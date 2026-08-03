"""Interactive import preview, field mapping, review and transactional commit."""
from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Any, Dict, List
import uuid

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from src.import_commit import commit_template_import
from src.import_wizard import (
    TEACHER_FIELD_LABELS,
    evaluate_teacher_rows,
    evaluate_template_rows,
    parse_teacher_source,
    parse_template_source,
    parse_workspace_source,
)
from src.operations_domain import AuthenticatedUser, PermissionDenied
from src.revision_bootstrap import ensure_template_revisions
from web.backend.analysis_api import stream_upload
from web.backend.app_context import ApplicationContext
from web.backend.auth import operator_dependency


class ImportEvaluateRequest(BaseModel):
    mapping: Dict[str, str] = Field(default_factory=dict)
    mode: str = "append"


class ImportDecision(BaseModel):
    row_index: int
    action: str


class ImportCommitRequest(BaseModel):
    mode: str = "append"
    decisions: List[ImportDecision] = Field(default_factory=list)


def _can_import_kind(user: AuthenticatedUser, kind: str) -> None:
    if kind in {"teachers", "workspace"} and user.role != "admin":
        raise PermissionDenied("Импорт преподавателей и пространств доступен администратору.")


def _public_job(job: Dict[str, Any], row_limit: int = 200) -> Dict[str, Any]:
    source = dict(job.get("source") or {})
    rows = list(source.get("rows") or [])
    source["rows"] = rows[:row_limit]
    source["total_rows"] = len(rows)
    source["truncated"] = len(rows) > row_limit
    evaluation = dict(job.get("evaluation") or {})
    evaluation_rows = list(evaluation.get("rows") or [])
    evaluation["rows"] = evaluation_rows[:row_limit]
    evaluation["truncated"] = len(evaluation_rows) > row_limit
    return {
        "id": job["id"],
        "workspace_id": job.get("workspace_id"),
        "kind": job["kind"],
        "filename": job["filename"],
        "metadata": job.get("metadata") or {},
        "mapping": job.get("mapping") or {},
        "source": source,
        "evaluation": evaluation,
        "status": job["status"],
        "created_at": job["created_at"],
        "expires_at": job["expires_at"],
        "field_labels": TEACHER_FIELD_LABELS if job["kind"] == "teachers" else {},
    }


def _review_evaluation(context: ApplicationContext, job: Dict[str, Any]) -> Dict[str, Any]:
    """Return detailed reviewed rows even after commit stored final statistics."""

    evaluation = dict(job.get("evaluation") or {})
    rows = list(evaluation.get("rows") or [])
    if rows and any(isinstance(item, dict) and item.get("record") for item in rows):
        return evaluation

    source = job.get("source") or {}
    source_rows = source.get("rows") or []
    if job["kind"] == "teachers":
        return evaluate_teacher_rows(
            source_rows,
            job.get("mapping") or source.get("suggested_mapping") or {},
            context.workspace_repository.list_teachers(job["workspace_id"]),
        )
    if job["kind"] == "templates":
        return evaluate_template_rows(
            source_rows,
            context.workspace_repository.list_templates(job["workspace_id"]),
        )
    if source_rows:
        return {
            "kind": "workspace",
            "summary": {"add": 1, "update": 0, "conflict": 0, "skip": 0, "error": 0},
            "rows": [{
                "row_index": 0,
                "record": source_rows[0],
                "suggested_action": "add",
                "message": "Создано новое пространство.",
            }],
            "total_rows": 1,
        }
    return {"rows": [], "summary": {}, "total_rows": 0}


def build_import_router(context: ApplicationContext) -> APIRouter:
    router = APIRouter(tags=["imports"])
    operator = operator_dependency(context)

    @router.post("/api/workspaces/{workspace_id}/imports/preview")
    async def preview_import(
        workspace_id: str,
        file: UploadFile = File(...),
        kind: str = Query("teachers", pattern="^(teachers|templates|workspace)$"),
        user: AuthenticatedUser = Depends(operator),
    ) -> Dict[str, Any]:
        _can_import_kind(user, kind)
        context.workspace_repository.get_workspace(workspace_id)
        original_name = file.filename or "import.dat"
        upload_id = str(uuid.uuid4())
        suffix = Path(original_name).suffix.lower()
        target = context.paths.import_root / f"{upload_id}{suffix}"
        await stream_upload(file, target)
        payload = target.read_bytes()
        if kind == "teachers":
            parsed = parse_teacher_source(payload, original_name)
            evaluation = evaluate_teacher_rows(
                parsed["rows"],
                parsed["suggested_mapping"],
                context.workspace_repository.list_teachers(workspace_id),
            )
        elif kind == "templates":
            parsed = parse_template_source(payload, original_name)
            evaluation = evaluate_template_rows(
                parsed["rows"],
                context.workspace_repository.list_templates(workspace_id),
            )
        else:
            parsed = parse_workspace_source(payload, original_name)
            evaluation = {
                "kind": "workspace",
                "summary": {"add": 1, "update": 0, "conflict": 0, "skip": 0, "error": 0},
                "rows": [{
                    "row_index": 0,
                    "record": parsed["rows"][0],
                    "suggested_action": "add",
                    "message": "Будет создано новое пространство.",
                }],
                "total_rows": 1,
            }
        metadata = {
            key: value for key, value in parsed.items()
            if key not in {"rows", "suggested_mapping"}
        }
        job = context.operations.create_import_job(
            workspace_id=workspace_id,
            user_id=user.id,
            kind=kind,
            filename=original_name,
            source_path=str(target),
            source={
                "columns": parsed.get("columns", []),
                "rows": parsed.get("rows", []),
                "suggested_mapping": parsed.get("suggested_mapping", {}),
            },
            metadata=metadata,
        )
        job = context.operations.update_import_evaluation(
            job["id"],
            mapping=parsed.get("suggested_mapping", {}),
            evaluation=evaluation,
            user_id=user.id,
        )
        return _public_job(job)

    @router.post("/api/imports/{job_id}/evaluate")
    def evaluate_import(
        job_id: str,
        payload: ImportEvaluateRequest,
        user: AuthenticatedUser = Depends(operator),
    ) -> Dict[str, Any]:
        job = context.operations.get_import_job(job_id)
        if job["user_id"] != user.id and user.role != "admin":
            raise PermissionDenied("Этот предварительный импорт создан другим пользователем.")
        _can_import_kind(user, job["kind"])
        source = job.get("source") or {}
        if job["kind"] == "teachers":
            evaluation = evaluate_teacher_rows(
                source.get("rows") or [],
                payload.mapping,
                context.workspace_repository.list_teachers(job["workspace_id"]),
            )
        elif job["kind"] == "templates":
            evaluation = evaluate_template_rows(
                source.get("rows") or [],
                context.workspace_repository.list_templates(job["workspace_id"]),
            )
        else:
            evaluation = job.get("evaluation") or {}
        updated = context.operations.update_import_evaluation(
            job_id,
            mapping=payload.mapping,
            evaluation=evaluation,
            user_id=job["user_id"],
        )
        return _public_job(updated)

    @router.post("/api/imports/{job_id}/commit")
    def commit_import(
        job_id: str,
        payload: ImportCommitRequest,
        user: AuthenticatedUser = Depends(operator),
    ) -> Dict[str, Any]:
        job = context.operations.get_import_job(job_id)
        if job["user_id"] != user.id and user.role != "admin":
            raise PermissionDenied("Этот предварительный импорт создан другим пользователем.")
        _can_import_kind(user, job["kind"])
        if job["status"] == "committed":
            return job.get("evaluation") or {"status": "already_committed"}
        evaluation = job.get("evaluation") or {}
        rows = evaluation.get("rows") or []
        decisions = {item.row_index: item.action for item in payload.decisions}
        if job["kind"] == "teachers":
            result = context.operations.commit_teacher_import(
                job_id=job_id,
                workspace_id=job["workspace_id"],
                rows=rows,
                decisions=decisions,
                mode=payload.mode,
                user_id=user.id,
            )
        elif job["kind"] == "templates":
            result = commit_template_import(
                context.operations,
                job_id=job_id,
                workspace_id=job["workspace_id"],
                rows=rows,
                decisions=decisions,
                mode=payload.mode,
                user_id=user.id,
            )
        else:
            source_rows = (job.get("source") or {}).get("rows") or []
            created = context.workspace_repository.import_workspace(source_rows[0])
            ensure_template_revisions(context.operations)
            result = {
                "added": 1,
                "updated": 0,
                "skipped": 0,
                "errors": 0,
                "workspace": created,
            }
            context.operations.mark_import_committed(
                job_id,
                user_id=user.id,
                workspace_id=created["id"],
                result=result,
            )
        return result

    @router.get("/api/imports/{job_id}/report.csv")
    def import_report(
        job_id: str,
        user: AuthenticatedUser = Depends(operator),
    ) -> Response:
        job = context.operations.get_import_job(job_id)
        if job["user_id"] != user.id and user.role != "admin":
            raise PermissionDenied("Этот предварительный импорт создан другим пользователем.")
        evaluation = _review_evaluation(context, job)
        rows = evaluation.get("rows") or []
        buffer = io.StringIO()
        writer = csv.writer(buffer, delimiter=";")
        writer.writerow([
            "Строка",
            "Действие",
            "Сообщение",
            "Краткое имя",
            "Полное ФИО",
            "Название",
        ])
        for item in rows:
            record = item.get("record") or {}
            writer.writerow([
                int(item.get("row_index", 0)) + 1,
                item.get("suggested_action", item.get("action", "")),
                item.get("message", ""),
                record.get("short_name", ""),
                record.get("full_name", ""),
                record.get("name", ""),
            ])
        return Response(
            "\ufeff" + buffer.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="import-{job_id}.csv"'},
        )

    return router
