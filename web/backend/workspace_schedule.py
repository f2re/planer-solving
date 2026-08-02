"""Workspace-aware validation and schedule generation routes."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
import uuid

from fastapi import APIRouter, Request

from src.data_loader import DataLoader
from src.exporter import export_to_excel
from src.schedule_analyzer import ScheduleLayout
from src.transformer import transform_to_teacher_grid
from src.weekly_exporter import generate_weekly_semester_schedule
from web.backend.analysis_api import analyze_files, request_uploads
from web.backend.app_context import ApplicationContext
from web.backend.schemas import (
    FileUploadDetail,
    GenerateScheduleRequest,
    ScheduleUploadResponse,
    ValidateLayoutRequest,
    ValidateLayoutResponse,
)

logger = logging.getLogger(__name__)


def build_schedule_router(context: ApplicationContext) -> APIRouter:
    router = APIRouter(tags=["schedule"])

    def workspace(workspace_id: str | None = None) -> Dict[str, Any]:
        return context.workspace_repository.get_workspace(workspace_id)

    def teacher_file(session_id: str, selected_workspace: Dict[str, Any]) -> Path:
        return context.sessions.write_snapshot(
            session_id,
            f"teachers-{selected_workspace['id']}.json",
            selected_workspace.get("teachers", []),
        )

    @router.post("/api/analysis/{session_id}/validate", response_model=ValidateLayoutResponse)
    def validate_layout(session_id: str, request: ValidateLayoutRequest) -> ValidateLayoutResponse:
        manifest = context.sessions.load_manifest(session_id)
        item = context.sessions.manifest_file(manifest, request.file_id)
        selected_workspace = workspace(request.workspace_id)
        loader = DataLoader(str(teacher_file(session_id, selected_workspace)))
        loader.load_group_schedule(
            str(context.sessions.stored_path(session_id, item)),
            group_name=request.group_name,
            layout=ScheduleLayout.from_dict(request.layout),
        )
        report = loader.last_report
        status = "error" if report.get("errors") else (
            "warning" if report.get("warnings") else "success"
        )
        return ValidateLayoutResponse(status=status, report=report)

    def generate_from_session(
        session_id: str,
        request: GenerateScheduleRequest,
    ) -> ScheduleUploadResponse:
        manifest = context.sessions.load_manifest(session_id)
        specs = [spec for spec in request.files if spec.enabled]
        if not specs:
            return ScheduleUploadResponse(
                status="error",
                message="Не выбран ни один файл для обработки.",
            )

        selected_workspace = workspace(request.workspace_id)
        teachers = selected_workspace.get("teachers", [])
        loader = DataLoader(str(teacher_file(session_id, selected_workspace)))
        lessons_all = []
        details: List[FileUploadDetail] = []
        reports: List[Dict[str, Any]] = []

        for spec in specs:
            item = context.sessions.manifest_file(manifest, spec.file_id)
            try:
                lessons = loader.load_group_schedule(
                    str(context.sessions.stored_path(session_id, item)),
                    group_name=spec.group_name,
                    layout=ScheduleLayout.from_dict(spec.layout),
                )
                report = dict(loader.last_report)
                reports.append(report)
                if report.get("errors"):
                    status = "error"
                    message = "; ".join(report["errors"])
                elif report.get("warnings"):
                    status = "warning"
                    message = (
                        f"Найдено занятий: {len(lessons)}. "
                        "Требуется проверить предупреждения."
                    )
                    lessons_all.extend(lessons)
                else:
                    status = "success"
                    message = f"Найдено занятий: {len(lessons)}."
                    lessons_all.extend(lessons)
                details.append(FileUploadDetail(
                    file_id=spec.file_id,
                    filename=item["filename"],
                    status=status,
                    message=message,
                    lesson_count=len(lessons),
                ))
            except Exception:
                logger.exception(
                    "Cannot parse %s in analysis session %s",
                    item.get("filename", spec.file_id),
                    session_id,
                )
                details.append(FileUploadDetail(
                    file_id=spec.file_id,
                    filename=item["filename"],
                    status="error",
                    message="Файл не обработан из-за внутренней ошибки парсинга.",
                    lesson_count=0,
                ))

        if not lessons_all:
            return ScheduleUploadResponse(
                status="error",
                message="После проверки разметки не найдено ни одного занятия без критических ошибок.",
                details=details,
                reports=reports,
                warnings=list(loader.warnings),
            )
        filtered = [
            lesson for lesson in lessons_all
            if str(lesson.teacher).strip().casefold() not in {"", "unknown", "none"}
        ]
        if not filtered:
            return ScheduleUploadResponse(
                status="error",
                message=(
                    "Занятия найдены, но преподаватели не определены. "
                    "Проверьте активное пространство, блок дисциплин и список сотрудников."
                ),
                details=details,
                reports=reports,
                warnings=list(loader.warnings),
            )

        settings = selected_workspace.get("settings", {})
        start_date = settings.get("schedule_start_date", "2026-02-10")
        end_date = settings.get("schedule_end_date", "2026-06-30")
        transformed = transform_to_teacher_grid(
            filtered,
            teachers,
            start_date_str=start_date,
            end_date_str=end_date,
        )
        output_id = str(uuid.uuid4())
        filename = f"schedule_{output_id}.xlsx"
        export_to_excel(
            transformed,
            teachers,
            str(context.paths.output_dir / filename),
        )

        warnings = list(loader.warnings)
        weekly_filename: Optional[str] = None
        if context.paths.weekly_template.exists():
            weekly_filename = f"weekly_schedule_{output_id}.xlsx"
            try:
                generate_weekly_semester_schedule(
                    teachers_config=teachers,
                    lessons=lessons_all,
                    template_path=str(context.paths.weekly_template),
                    output_path=str(context.paths.output_dir / weekly_filename),
                    start_date_str=start_date,
                    end_date_str=end_date,
                )
            except Exception:
                logger.exception(
                    "Cannot generate weekly schedule for workspace %s",
                    selected_workspace.get("id"),
                )
                weekly_filename = None
                warnings.append(
                    "Недельный файл не сформирован из-за внутренней ошибки экспорта."
                )
        else:
            warnings.append(
                "Недельный файл не сформирован: отсутствует шаблон obrazec/Недельное.xlsx."
            )

        has_attention = any(item.status != "success" for item in details) or bool(warnings)
        return ScheduleUploadResponse(
            filename=filename,
            weekly_filename=weekly_filename,
            status="warning" if has_attention else "success",
            message=(
                f"Расписание пространства «{selected_workspace['name']}» сформировано, "
                "но часть данных требует внимания."
                if has_attention
                else f"Расписание пространства «{selected_workspace['name']}» сформировано."
            ),
            details=details,
            warnings=warnings,
            reports=reports,
        )

    @router.post("/api/analysis/{session_id}/generate", response_model=ScheduleUploadResponse)
    def generate_schedule(
        session_id: str,
        request: GenerateScheduleRequest,
    ) -> ScheduleUploadResponse:
        return generate_from_session(session_id, request)

    @router.post("/api/upload", response_model=ScheduleUploadResponse)
    async def upload_compatibility(http_request: Request) -> ScheduleUploadResponse:
        analysis = await analyze_files(context, await request_uploads(http_request))
        specs = [{
            "file_id": item.file_id,
            "group_name": item.group_name,
            "layout": item.analysis["layout"],
            "enabled": True,
        } for item in analysis.files if item.analysis and item.status != "error"]
        generation_request = GenerateScheduleRequest(
            files=specs,
            workspace_id=context.workspace_repository.default_workspace_id(),
        )
        return generate_from_session(analysis.session_id, generation_request)

    return router
