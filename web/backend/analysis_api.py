"""Streaming schedule upload and automatic composite-template matching API."""
from __future__ import annotations

import logging
from pathlib import Path
import time
from typing import Any, Dict, List
import uuid

from fastapi import APIRouter, Depends, FastAPI, Request, UploadFile
from pydantic import BaseModel

from src.operations_domain import AuthenticatedUser
from src.schedule_analyzer import ScheduleAnalyzer
from src.template_matcher import evaluate_layout, rank_candidates
from src.workbook_fingerprint import build_workbook_fingerprint
from web.backend.app_context import ApplicationContext
from web.backend.auth import operator_dependency
from web.backend.errors import ApplicationError
from web.backend.schemas import AnalysisFile, AnalyzeResponse

logger = logging.getLogger(__name__)
UPLOAD_CHUNK_SIZE = 1024 * 1024


class TemplateMatchRequest(BaseModel):
    workspace_id: str


async def request_uploads(request: Request, field_name: str = "files") -> List[UploadFile]:
    form = await request.form(max_files=float("inf"), max_fields=float("inf"))
    files = [
        item for item in form.getlist(field_name)
        if hasattr(item, "read") and hasattr(item, "filename")
    ]
    if not files:
        raise ApplicationError("Не выбраны файлы расписаний.")
    return files


async def stream_upload(upload: UploadFile, target: Path) -> int:
    written = 0
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
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


async def analyze_files(context: ApplicationContext, files: List[UploadFile]) -> AnalyzeResponse:
    session_id, session_dir = context.sessions.create()
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
            item["message"] = (
                "Не удалось сохранить файл на сервере. "
                "Проверьте свободное место и права каталога."
            )
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
            analysis["fingerprint"] = build_workbook_fingerprint(stored_path)
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
            item["message"] = (
                "Книгу не удалось разобрать. Проверьте, что файл не повреждён "
                "и содержит таблицу Excel."
            )

        manifest_files.append(item)
        response_files.append(_response_file(item))

    manifest = {
        "session_id": session_id,
        "created_at": time.time(),
        "files": manifest_files,
    }
    context.sessions.save_manifest(session_id, manifest)
    return AnalyzeResponse(session_id=session_id, files=response_files)


def build_analysis_router(context: ApplicationContext) -> APIRouter:
    router = APIRouter(tags=["analysis"])
    operator = operator_dependency(context)

    @router.post("/api/analyze", response_model=AnalyzeResponse)
    async def analyze_schedules(
        request: Request,
        _: AuthenticatedUser = Depends(operator),
    ) -> AnalyzeResponse:
        return await analyze_files(context, await request_uploads(request))

    @router.post("/api/analysis/{session_id}/files/{file_id}/match-templates")
    def match_templates(
        session_id: str,
        file_id: str,
        request: TemplateMatchRequest,
        _: AuthenticatedUser = Depends(operator),
    ) -> Dict[str, Any]:
        manifest = context.sessions.load_manifest(session_id)
        item = context.sessions.manifest_file(manifest, file_id)
        analysis = item.get("analysis")
        if not isinstance(analysis, dict):
            raise ApplicationError("Для файла нет результатов автоматического анализа.")

        workspace = context.workspace_repository.get_workspace(request.workspace_id)
        teachers_path = context.sessions.write_snapshot(
            session_id,
            f"teachers-match-{workspace['id']}.json",
            workspace.get("teachers", []),
        )
        workbook_path = context.sessions.stored_path(session_id, item)
        fingerprint = analysis.get("fingerprint") or {}
        common = {
            "file_path": workbook_path,
            "teachers_path": teachers_path,
            "group_name": item.get("group_name") or Path(item["filename"]).stem,
            "available_sheets": analysis.get("sheet_names", []),
            "fallback_sheet": analysis.get("selected_sheet", ""),
            "workbook_fingerprint": fingerprint,
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
            candidate = evaluate_layout(
                **common,
                layout=template.get("layout", {}),
                source="template",
                name=template.get("name") or "Шаблон без названия",
                template_id=template.get("id"),
            )
            revisions = context.operations.list_template_revisions(
                workspace["id"], template["id"]
            )
            candidate["template_revision_id"] = revisions[0]["id"] if revisions else None
            learning = context.operations.template_learning_summary(
                template["id"], fingerprint.get("signature")
            )
            learning_bonus = min(35.0, learning["exact_successes"] * 12.0 + learning["success_rate"] * 14.0)
            learning_penalty = min(25.0, learning["failures"] * 1.5)
            candidate["learning"] = learning
            candidate["score"] = round(
                float(candidate["score"]) + learning_bonus - learning_penalty,
                3,
            )
            if learning_bonus:
                candidate["reasons"].append(
                    f"Подтверждённые успешные применения: {learning['successes']}"
                )
            candidates.append(candidate)

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
                key: selected.get(key)
                for key in (
                    "candidate_key", "source", "name", "template_id",
                    "template_revision_id", "component_id", "component_label",
                    "score", "quality_percent", "fingerprint_similarity",
                    "metrics", "reasons", "improvement_over_automatic",
                )
            },
            "candidates": [{
                key: candidate.get(key)
                for key in (
                    "candidate_key", "source", "name", "template_id",
                    "template_revision_id", "component_id", "component_label",
                    "score", "quality_percent", "fingerprint_similarity",
                    "metrics", "reasons", "layout", "usable", "learning",
                )
            } for candidate in ranked],
        }
        context.sessions.save_manifest(session_id, manifest)
        return {
            "file_id": file_id,
            "workspace_id": workspace["id"],
            "selected": selected,
            "automatic": automatic,
            "candidates": ranked,
            "evaluated_count": len(ranked),
        }

    return router


def install_analysis_api(app: FastAPI, context: ApplicationContext) -> FastAPI:
    app.include_router(build_analysis_router(context))
    return app
