"""Append, replace, remove and restore individual workbooks in an active analysis session."""
from __future__ import annotations

import logging
import os
from pathlib import Path
import time
from typing import Any, Dict, List
import uuid

from fastapi import APIRouter, Request, UploadFile

from src.schedule_analyzer import ScheduleAnalyzer
from src.template_learning import fingerprint_from_analysis
from web.backend.analysis_api import request_uploads, stream_upload
from web.backend.app_context import ApplicationContext
from web.backend.errors import ApplicationError
from web.backend.schemas import AnalysisFile, AnalyzeResponse

logger = logging.getLogger(__name__)
SUPPORTED_EXTENSIONS = {".xlsx", ".xlsm"}


def _response_file(item: Dict[str, Any]) -> AnalysisFile:
    keys = ("file_id", "filename", "group_name", "status", "message", "analysis")
    return AnalysisFile(**{key: item.get(key) for key in keys})


async def _single_upload(request: Request, field_name: str = "file") -> UploadFile:
    form = await request.form(max_files=1, max_fields=float("inf"))
    item = form.get(field_name)
    if not item or not hasattr(item, "read") or not hasattr(item, "filename"):
        raise ApplicationError("Выберите файл для замены.")
    return item


async def _analyze_upload(
    context: ApplicationContext,
    session_id: str,
    upload: UploadFile,
    *,
    file_id: str | None = None,
    group_name: str | None = None,
) -> Dict[str, Any]:
    """Store and analyze one upload without creating a new session."""

    session_dir = context.sessions.path(session_id)
    original_name = Path(upload.filename or "schedule.xlsx").name
    extension = Path(original_name).suffix.lower()
    resolved_file_id = file_id or str(uuid.uuid4())
    item: Dict[str, Any] = {
        "file_id": resolved_file_id,
        "filename": original_name,
        "group_name": group_name or Path(original_name).stem,
        "stored_name": "",
        "status": "error",
        "message": "",
        "analysis": None,
        "bytes_written": 0,
    }

    if extension not in SUPPORTED_EXTENSIONS:
        await upload.close()
        item["message"] = (
            "Поддерживаются .xlsx и .xlsm. Этот файл сохранён в списке как требующий замены; "
            "остальные файлы можно продолжить обрабатывать."
        )
        return item

    stored_name = f"{resolved_file_id}{extension}"
    stored_path = session_dir / stored_name
    item["stored_name"] = stored_name
    try:
        item["bytes_written"] = await stream_upload(upload, stored_path)
    except Exception:
        logger.exception("Cannot store workbook %s in session %s", original_name, session_id)
        stored_path.unlink(missing_ok=True)
        item["message"] = (
            "Не удалось сохранить файл. Проверьте свободное место и права каталога; "
            "другие файлы сеанса не затронуты."
        )
        return item

    if not item["bytes_written"]:
        stored_path.unlink(missing_ok=True)
        item["message"] = "Файл пуст. Замените только этот файл или исключите его из сеанса."
        return item

    try:
        analysis = ScheduleAnalyzer().analyze(str(stored_path)).to_dict()
        analysis["fingerprint"] = fingerprint_from_analysis(analysis)
        item["analysis"] = analysis
        item["status"] = "success" if analysis["confidence"] >= 0.55 else "warning"
        item["message"] = (
            "Структура определена автоматически."
            if item["status"] == "success"
            else "Структура определена с низкой уверенностью; файл доступен для правки на месте."
        )
    except Exception:
        logger.exception("Cannot analyze workbook %s in session %s", original_name, session_id)
        item["status"] = "error"
        item["message"] = (
            "Книгу не удалось разобрать. Замените только этот файл, исключите его или "
            "оставьте в диагностическом результате."
        )
    return item


def _remove_stored_file(context: ApplicationContext, session_id: str, item: Dict[str, Any]) -> None:
    stored_name = str(item.get("stored_name") or "")
    if not stored_name:
        return
    session_dir = context.sessions.path(session_id)
    path = (session_dir / stored_name).resolve()
    if path.parent == session_dir:
        path.unlink(missing_ok=True)


def build_session_file_router(context: ApplicationContext) -> APIRouter:
    router = APIRouter(tags=["analysis-session-files"])

    @router.post("/api/analysis/{session_id}/files", response_model=AnalyzeResponse)
    async def append_files(session_id: str, request: Request) -> AnalyzeResponse:
        manifest = context.sessions.load_manifest(session_id)
        uploads = await request_uploads(request)
        items: List[Dict[str, Any]] = []
        for upload in uploads:
            items.append(await _analyze_upload(context, session_id, upload))
        manifest.setdefault("files", []).extend(items)
        manifest["updated_at"] = time.time()
        context.sessions.save_manifest(session_id, manifest)
        return AnalyzeResponse(
            session_id=session_id,
            files=[_response_file(item) for item in items],
        )

    @router.put(
        "/api/analysis/{session_id}/files/{file_id}",
        response_model=AnalysisFile,
    )
    async def replace_file(
        session_id: str,
        file_id: str,
        request: Request,
    ) -> AnalysisFile:
        manifest = context.sessions.load_manifest(session_id)
        existing = context.sessions.manifest_file(manifest, file_id)
        upload = await _single_upload(request)
        replacement = await _analyze_upload(
            context,
            session_id,
            upload,
            file_id=file_id,
            group_name=str(existing.get("group_name") or ""),
        )
        old_stored_name = str(existing.get("stored_name") or "")
        new_stored_name = str(replacement.get("stored_name") or "")
        if old_stored_name and old_stored_name != new_stored_name:
            _remove_stored_file(context, session_id, existing)

        files = manifest.get("files", [])
        for index, item in enumerate(files):
            if isinstance(item, dict) and item.get("file_id") == file_id:
                files[index] = replacement
                break
        manifest["updated_at"] = time.time()
        context.sessions.save_manifest(session_id, manifest)
        return _response_file(replacement)

    @router.delete("/api/analysis/{session_id}/files/{file_id}")
    def remove_file(session_id: str, file_id: str) -> Dict[str, Any]:
        manifest = context.sessions.load_manifest(session_id)
        files = manifest.get("files", [])
        item = context.sessions.manifest_file(manifest, file_id)
        session_dir = context.sessions.path(session_id)
        trash_dir = session_dir / ".trash"
        trash_dir.mkdir(parents=True, exist_ok=True)

        stored_name = str(item.get("stored_name") or "")
        trash_name = ""
        if stored_name:
            source = (session_dir / stored_name).resolve()
            if source.parent == session_dir and source.is_file():
                trash_name = f"{file_id}-{Path(stored_name).name}"
                os.replace(source, trash_dir / trash_name)

        manifest["files"] = [
            candidate for candidate in files
            if not (isinstance(candidate, dict) and candidate.get("file_id") == file_id)
        ]
        removed = dict(item)
        removed["trash_name"] = trash_name
        removed["removed_at"] = time.time()
        manifest.setdefault("removed_files", []).append(removed)
        manifest["updated_at"] = time.time()
        context.sessions.save_manifest(session_id, manifest)
        next_file_id = next(
            (
                candidate.get("file_id")
                for candidate in manifest["files"]
                if isinstance(candidate, dict) and candidate.get("analysis")
            ),
            None,
        )
        return {
            "status": "removed",
            "file_id": file_id,
            "filename": item.get("filename"),
            "next_file_id": next_file_id,
            "can_restore": True,
        }

    @router.post(
        "/api/analysis/{session_id}/files/{file_id}/restore",
        response_model=AnalysisFile,
    )
    def restore_file(session_id: str, file_id: str) -> AnalysisFile:
        manifest = context.sessions.load_manifest(session_id)
        removed_files = manifest.setdefault("removed_files", [])
        removed = next(
            (
                item for item in removed_files
                if isinstance(item, dict) and item.get("file_id") == file_id
            ),
            None,
        )
        if not removed:
            raise ApplicationError("Удалённый файл уже восстановлен или не найден.", status_code=404)

        restored = dict(removed)
        trash_name = str(restored.pop("trash_name", "") or "")
        restored.pop("removed_at", None)
        stored_name = str(restored.get("stored_name") or "")
        if trash_name and stored_name:
            session_dir = context.sessions.path(session_id)
            source = (session_dir / ".trash" / Path(trash_name).name).resolve()
            target = (session_dir / Path(stored_name).name).resolve()
            if source.is_file():
                os.replace(source, target)
            elif not target.is_file():
                restored["stored_name"] = ""
                restored["analysis"] = None
                restored["status"] = "error"
                restored["message"] = "Исходный файл уже недоступен. Замените только эту запись."

        manifest.setdefault("files", []).append(restored)
        manifest["removed_files"] = [item for item in removed_files if item is not removed]
        manifest["updated_at"] = time.time()
        context.sessions.save_manifest(session_id, manifest)
        return _response_file(restored)

    return router
