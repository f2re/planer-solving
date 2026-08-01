"""Workspace-aware validation and schedule generation routes."""
from __future__ import annotations

import json
from pathlib import Path
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter

from src.data_loader import DataLoader
from src.schedule_analyzer import ScheduleLayout
from web.backend.schemas import (
    FileUploadDetail,
    GenerateScheduleRequest,
    ScheduleUploadResponse,
    ValidateLayoutRequest,
    ValidateLayoutResponse,
)


def build_schedule_router(context: Any, workspace_getter: Any, default_workspace_id: Any) -> APIRouter:
    router = APIRouter()

    def teacher_file(session_id: str, workspace: Dict[str, Any]) -> Path:
        path = context._safe_session_dir(session_id) / f"teachers-{workspace['id']}.json"
        context._atomic_json_write(path, workspace.get("teachers", []))
        return path

    @router.post("/api/analysis/{session_id}/validate", response_model=ValidateLayoutResponse)
    def validate_layout(session_id: str, request: ValidateLayoutRequest) -> ValidateLayoutResponse:
        manifest = context._load_manifest(session_id)
        item = context._manifest_file(manifest, request.file_id)
        workspace = workspace_getter(request.workspace_id)
        loader = DataLoader(str(teacher_file(session_id, workspace)))
        loader.load_group_schedule(
            str(context._stored_path(session_id, item)),
            group_name=request.group_name,
            layout=ScheduleLayout.from_dict(request.layout),
        )
        report = loader.last_report
        status = "error" if report.get("errors") else ("warning" if report.get("warnings") else "success")
        return ValidateLayoutResponse(status=status, report=report)

    def generate_from_session(session_id: str, request: GenerateScheduleRequest) -> ScheduleUploadResponse:
        manifest = context._load_manifest(session_id)
        specs = [spec for spec in request.files if spec.enabled]
        if not specs:
            return ScheduleUploadResponse(status="error", message="Не выбран ни один файл для обработки.")

        workspace = workspace_getter(request.workspace_id)
        teachers = workspace.get("teachers", [])
        loader = DataLoader(str(teacher_file(session_id, workspace)))
        lessons_all = []
        details: List[FileUploadDetail] = []
        reports: List[Dict[str, Any]] = []

        for spec in specs:
            item = context._manifest_file(manifest, spec.file_id)
            try:
                lessons = loader.load_group_schedule(
                    str(context._stored_path(session_id, item)),
                    group_name=spec.group_name,
                    layout=ScheduleLayout.from_dict(spec.layout),
                )
                report = dict(loader.last_report)
                reports.append(report)
                if report.get("errors"):
                    status, message = "error", "; ".join(report["errors"])
                elif report.get("warnings"):
                    status, message = "warning", f"Найдено занятий: {len(lessons)}. Требуется проверить предупреждения."
                else:
                    status, message = "success", f"Найдено занятий: {len(lessons)}."
                lessons_all.extend(lessons)
                details.append(FileUploadDetail(
                    file_id=spec.file_id, filename=item["filename"], status=status,
                    message=message, lesson_count=len(lessons),
                ))
            except Exception as exc:
                details.append(FileUploadDetail(
                    file_id=spec.file_id, filename=item["filename"], status="error",
                    message=str(exc), lesson_count=0,
                ))

        if not lessons_all:
            return ScheduleUploadResponse(
                status="error", message="После проверки разметки не найдено ни одного занятия.",
                details=details, reports=reports, warnings=list(loader.warnings),
            )
        filtered = [lesson for lesson in lessons_all if lesson.teacher != "Unknown"]
        if not filtered:
            return ScheduleUploadResponse(
                status="error",
                message="Занятия найдены, но преподаватели не определены. Проверьте активное пространство, блок дисциплин и список сотрудников.",
                details=details, reports=reports, warnings=list(loader.warnings),
            )

        settings = workspace.get("settings", {})
        start_date = settings.get("schedule_start_date", "2026-02-10")
        end_date = settings.get("schedule_end_date", "2026-06-30")
        transformed = context.transform_to_teacher_grid(
            filtered, teachers, start_date_str=start_date, end_date_str=end_date,
        )
        output_id = str(uuid.uuid4())
        filename = f"schedule_{output_id}.xlsx"
        context.export_to_excel(transformed, teachers, str(context.OUTPUT_DIR / filename))

        warnings = list(loader.warnings)
        weekly_filename: Optional[str] = None
        weekly_template = context.BASE_DIR / "obrazec" / "Недельное.xlsx"
        if weekly_template.exists():
            weekly_filename = f"weekly_schedule_{output_id}.xlsx"
            try:
                context.generate_weekly_semester_schedule(
                    teachers_config=teachers, lessons=lessons_all,
                    template_path=str(weekly_template),
                    output_path=str(context.OUTPUT_DIR / weekly_filename),
                    start_date_str=start_date, end_date_str=end_date,
                )
            except Exception as exc:
                weekly_filename = None
                warnings.append(f"Недельный файл не сформирован: {exc}")
        else:
            warnings.append("Недельный файл не сформирован: отсутствует шаблон obrazec/Недельное.xlsx.")

        has_attention = any(item.status != "success" for item in details) or bool(warnings)
        return ScheduleUploadResponse(
            filename=filename, weekly_filename=weekly_filename,
            status="warning" if has_attention else "success",
            message=(f"Расписание пространства «{workspace['name']}» сформировано, но часть данных требует внимания."
                     if has_attention else f"Расписание пространства «{workspace['name']}» сформировано."),
            details=details, warnings=warnings, reports=reports,
        )

    @router.post("/api/analysis/{session_id}/generate", response_model=ScheduleUploadResponse)
    def generate_schedule(session_id: str, request: GenerateScheduleRequest) -> ScheduleUploadResponse:
        return generate_from_session(session_id, request)

    @router.post("/api/upload", response_model=ScheduleUploadResponse)
    async def upload_compatibility(files: List[Any] = context.File(...)) -> ScheduleUploadResponse:
        analysis = await context.analyze_schedules(files)
        specs = [{
            "file_id": item.file_id, "group_name": item.group_name,
            "layout": item.analysis["layout"], "enabled": True,
        } for item in analysis.files if item.analysis and item.status != "error"]
        request = GenerateScheduleRequest(files=specs, workspace_id=default_workspace_id())
        return generate_from_session(analysis.session_id, request)

    return router
