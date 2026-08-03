"""Workspace-aware validation, generation and durable processing history."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional
import uuid

from fastapi import APIRouter, Request

from src.data_loader import DataLoader
from src.exporter import export_to_excel
from src.schedule_analyzer import ScheduleLayout
from src.transformer import transform_to_teacher_grid
from src.weekly_exporter import generate_weekly_semester_schedule
from src.workspace_domain import default_semester_settings
from web.backend.analysis_api import analyze_files, request_uploads
from web.backend.app_context import ApplicationContext
from web.backend.auth import actor_from_request
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
    repository = context.workspace_repository

    def workspace(workspace_id: str | None = None) -> Dict[str, Any]:
        return repository.get_workspace(workspace_id)

    def teacher_file(session_id: str, selected_workspace: Dict[str, Any]) -> Path:
        return context.sessions.write_snapshot(
            session_id,
            f"teachers-{selected_workspace['id']}.json",
            selected_workspace.get("teachers", []),
        )

    @router.post("/api/analysis/{session_id}/validate", response_model=ValidateLayoutResponse)
    def validate_layout(
        session_id: str,
        payload: ValidateLayoutRequest,
    ) -> ValidateLayoutResponse:
        manifest = context.sessions.load_manifest(session_id)
        item = context.sessions.manifest_file(manifest, payload.file_id)
        selected_workspace = workspace(payload.workspace_id)
        loader = DataLoader(str(teacher_file(session_id, selected_workspace)))
        loader.load_group_schedule(
            str(context.sessions.stored_path(session_id, item)),
            group_name=payload.group_name,
            layout=ScheduleLayout.from_dict(payload.layout),
        )
        report = loader.last_report
        status = "error" if report.get("errors") else (
            "warning" if report.get("warnings") else "success"
        )
        return ValidateLayoutResponse(status=status, report=report)

    def finish_failed(
        run_id: str,
        *,
        message: str,
        details: List[FileUploadDetail],
        reports: List[Dict[str, Any]],
        warnings: List[str],
        actor: Mapping[str, Any],
    ) -> ScheduleUploadResponse:
        repository.finish_processing_run(
            run_id,
            status="error",
            lesson_count=0,
            warning_count=len(warnings),
            error_count=max(1, sum(1 for item in details if item.status == "error")),
            selected_templates=[],
            report={"message": message, "reports": reports},
            artifacts=[],
            actor=actor,
        )
        return ScheduleUploadResponse(
            run_id=run_id,
            status="error",
            message=message,
            details=details,
            reports=reports,
            warnings=warnings,
        )

    def generate_from_session(
        session_id: str,
        payload: GenerateScheduleRequest,
        *,
        actor: Mapping[str, Any],
    ) -> ScheduleUploadResponse:
        manifest = context.sessions.load_manifest(session_id)
        specs = [spec for spec in payload.files if spec.enabled]
        if not specs:
            return ScheduleUploadResponse(
                status="error",
                message="Не выбран ни один файл для обработки.",
            )

        selected_workspace = workspace(payload.workspace_id)
        run_id = repository.start_processing_run(
            workspace_id=selected_workspace["id"],
            session_id=session_id,
            actor=actor,
            source_count=len(specs),
        )
        teachers = selected_workspace.get("teachers", [])
        loader = DataLoader(str(teacher_file(session_id, selected_workspace)))
        lessons_all = []
        details: List[FileUploadDetail] = []
        reports: List[Dict[str, Any]] = []
        selected_templates: List[Dict[str, Any]] = []

        for spec in specs:
            item = context.sessions.manifest_file(manifest, spec.file_id)
            stored_path = context.sessions.stored_path(session_id, item)
            selected_match = dict((item.get("template_match") or {}).get("selected") or {})
            if selected_match.get("template_id"):
                selected_templates.append(selected_match)
            try:
                lessons = loader.load_group_schedule(
                    str(stored_path),
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
                repository.record_processing_file(
                    run_id,
                    file_id=spec.file_id,
                    filename=item["filename"],
                    file_path=stored_path,
                    group_name=spec.group_name,
                    layout=spec.layout,
                    report=report,
                    template_match=selected_match,
                )
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
                error_report = {"errors": ["Внутренняя ошибка парсинга."], "warnings": []}
                repository.record_processing_file(
                    run_id,
                    file_id=spec.file_id,
                    filename=item["filename"],
                    file_path=stored_path,
                    group_name=spec.group_name,
                    layout=spec.layout,
                    report=error_report,
                    template_match=selected_match,
                )
                details.append(FileUploadDetail(
                    file_id=spec.file_id,
                    filename=item["filename"],
                    status="error",
                    message="Файл не обработан из-за внутренней ошибки парсинга.",
                    lesson_count=0,
                ))

        accumulated_warnings = list(loader.warnings)
        if not lessons_all:
            return finish_failed(
                run_id,
                message="После проверки разметки не найдено ни одного занятия без критических ошибок.",
                details=details,
                reports=reports,
                warnings=accumulated_warnings,
                actor=actor,
            )
        filtered = [
            lesson for lesson in lessons_all
            if str(lesson.teacher).strip().casefold() not in {"", "unknown", "none"}
        ]
        if not filtered:
            return finish_failed(
                run_id,
                message=(
                    "Занятия найдены, но преподаватели не определены. "
                    "Проверьте активное пространство, блок дисциплин и список сотрудников."
                ),
                details=details,
                reports=reports,
                warnings=accumulated_warnings,
                actor=actor,
            )

        settings = selected_workspace.get("settings") or {}
        defaults = default_semester_settings()
        start_date = str(settings.get("schedule_start_date") or defaults["schedule_start_date"])
        end_date = str(settings.get("schedule_end_date") or defaults["schedule_end_date"])
        transformed = transform_to_teacher_grid(
            filtered,
            teachers,
            start_date_str=start_date,
            end_date_str=end_date,
        )
        output_id = str(uuid.uuid4())
        filename = f"schedule_{output_id}.xlsx"
        output_path = context.paths.output_dir / filename
        export_to_excel(transformed, teachers, str(output_path))

        warnings = list(accumulated_warnings)
        artifacts: List[Dict[str, Any]] = [{"kind": "schedule", "path": output_path}]
        weekly_filename: Optional[str] = None
        if context.paths.weekly_template.exists():
            weekly_filename = f"weekly_schedule_{output_id}.xlsx"
            weekly_path = context.paths.output_dir / weekly_filename
            try:
                generate_weekly_semester_schedule(
                    teachers_config=teachers,
                    lessons=lessons_all,
                    template_path=str(context.paths.weekly_template),
                    output_path=str(weekly_path),
                    start_date_str=start_date,
                    end_date_str=end_date,
                )
                artifacts.append({"kind": "weekly", "path": weekly_path})
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
        status = "warning" if has_attention else "success"
        repository.finish_processing_run(
            run_id,
            status=status,
            lesson_count=len(filtered),
            warning_count=len(warnings) + sum(1 for item in details if item.status == "warning"),
            error_count=sum(1 for item in details if item.status == "error"),
            selected_templates=selected_templates,
            report={"reports": reports, "details": [item.model_dump() for item in details]},
            artifacts=artifacts,
            actor=actor,
        )
        return ScheduleUploadResponse(
            run_id=run_id,
            filename=filename,
            weekly_filename=weekly_filename,
            status=status,
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
        payload: GenerateScheduleRequest,
        request: Request,
    ) -> ScheduleUploadResponse:
        return generate_from_session(session_id, payload, actor=actor_from_request(request))

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
            workspace_id=repository.default_workspace_id(),
        )
        return generate_from_session(
            analysis.session_id,
            generation_request,
            actor=actor_from_request(http_request),
        )

    return router
