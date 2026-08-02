"""Analysis-session preview, cleanup and generated-file download routes."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse

from src.schedule_analyzer import ScheduleAnalyzer
from web.backend.app_context import ApplicationContext
from web.backend.errors import ApplicationError, UploadedFileNotFound


def build_session_router(context: ApplicationContext) -> APIRouter:
    router = APIRouter(tags=["analysis"])

    @router.get("/api/analysis/{session_id}/files/{file_id}/preview")
    def preview_schedule(
        session_id: str,
        file_id: str,
        region: str = Query("schedule"),
        row_start: Optional[int] = Query(None, ge=1),
        row_end: Optional[int] = Query(None, ge=1),
        col_start: Optional[int] = Query(None, ge=1),
        col_end: Optional[int] = Query(None, ge=1),
        sheet_name: Optional[str] = Query(None),
    ) -> Dict[str, Any]:
        if region not in {"schedule", "legend", "custom"}:
            raise ApplicationError("Неизвестная область предпросмотра.")
        manifest = context.sessions.load_manifest(session_id)
        item = context.sessions.manifest_file(manifest, file_id)
        analysis = item.get("analysis")
        if not isinstance(analysis, dict):
            raise ApplicationError("Для файла нет результатов анализа.")
        defaults = analysis["legend_preview"] if region == "legend" else analysis["schedule_preview"]
        selected_row_start = row_start or int(defaults["row_start"])
        selected_row_end = row_end or int(defaults["row_end"])
        selected_col_start = col_start or int(defaults["col_start"])
        selected_col_end = col_end or int(defaults["col_end"])
        if selected_row_end < selected_row_start or selected_col_end < selected_col_start:
            raise ApplicationError("Неверно задан диапазон предпросмотра.")
        try:
            return ScheduleAnalyzer().preview(
                str(context.sessions.stored_path(session_id, item)),
                sheet_name or str(analysis["selected_sheet"]),
                selected_row_start,
                selected_row_end,
                selected_col_start,
                selected_col_end,
            )
        except ValueError as exc:
            raise ApplicationError(str(exc)) from exc

    @router.delete("/api/analysis/{session_id}")
    def delete_analysis_session(session_id: str) -> Dict[str, str]:
        context.sessions.delete(session_id)
        return {"status": "success"}

    @router.get("/api/download/{filename}")
    def download_file(filename: str) -> FileResponse:
        safe_name = Path(filename).name
        file_path = (context.paths.output_dir / safe_name).resolve()
        if (
            not safe_name
            or file_path.parent != context.paths.output_dir.resolve()
            or not file_path.is_file()
        ):
            raise UploadedFileNotFound("Файл не найден.")
        return FileResponse(
            path=str(file_path),
            filename=safe_name,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    return router
