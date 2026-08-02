"""Streaming schedule upload and automatic layout-template matching API."""
from __future__ import annotations

import logging
from pathlib import Path
import time
import uuid
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Request, UploadFile
from pydantic import BaseModel

from src.schedule_analyzer import ScheduleAnalyzer
from src.template_matcher import evaluate_layout, rank_candidates
from src.workspace_store import WorkspaceError, WorkspaceNotFound, WorkspaceStore
from web.backend.schemas import AnalysisFile, AnalyzeResponse

logger = logging.getLogger(__name__)
UPLOAD_CHUNK_SIZE = 1024 * 1024


class TemplateMatchRequest(BaseModel):
    workspace_id: str


async def request_uploads(request: Request, field_name: str = "files") -> List[UploadFile]:
    """Parse multipart data without Starlette's default file-count ceiling."""

    unlimited = float("inf")
    form = await request.form(max_files=unlimited, max_fields=unlimited)
    files = [item for item in form.getlist(field_name) if hasattr(item, "read") and hasattr(item, "filename")]
    if not files:
        raise HTTPException(status_code=400, detail="Не выбраны файлы расписаний.")
    return files


async def stream_upload(upload: UploadFile, target: Path) -> int:
    """Write an uploaded file incrementally without an application size limit."""

    written = 0
    try:
        with target.open("wb") as output:
            while True:
                chunk = await upload.read(UPLOAD_CHUNK_SIZE)
                if not chunk:
                    break
                output.write(chunk)
                written += len(chunk)
    finally:
        await upload.close()
    return written


def _response_file(item: Dict[str, Any]) -> AnalysisFile:
    keys = ("file_id", "filename", "group_name", "status", "message", "analysis")
    return AnalysisFile(**{key: item[key] for key in keys})


async def analyze_files(context: Any, files: List[UploadFile]) -> AnalyzeResponse:
    """Analyze any number of workbooks while keeping their payloads off RAM."""

    context._cleanup_old_sessions()
    session_id = str(uuid.uuid4())
    session_dir = context.SESSION_ROOT / session_id
    session_dir.mkdir(parents=True, exist_ok=False)
    analyzer = ScheduleAnalyzer()
    response_files: List[AnalysisFile] = []
    manifest_files: List[Dict[str, Any]] = []

    for upload in files:
        original_name = Path(upload.filename or "schedule.xlsx").name
        extension = Path(original_name).suffix.lower()
        file_id = str(uuid.uuid4())
        item: Dict[str, Any] = {
            "file_id": file_id,
            "filename": original_name,
            "group_name": Path(original_name).stem,
            "stored_name": "",
            "status": "error",
            "message": "",
            "analysis": None,
            "bytes_written": 0,
        }

        if extension not in {".xlsx", ".xlsm"}:
            await upload.close()
            item["message"] = (
                "Поддерживаются .xlsx и .xlsm. Старый формат .xls необходимо "
                "один раз сохранить как .xlsx."
            )
            manifest_files.append(item)
            response_files.append(_response_file(item))
            continue

        stored_name = f"{file_id}{extension}"
        stored_path = session_dir / stored_name
        item["stored_name"] = stored_name
        try:
            item["bytes_written"] = await stream_upload(upload, stored_path)
        except Exception:
            logger.exception("Cannot store uploaded workbook %s", original_name)
            stored_path.unlink(missing_ok=True)
            item["message"] = "Не удалось сохранить файл на сервере. Проверьте свободное место и права каталога."
            manifest_files.append(item)
            response_files.append(_response_file(item))
            continue

        if not item["bytes_written"]:
            stored_path.unlink(missing_ok=True)
            item["message"] = "Файл пуст."
            manifest_files.append(item)
            response_files.append(_response_file(item))
            continue

        try:
            analysis = analyzer.analyze(str(stored_path)).to_dict()
            item["analysis"] = analysis
            item["status"] = "success" if analysis["confidence"] >= 0.55 else "warning"
            item["message"] = (
                "Структура определена автоматически."
                if item["status"] == "success"
                else "Структура определена с низкой уверенностью; требуется ручная проверка."
            )
        except Exception:
            logger.exception("Cannot analyze workbook %s", original_name)
            item["status"] = "error"
            item["message"] = "Книгу не удалось разобрать. Проверьте, что файл не повреждён и содержит таблицу Excel."

        manifest_files.append(item)
        response_files.append(_response_file(item))

    manifest = {
        "session_id": session_id,
        "created_at": time.time(),
        "files": manifest_files,
    }
    context._atomic_json_write(session_dir / "manifest.json", manifest)
    return AnalyzeResponse(session_id=session_id, files=response_files)


def _install_router_before_static(app: Any, router: APIRouter) -> None:
    static_routes, kept = [], []
    for route in app.router.routes:
        if route.__class__.__name__ == "Mount":
            static_routes.append(route)
            continue
        methods = getattr(route, "methods", set())
        if getattr(route, "path", None) == "/api/analyze" and "POST" in methods:
            continue
        kept.append(route)
    app.router.routes[:] = kept
    app.include_router(router)
    app.router.routes.extend(static_routes)


def install_analysis_api(app: Any, context: Any) -> Any:
    """Replace the legacy buffered upload route and add template matching."""

    router = APIRouter()

    @router.post("/api/analyze", response_model=AnalyzeResponse)
    async def analyze_schedules(request: Request) -> AnalyzeResponse:
        return await analyze_files(context, await request_uploads(request))

    @router.post("/api/analysis/{session_id}/files/{file_id}/match-templates")
    def match_templates(
        session_id: str,
        file_id: str,
        request: TemplateMatchRequest,
    ) -> Dict[str, Any]:
        manifest = context._load_manifest(session_id)
        item = context._manifest_file(manifest, file_id)
        analysis = item.get("analysis")
        if not analysis:
            raise HTTPException(status_code=400, detail="Для файла нет результатов автоматического анализа.")

        store = WorkspaceStore(
            context.BASE_DIR / "data" / "workspaces.json",
            context.TEACHERS_JSON,
        )
        try:
            workspace = store.get_workspace(request.workspace_id)
        except WorkspaceNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except WorkspaceError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        session_dir = context._safe_session_dir(session_id)
        teachers_path = session_dir / f"teachers-match-{workspace['id']}.json"
        context._atomic_json_write(teachers_path, workspace.get("teachers", []))
        workbook_path = context._stored_path(session_id, item)
        common = {
            "file_path": workbook_path,
            "teachers_path": teachers_path,
            "group_name": item.get("group_name") or Path(item["filename"]).stem,
            "available_sheets": analysis.get("sheet_names", []),
            "fallback_sheet": analysis.get("selected_sheet", ""),
        }

        candidates = [
            evaluate_layout(
                **common,
                layout=analysis["layout"],
                source="automatic",
                name="Автоматическая разметка",
            )
        ]
        for template in workspace.get("templates", []):
            candidates.append(
                evaluate_layout(
                    **common,
                    layout=template.get("layout", {}),
                    source="template",
                    name=template.get("name") or "Шаблон без названия",
                    template_id=template.get("id"),
                )
            )

        ranked = rank_candidates(candidates)
        selected = ranked[0]
        automatic = next(candidate for candidate in ranked if candidate["source"] == "automatic")
        selected["improvement_over_automatic"] = round(
            float(selected["score"]) - float(automatic["score"]), 3
        )

        item["template_match"] = {
            "workspace_id": workspace["id"],
            "evaluated_at": time.time(),
            "selected": {
                key: selected[key]
                for key in (
                    "candidate_key", "source", "name", "template_id", "score",
                    "quality_percent", "metrics", "reasons", "improvement_over_automatic",
                )
            },
        }
        context._atomic_json_write(session_dir / "manifest.json", manifest)
        return {
            "file_id": file_id,
            "workspace_id": workspace["id"],
            "selected": selected,
            "automatic": automatic,
            "candidates": ranked,
            "evaluated_count": len(ranked),
        }

    _install_router_before_static(app, router)
    return app
