"""Workspace-aware validation, generation and durable processing history."""
from __future__ import annotations

import logging
import os
from pathlib import Path
import shutil
from typing import Any, Dict, List, Mapping, Optional
import uuid

from fastapi import APIRouter, Request

from src.data_loader import DataLoader
from src.exporter import export_to_excel
from src.schedule_analyzer import ScheduleAnalyzer, ScheduleLayout
from src.schedule_period import SchedulePeriodError, resolve_schedule_calendar
from src.transformer import transform_to_teacher_grid
from src.weekly_exporter import generate_weekly_semester_schedule
from src.workspace_domain import default_semester_settings
from web.backend.analysis_api import analyze_files, request_uploads
from web.backend.app_context import ApplicationContext
from web.backend.auth import actor_from_request
from web.backend.errors import ApplicationError
from web.backend.schemas import (
    FileUploadDetail,
    GenerateFileSpec,
    GenerateScheduleRequest,
    ScheduleUploadResponse,
    ValidateLayoutRequest,
    ValidateLayoutResponse,
)

logger = logging.getLogger(__name__)


def _model_dict(model: Any) -> Dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def _archive_source(
    context: ApplicationContext,
    run_id: str,
    file_id: str,
    source: Path,
) -> str:
    archive_root = (context.paths.data_dir / "history").resolve()
    destination_dir = archive_root / run_id / "sources"
    destination_dir.mkdir(parents=True, exist_ok=True)
    extension = source.suffix.lower() if source.suffix.lower() in {".xlsx", ".xlsm"} else ".xlsx"
    destination = destination_dir / f"{file_id}{extension}"
    if not destination.exists():
        try:
            os.link(source, destination)
        except OSError:
            shutil.copy2(source, destination)
    return destination.relative_to(context.paths.data_dir.resolve()).as_posix()


def _resolve_archive(context: ApplicationContext, relative: str) -> Path:
    root = context.paths.data_dir.resolve()
    path = (root / relative).resolve()
    history_root = (root / "history").resolve()
    if history_root not in path.parents or not path.is_file():
        raise ApplicationError(
            "Архивный исходный файл недоступен. Повторите загрузку вручную.",
            status_code=409,
            code="source_archive_missing",
        )
    return path


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
                report["source_archive"] = _archive_source(
                    context,
                    run_id,
                    spec.file_id,
                    stored_path,
                )
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
                error_report = {
                    "file": item.get("filename", spec.file_id),
                    "group": spec.group_name,
                    "errors": ["Внутренняя ошибка парсинга."],
                    "warnings": [],
                }
                try:
                    error_report["source_archive"] = _archive_source(
                        context,
                        run_id,
                        spec.file_id,
                        stored_path,
                    )
                except OSError:
                    pass
                reports.append(error_report)
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
        settings = selected_workspace.get("settings") or {}
        defaults = default_semester_settings()
        start_date = str(settings.get("schedule_start_date") or defaults["schedule_start_date"])
        end_date = str(settings.get("schedule_end_date") or defaults["schedule_end_date"])

        try:
            calendar = resolve_schedule_calendar(
                lessons_all,
                start_date_str=start_date,
                end_date_str=end_date,
                period_reports=reports,
            )
        except SchedulePeriodError as exc:
            period_report = dict(exc.report)
            period_report.setdefault("file", "Проверка периода")
            period_report.setdefault("group", "Все загруженные расписания")
            reports.append(period_report)
            for warning in exc.warnings:
                if warning not in accumulated_warnings:
                    accumulated_warnings.append(warning)
            reason = "; ".join(exc.errors[:3])
            if len(exc.errors) > 3:
                reason += f"; ещё ошибок: {len(exc.errors) - 3}."
            return finish_failed(
                run_id,
                message=f"Формирование остановлено: период расписаний не согласован. {reason}",
                details=details,
                reports=reports,
                warnings=accumulated_warnings,
                actor=actor,
            )

        for warning in calendar.warnings:
            if warning not in accumulated_warnings:
                accumulated_warnings.append(warning)

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

        transformed = transform_to_teacher_grid(
            filtered,
            teachers,
            start_date_str=start_date,
            end_date_str=end_date,
            period_reports=reports,
            resolved_calendar=calendar,
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
                    lessons=filtered,
                    template_path=str(context.paths.weekly_template),
                    output_path=str(weekly_path),
                    start_date_str=start_date,
                    end_date_str=end_date,
                    period_reports=reports,
                    resolved_calendar=calendar,
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
            report={
                "reports": reports,
                "details": [_model_dict(item) for item in details],
                "period": transformed["period_report"],
            },
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

    @router.post("/api/workspaces/{workspace_id}/runs/{run_id}/repeat", response_model=ScheduleUploadResponse)
    def repeat_processing_run(
        workspace_id: str,
        run_id: str,
        request: Request,
    ) -> ScheduleUploadResponse:
        actor = actor_from_request(request)
        previous = repository.get_processing_run(run_id)
        if previous["workspace_id"] != workspace_id:
            raise ApplicationError("Запуск относится к другому пространству.", status_code=404)
        session_id, session_dir = context.sessions.create()
        manifest_files: List[Dict[str, Any]] = []
        specs: List[GenerateFileSpec] = []
        for source in previous.get("files", []):
            archived = _resolve_archive(
                context,
                str((source.get("report") or {}).get("source_archive") or ""),
            )
            file_id = str(uuid.uuid4())
            destination = session_dir / f"{file_id}{archived.suffix.lower()}"
            try:
                os.link(archived, destination)
            except OSError:
                shutil.copy2(archived, destination)
            manifest_files.append({
                "file_id": file_id,
                "filename": source["filename"],
                "group_name": source.get("group_name") or Path(source["filename"]).stem,
                "stored_name": destination.name,
                "status": "success",
                "message": "Восстановлено из истории обработки.",
                "analysis": None,
                "template_match": {
                    "selected": {
                        "template_id": source.get("template_id"),
                        "revision_no": source.get("template_revision"),
                        "score": source.get("match_score"),
                    }
                },
            })
            specs.append(GenerateFileSpec(
                file_id=file_id,
                group_name=source.get("group_name") or Path(source["filename"]).stem,
                layout=source.get("layout") or {},
                enabled=True,
            ))
        context.sessions.save_manifest(
            session_id,
            {"session_id": session_id, "created_at": previous.get("created_at"), "files": manifest_files},
        )
        repository.audit(
            actor=actor,
            action="processing.repeat",
            entity_type="processing_run",
            entity_id=run_id,
            workspace_id=workspace_id,
            summary="Повтор обработки с прежними исходниками и разметкой",
        )
        return generate_from_session(
            session_id,
            GenerateScheduleRequest(files=specs, workspace_id=workspace_id),
            actor=actor,
        )

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
