"""Workspace-aware validation, generation and durable processing history."""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path
import shutil
from typing import Any, Dict, List, Optional
import uuid

from fastapi import APIRouter, Depends, Request

from src.data_loader import DataLoader
from src.exporter import export_to_excel
from src.operations_domain import AuthenticatedUser
from src.schedule_analyzer import ScheduleLayout
from src.transformer import transform_to_teacher_grid
from src.weekly_exporter import generate_weekly_semester_schedule
from src.workspace_domain import default_semester_settings
from web.backend.analysis_api import analyze_files, request_uploads
from web.backend.app_context import ApplicationContext
from web.backend.auth import operator_dependency
from web.backend.errors import ApplicationError
from web.backend.schemas import (
    FileUploadDetail,
    GenerateScheduleRequest,
    ScheduleUploadResponse,
    ValidateLayoutRequest,
    ValidateLayoutResponse,
)

logger = logging.getLogger(__name__)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_schedule_router(context: ApplicationContext) -> APIRouter:
    router = APIRouter(tags=["schedule"])
    operator = operator_dependency(context)

    def workspace(workspace_id: str | None = None) -> Dict[str, Any]:
        return context.workspace_repository.get_workspace(workspace_id)

    def teacher_file(session_id: str, selected_workspace: Dict[str, Any]) -> Path:
        return context.sessions.write_snapshot(
            session_id,
            f"teachers-{selected_workspace['id']}.json",
            selected_workspace.get("teachers", []),
        )

    @router.post("/api/analysis/{session_id}/validate", response_model=ValidateLayoutResponse)
    def validate_layout(
        session_id: str,
        request: ValidateLayoutRequest,
        _: AuthenticatedUser = Depends(operator),
    ) -> ValidateLayoutResponse:
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
        user: AuthenticatedUser,
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
        settings = selected_workspace.get("settings") or {}
        defaults = default_semester_settings()
        start_date = str(settings.get("schedule_start_date") or defaults["schedule_start_date"])
        end_date = str(settings.get("schedule_end_date") or defaults["schedule_end_date"])
        run_id = context.operations.create_processing_run(
            workspace_id=selected_workspace["id"],
            user_id=user.id,
            source_session_id=session_id,
            settings={
                "schedule_start_date": start_date,
                "schedule_end_date": end_date,
            },
            total_files=len(specs),
        )
        run_root = context.paths.history_root / run_id
        source_root = run_root / "sources"
        artifact_root = run_root / "artifacts"
        source_root.mkdir(parents=True, exist_ok=True)
        artifact_root.mkdir(parents=True, exist_ok=True)

        loader = DataLoader(str(teacher_file(session_id, selected_workspace)))
        lessons_all = []
        details: List[FileUploadDetail] = []
        reports: List[Dict[str, Any]] = []
        success_files = warning_files = error_files = 0

        for spec in specs:
            item = context.sessions.manifest_file(manifest, spec.file_id)
            source = context.sessions.stored_path(session_id, item)
            historical_source = source_root / f"{spec.file_id}{source.suffix.lower()}"
            shutil.copy2(source, historical_source)
            source_hash = _sha256(historical_source)
            selected_match = (item.get("template_match") or {}).get("selected") or {}
            report: Dict[str, Any] = {}
            lessons = []
            try:
                lessons = loader.load_group_schedule(
                    str(source),
                    group_name=spec.group_name,
                    layout=ScheduleLayout.from_dict(spec.layout),
                )
                report = dict(loader.last_report)
                reports.append(report)
                if report.get("errors"):
                    status = "error"
                    message = "; ".join(report["errors"])
                    error_files += 1
                elif report.get("warnings"):
                    status = "warning"
                    message = (
                        f"Найдено занятий: {len(lessons)}. "
                        "Требуется проверить предупреждения."
                    )
                    lessons_all.extend(lessons)
                    warning_files += 1
                else:
                    status = "success"
                    message = f"Найдено занятий: {len(lessons)}."
                    lessons_all.extend(lessons)
                    success_files += 1
            except Exception:
                logger.exception(
                    "Cannot parse %s in analysis session %s",
                    item.get("filename", spec.file_id),
                    session_id,
                )
                status = "error"
                message = "Файл не обработан из-за внутренней ошибки парсинга."
                error_files += 1
                report = {"errors": [message], "warnings": [], "lesson_count": 0}
                reports.append(report)

            context.operations.add_processing_file(
                run_id=run_id,
                original_name=item["filename"],
                group_name=spec.group_name,
                source_sha256=source_hash,
                source_path=str(historical_source),
                template_id=selected_match.get("template_id"),
                template_revision_id=selected_match.get("template_revision_id"),
                component_id=selected_match.get("component_id"),
                layout=spec.layout,
                analysis=item.get("analysis") or {},
                validation=report,
                lesson_count=len(lessons),
                status=status,
                message=message,
            )
            details.append(FileUploadDetail(
                file_id=spec.file_id,
                filename=item["filename"],
                status=status,
                message=message,
                lesson_count=len(lessons),
            ))

            template_id = selected_match.get("template_id")
            if template_id:
                metrics = {
                    "lesson_count": len(lessons),
                    "mapped_lessons": int(report.get("mapped_lessons", 0) or 0),
                    "errors": len(report.get("errors", []) or []),
                    "warnings": len(report.get("warnings", []) or []),
                }
                quality = round(
                    100 * metrics["mapped_lessons"] / max(1, metrics["lesson_count"])
                )
                fingerprint = (item.get("analysis") or {}).get("fingerprint") or {}
                context.operations.record_template_learning(
                    workspace_id=selected_workspace["id"],
                    template_id=template_id,
                    revision_id=selected_match.get("template_revision_id"),
                    workbook_signature=fingerprint.get("signature"),
                    sheet_signature=None,
                    fingerprint=fingerprint,
                    outcome="success" if status != "error" and lessons else "failure",
                    score=float(selected_match.get("score", 0) or 0),
                    quality_percent=quality,
                    metrics=metrics,
                )

        if not lessons_all:
            message = "После проверки разметки не найдено ни одного занятия без критических ошибок."
            context.operations.finish_processing_run(
                run_id=run_id,
                status="error",
                message=message,
                success_files=success_files,
                warning_files=warning_files,
                error_files=error_files,
                user_id=user.id,
            )
            return ScheduleUploadResponse(
                run_id=run_id,
                status="error",
                message=message,
                details=details,
                reports=reports,
                warnings=list(loader.warnings),
            )

        filtered = [
            lesson for lesson in lessons_all
            if str(lesson.teacher).strip().casefold() not in {"", "unknown", "none"}
        ]
        if not filtered:
            message = (
                "Занятия найдены, но преподаватели не определены. "
                "Проверьте активное пространство, блок дисциплин и список сотрудников."
            )
            context.operations.finish_processing_run(
                run_id=run_id,
                status="error",
                message=message,
                success_files=success_files,
                warning_files=warning_files,
                error_files=max(1, error_files),
                user_id=user.id,
            )
            return ScheduleUploadResponse(
                run_id=run_id,
                status="error",
                message=message,
                details=details,
                reports=reports,
                warnings=list(loader.warnings),
            )

        try:
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
            historical_output = artifact_root / filename
            shutil.copy2(output_path, historical_output)
            context.operations.add_processing_artifact(
                run_id=run_id,
                kind="general",
                filename=filename,
                stored_path=str(historical_output),
                sha256=_sha256(historical_output),
                size=historical_output.stat().st_size,
            )
        except Exception as exc:
            logger.exception("Cannot generate consolidated schedule")
            context.operations.finish_processing_run(
                run_id=run_id,
                status="error",
                message="Не удалось сформировать итоговый файл.",
                success_files=success_files,
                warning_files=warning_files,
                error_files=max(1, error_files),
                user_id=user.id,
            )
            raise ApplicationError("Не удалось сформировать итоговый файл.") from exc

        warnings = list(loader.warnings)
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
                historical_weekly = artifact_root / weekly_filename
                shutil.copy2(weekly_path, historical_weekly)
                context.operations.add_processing_artifact(
                    run_id=run_id,
                    kind="weekly",
                    filename=weekly_filename,
                    stored_path=str(historical_weekly),
                    sha256=_sha256(historical_weekly),
                    size=historical_weekly.stat().st_size,
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

        has_attention = error_files > 0 or warning_files > 0 or bool(warnings)
        status = "warning" if has_attention else "success"
        message = (
            f"Расписание пространства «{selected_workspace['name']}» сформировано, "
            "но часть данных требует внимания."
            if has_attention
            else f"Расписание пространства «{selected_workspace['name']}» сформировано."
        )
        context.operations.finish_processing_run(
            run_id=run_id,
            status=status,
            message=message,
            success_files=success_files,
            warning_files=warning_files,
            error_files=error_files,
            user_id=user.id,
        )
        return ScheduleUploadResponse(
            filename=filename,
            weekly_filename=weekly_filename,
            run_id=run_id,
            status=status,
            message=message,
            details=details,
            warnings=warnings,
            reports=reports,
        )

    @router.post("/api/analysis/{session_id}/generate", response_model=ScheduleUploadResponse)
    def generate_schedule(
        session_id: str,
        request: GenerateScheduleRequest,
        user: AuthenticatedUser = Depends(operator),
    ) -> ScheduleUploadResponse:
        return generate_from_session(session_id, request, user)

    @router.post("/api/upload", response_model=ScheduleUploadResponse)
    async def upload_compatibility(
        http_request: Request,
        user: AuthenticatedUser = Depends(operator),
    ) -> ScheduleUploadResponse:
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
        return generate_from_session(analysis.session_id, generation_request, user)

    return router
