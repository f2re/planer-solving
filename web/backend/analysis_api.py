"""Streaming schedule upload and automatic layout-template matching API."""
from __future__ import annotations

import logging
from pathlib import Path
import time
from typing import Any, Dict, List
import uuid

from fastapi import APIRouter, FastAPI, Request, UploadFile
from pydantic import BaseModel

from src.schedule_analyzer import ScheduleAnalyzer
from src.template_learning import (
    best_template_layout,
    fingerprint_from_analysis,
    fingerprint_similarity,
    layout_candidates,
)
from src.template_matcher import evaluate_layout, rank_candidates
from web.backend.app_context import ApplicationContext
from web.backend.errors import ApplicationError
from web.backend.schemas import AnalysisFile, AnalyzeResponse

logger = logging.getLogger(__name__)
UPLOAD_CHUNK_SIZE = 1024 * 1024


class TemplateMatchRequest(BaseModel):
    workspace_id: str


async def request_uploads(request: Request, field_name: str = "files") -> List[UploadFile]:
    """Parse multipart data without an application file-count ceiling."""

    form = await request.form(max_files=float("inf"), max_fields=float("inf"))
    files = [
        item for item in form.getlist(field_name)
        if hasattr(item, "read") and hasattr(item, "filename")
    ]
    if not files:
        raise ApplicationError("Не выбраны файлы расписаний.")
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


async def analyze_files(context: ApplicationContext, files: List[UploadFile]) -> AnalyzeResponse:
    """Analyze any number of workbooks while keeping their payloads off RAM."""

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
            analysis["fingerprint"] = fingerprint_from_analysis(analysis)
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
    repository = context.workspace_repository

    @router.post("/api/analyze", response_model=AnalyzeResponse)
    async def analyze_schedules(request: Request) -> AnalyzeResponse:
        return await analyze_files(context, await request_uploads(request))

    @router.post("/api/analysis/{session_id}/files/{file_id}/match-templates")
    def match_templates(
        session_id: str,
        file_id: str,
        request: TemplateMatchRequest,
    ) -> Dict[str, Any]:
        manifest = context.sessions.load_manifest(session_id)
        item = context.sessions.manifest_file(manifest, file_id)
        analysis = item.get("analysis")
        if not isinstance(analysis, dict):
            raise ApplicationError("Для файла нет результатов автоматического анализа.")

        workspace = repository.get_workspace(request.workspace_id)
        teachers_path = context.sessions.write_snapshot(
            session_id,
            f"teachers-match-{workspace['id']}.json",
            workspace.get("teachers", []),
        )
        workbook_path = context.sessions.stored_path(session_id, item)
        common = {
            "file_path": workbook_path,
            "teachers_path": teachers_path,
            "group_name": item.get("group_name") or Path(item["filename"]).stem,
            "available_sheets": analysis.get("sheet_names", []),
            "fallback_sheet": analysis.get("selected_sheet", ""),
        }
        workbook_fingerprint = analysis.get("fingerprint") or fingerprint_from_analysis(analysis)

        automatic = evaluate_layout(
            **common,
            layout=analysis["layout"],
            source="automatic",
            name="Автоматическая разметка",
        )
        automatic.update({
            "rule_id": "automatic",
            "rule_name": "Автоматическая разметка",
            "revision_no": None,
            "fingerprint_similarity": 1.0,
        })
        candidates = [automatic]

        for template in workspace.get("templates", []):
            similarity = fingerprint_similarity(template.get("fingerprint"), workbook_fingerprint)
            evaluated_rules = []
            for rule in layout_candidates(template, analysis.get("sheet_names", [])):
                candidate = evaluate_layout(
                    **common,
                    layout=rule["layout"],
                    source="template",
                    name=template.get("name") or "Шаблон без названия",
                    template_id=template.get("id"),
                )
                candidate.update({
                    "rule_id": rule["rule_id"],
                    "rule_name": rule["rule_name"],
                    "revision_no": template.get("current_revision"),
                })
                evaluated_rules.append(candidate)
            if evaluated_rules:
                candidates.append(best_template_layout(evaluated_rules, similarity))

        ranked = rank_candidates(candidates)
        selected = ranked[0]
        selected["improvement_over_automatic"] = round(
            float(selected["score"]) - float(automatic["score"]), 3
        )
        if selected.get("template_id"):
            metrics = selected.get("metrics") or {}
            status = (
                "error" if metrics.get("error_count")
                else "warning" if metrics.get("warning_count")
                else "success"
            )
            repository.record_template_evaluation(
                workspace["id"],
                selected["template_id"],
                status=status,
                quality=float(selected.get("quality_percent") or 0),
                lesson_count=int(metrics.get("unique_lessons") or 0),
            )

        item["template_match"] = {
            "workspace_id": workspace["id"],
            "evaluated_at": time.time(),
            "fingerprint": workbook_fingerprint,
            "selected": {
                key: selected.get(key)
                for key in (
                    "candidate_key", "source", "name", "template_id", "revision_no",
                    "rule_id", "rule_name", "score", "quality_percent", "metrics",
                    "reasons", "improvement_over_automatic", "fingerprint_similarity",
                )
            },
        }
        context.sessions.save_manifest(session_id, manifest)
        return {
            "file_id": file_id,
            "workspace_id": workspace["id"],
            "fingerprint": workbook_fingerprint,
            "selected": selected,
            "automatic": automatic,
            "candidates": ranked,
            "evaluated_count": len(ranked),
        }

    return router


def install_analysis_api(app: FastAPI, context: ApplicationContext) -> FastAPI:
    app.include_router(build_analysis_router(context))
    return app
