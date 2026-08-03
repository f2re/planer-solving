"""Append, replace, remove and restore individual workbooks in an active analysis session."""
from __future__ import annotations

import logging
import os
from pathlib import Path
import shutil
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
    storage_stem: str | None = None,
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

    stored_name = f"{storage_stem or resolved_file_id}{extension}"
    stored_path = session_dir / stored_name
    item["stored_name"] = stored_name
    try:
        item["bytes_written"] = await stream_upload(upload, stored_path)
    except Exception:
        logger.exception("Cannot store workbook %s in session %s", original_name, session_id)
        stored_path.unlink(missing_ok=True)
        item["stored_name"] = ""
        item["message"] = (
            "Не удалось сохранить файл. Проверьте свободное место и права каталога; "
            "другие файлы сеанса не затронуты."
        )
        return item

    if not item["bytes_written"]:
        stored_path.unlink(missing_ok=True)
        item["stored_name"] = ""
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


def _backup_file(source: Path, destination: Path) -> None:
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)


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
        try:
            context.sessions.save_manifest(session_id, manifest)
        except Exception as exc:
            logger.exception("Cannot append files to session %s", session_id)
            for item in items:
                _remove_stored_file(context, session_id, item)
            raise ApplicationError(
                "Новые файлы проверены, но сеанс не удалось сохранить. "
                "Они не добавлены, прежний состав сеанса не изменён.",
                status_code=500,
                code="append_commit_failed",
            ) from exc
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
        staging_stem = f".replacement-{file_id}-{uuid.uuid4()}"
        replacement = await _analyze_upload(
            context,
            session_id,
            upload,
            file_id=file_id,
            group_name=str(existing.get("group_name") or ""),
            storage_stem=staging_stem,
        )
        staging_name = str(replacement.get("stored_name") or "")
        session_dir = context.sessions.path(session_id)
        staging_path = (session_dir / staging_name).resolve() if staging_name else None

        if not replacement.get("analysis") or not staging_path or not staging_path.is_file():
            if staging_path and staging_path.parent == session_dir:
                staging_path.unlink(missing_ok=True)
            raise ApplicationError(
                "Новый файл не принят: он пуст, повреждён или имеет неподдерживаемый формат. "
                "Прежний исходник и все правки сохранены.",
                status_code=422,
                code="replacement_rejected",
            )

        extension = Path(replacement["filename"]).suffix.lower()
        target_name = f"{file_id}{extension}"
        target_path = (session_dir / target_name).resolve()
        old_stored_name = str(existing.get("stored_name") or "")
        old_path = (session_dir / old_stored_name).resolve() if old_stored_name else None
        backup_path = session_dir / f".replacement-backup-{file_id}-{uuid.uuid4()}{old_path.suffix if old_path else ''}"
        backup_created = False

        try:
            if old_path and old_path.parent == session_dir and old_path.is_file():
                _backup_file(old_path, backup_path)
                backup_created = True

            os.replace(staging_path, target_path)
            replacement["stored_name"] = target_name
            files = manifest.get("files", [])
            for index, item in enumerate(files):
                if isinstance(item, dict) and item.get("file_id") == file_id:
                    files[index] = replacement
                    break
            manifest["updated_at"] = time.time()
            context.sessions.save_manifest(session_id, manifest)
        except Exception as exc:
            logger.exception("Cannot atomically replace workbook %s in session %s", file_id, session_id)
            if backup_created and backup_path.is_file() and old_path:
                os.replace(backup_path, old_path)
            if target_path != old_path:
                target_path.unlink(missing_ok=True)
            staging_path.unlink(missing_ok=True)
            raise ApplicationError(
                "Новый файл проверен, но переключение не завершено. Прежний исходник восстановлен.",
                status_code=500,
                code="replacement_commit_failed",
            ) from exc
        else:
            if old_path and old_path != target_path:
                old_path.unlink(missing_ok=True)
            backup_path.unlink(missing_ok=True)
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
        source = (session_dir / stored_name).resolve() if stored_name else None
        trash_name = f"{file_id}-{Path(stored_name).name}" if stored_name else ""
        trash_path = (trash_dir / trash_name).resolve() if trash_name else None
        moved = False
        try:
            if source and source.parent == session_dir and source.is_file() and trash_path:
                os.replace(source, trash_path)
                moved = True

            manifest["files"] = [
                candidate for candidate in files
                if not (isinstance(candidate, dict) and candidate.get("file_id") == file_id)
            ]
            removed = dict(item)
            removed["trash_name"] = trash_name if moved else ""
            removed["removed_at"] = time.time()
            manifest.setdefault("removed_files", []).append(removed)
            manifest["updated_at"] = time.time()
            context.sessions.save_manifest(session_id, manifest)
        except Exception as exc:
            logger.exception("Cannot remove file %s from session %s", file_id, session_id)
            if moved and trash_path and trash_path.is_file() and source:
                os.replace(trash_path, source)
            raise ApplicationError(
                "Файл не убран: сеанс не удалось сохранить. Исходник и прежнее состояние восстановлены.",
                status_code=500,
                code="remove_commit_failed",
            ) from exc

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
                item for item in reversed(removed_files)
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
        session_dir = context.sessions.path(session_id)
        trash_path = (
            (session_dir / ".trash" / Path(trash_name).name).resolve()
            if trash_name
            else None
        )
        target_path = (
            (session_dir / Path(stored_name).name).resolve()
            if stored_name
            else None
        )
        moved = False
        try:
            if trash_path and target_path and trash_path.is_file():
                os.replace(trash_path, target_path)
                moved = True
            elif target_path and not target_path.is_file():
                restored["stored_name"] = ""
                restored["analysis"] = None
                restored["status"] = "error"
                restored["message"] = "Исходный файл уже недоступен. Замените только эту запись."

            manifest.setdefault("files", []).append(restored)
            removed_once = False
            retained: List[Dict[str, Any]] = []
            for item in reversed(removed_files):
                if not removed_once and item is removed:
                    removed_once = True
                    continue
                retained.append(item)
            manifest["removed_files"] = list(reversed(retained))
            manifest["updated_at"] = time.time()
            context.sessions.save_manifest(session_id, manifest)
        except Exception as exc:
            logger.exception("Cannot restore file %s in session %s", file_id, session_id)
            if moved and target_path and target_path.is_file() and trash_path:
                os.replace(target_path, trash_path)
            raise ApplicationError(
                "Файл не восстановлен: сеанс не удалось сохранить. Он остаётся в корзине и доступен для повторной попытки.",
                status_code=500,
                code="restore_commit_failed",
            ) from exc
        return _response_file(restored)

    return router
