"""Analysis-session restore, draft, preview, cleanup and download routes."""
from __future__ import annotations

import json
import os
from pathlib import Path
import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse

from src.schedule_analyzer import ScheduleAnalyzer
from web.backend.app_context import ApplicationContext
from web.backend.errors import ApplicationError, UploadedFileNotFound
from web.backend.schemas import AnalysisDraftRequest


MAX_DRAFT_BYTES = 4 * 1024 * 1024


def _model_dict(model: Any) -> Dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def _public_file(item: Dict[str, Any]) -> Dict[str, Any]:
    """Return enough state to rebuild the editor without exposing server paths."""

    result = {
        key: item.get(key)
        for key in (
            "file_id",
            "filename",
            "group_name",
            "status",
            "message",
            "analysis",
            "bytes_written",
            "template_match",
        )
    }
    return {key: value for key, value in result.items() if value is not None}


def build_session_router(context: ApplicationContext) -> APIRouter:
    router = APIRouter(tags=["analysis"])

    @router.get("/api/analysis/{session_id}")
    def restore_analysis_session(session_id: str) -> Dict[str, Any]:
        manifest = context.sessions.load_manifest(session_id)
        # Reading an active draft extends its 24-hour lifetime. The directory
        # mtime, not the browser cache, is the cleanup source of truth.
        try:
            os.utime(context.sessions.path(session_id), None)
        except OSError:
            pass
        return {
            "session_id": session_id,
            "created_at": manifest.get("created_at"),
            "updated_at": manifest.get("updated_at") or manifest.get("created_at"),
            "files": [_public_file(item) for item in manifest.get("files", []) if isinstance(item, dict)],
            "draft": manifest.get("draft") or {},
        }

    @router.put("/api/analysis/{session_id}/draft")
    def save_analysis_draft(
        session_id: str,
        payload: AnalysisDraftRequest,
    ) -> Dict[str, Any]:
        manifest = context.sessions.load_manifest(session_id)
        draft = _model_dict(payload)
        known_ids = {
            str(item.get("file_id"))
            for item in manifest.get("files", [])
            if isinstance(item, dict) and item.get("file_id")
        }
        supplied_ids = [item["file_id"] for item in draft.get("files", [])]
        unknown = sorted(set(supplied_ids) - known_ids)
        if unknown:
            raise ApplicationError(
                "Черновик содержит файлы, которых нет в текущем сеансе: " + ", ".join(unknown[:5]),
                status_code=409,
                code="draft_file_mismatch",
            )
        if len(supplied_ids) != len(set(supplied_ids)):
            raise ApplicationError(
                "Один файл повторяется в черновике несколько раз.",
                status_code=409,
                code="draft_file_duplicate",
            )
        selected_file_id = draft.get("selected_file_id")
        if selected_file_id and selected_file_id not in known_ids:
            raise ApplicationError(
                "Выбранный файл отсутствует в текущем сеансе.",
                status_code=409,
                code="draft_selected_file_missing",
            )
        for field_name in ("layouts", "period_overrides"):
            extra = sorted(set((draft.get(field_name) or {}).keys()) - known_ids)
            if extra:
                raise ApplicationError(
                    f"Поле {field_name} содержит неизвестные файлы: " + ", ".join(extra[:5]),
                    status_code=409,
                    code="draft_file_mismatch",
                )

        encoded = json.dumps(draft, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(encoded) > MAX_DRAFT_BYTES:
            raise ApplicationError(
                "Черновик слишком велик. Удалите лишние диагностические данные и повторите сохранение.",
                status_code=413,
                code="draft_too_large",
            )

        file_state = {item["file_id"]: item for item in draft.get("files", [])}
        for item in manifest.get("files", []):
            state = file_state.get(str(item.get("file_id")))
            if not state:
                continue
            item["group_name"] = str(state.get("group_name") or item.get("group_name") or "")[:240]

        now = time.time()
        draft["saved_at"] = now
        manifest["draft"] = draft
        manifest["updated_at"] = now
        context.sessions.save_manifest(session_id, manifest)
        return {
            "status": "success",
            "session_id": session_id,
            "saved_at": now,
            "bytes": len(encoded),
        }

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
        full_sheet: bool = Query(False),
    ) -> Dict[str, Any]:
        if region not in {"schedule", "legend", "custom"}:
            raise ApplicationError("Неизвестная область предпросмотра.")
        manifest = context.sessions.load_manifest(session_id)
        item = context.sessions.manifest_file(manifest, file_id)
        analysis = item.get("analysis")
        if not isinstance(analysis, dict):
            raise ApplicationError("Для файла нет результатов анализа.")

        if full_sheet:
            selected_row_start = 1
            selected_row_end = int(analysis.get("max_row") or 1)
            selected_col_start = 1
            selected_col_end = int(analysis.get("max_column") or 1)
            max_rows = 500
            max_columns = 160
        else:
            defaults = analysis["legend_preview"] if region == "legend" else analysis["schedule_preview"]
            selected_row_start = row_start or int(defaults["row_start"])
            selected_row_end = row_end or int(defaults["row_end"])
            selected_col_start = col_start or int(defaults["col_start"])
            selected_col_end = col_end or int(defaults["col_end"])
            max_rows = 140
            max_columns = 60

        if selected_row_end < selected_row_start or selected_col_end < selected_col_start:
            raise ApplicationError("Неверно задан диапазон предпросмотра.")
        try:
            result = ScheduleAnalyzer().preview(
                str(context.sessions.stored_path(session_id, item)),
                sheet_name or str(analysis["selected_sheet"]),
                selected_row_start,
                selected_row_end,
                selected_col_start,
                selected_col_end,
                max_rows=max_rows,
                max_columns=max_columns,
            )
            result["full_sheet"] = full_sheet
            result["truncated_rows"] = bool(full_sheet and selected_row_end - selected_row_start + 1 > max_rows)
            result["truncated_columns"] = bool(full_sheet and selected_col_end - selected_col_start + 1 > max_columns)
            return result
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
