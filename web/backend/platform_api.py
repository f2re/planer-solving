"""Interactive imports, revisions, run history, audit and learning APIs."""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

from fastapi import APIRouter, File, Query, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from src.import_wizard import (
    TEACHER_FIELDS,
    TEACHER_LABELS,
    classify_teachers,
    classify_templates,
    csv_report,
    parse_rows,
    suggest_teacher_mapping,
)
from src.template_learning import normalize_composite_rules
from web.backend.app_context import ApplicationContext
from web.backend.auth import actor_from_request, require_role
from web.backend.errors import ApplicationError


class ImportPreviewUpdate(BaseModel):
    mapping: Dict[str, str] = Field(default_factory=dict)


class ImportCommitRequest(BaseModel):
    decisions: Dict[str, str] = Field(default_factory=dict)


class TemplateProfileUpdate(BaseModel):
    layout: Optional[Dict[str, Any]] = None
    composite: List[Dict[str, Any]] = Field(default_factory=list)
    fingerprint: Dict[str, Any] = Field(default_factory=dict)
    comment: str = "Изменены составные правила"


class RestoreRevisionRequest(BaseModel):
    revision_no: int = Field(ge=1)


def _classify_job(context: ApplicationContext, workspace_id: str, kind: str, source: Mapping[str, Any], mapping: Mapping[str, str]) -> Dict[str, Any]:
    repository = context.workspace_repository
    rows = list(source.get("rows") or [])
    if kind == "teachers":
        return classify_teachers(rows, mapping, repository.list_teachers(workspace_id))
    if kind == "templates":
        return classify_templates(rows, repository.list_templates(workspace_id))
    raise ApplicationError("Неизвестный тип предварительного импорта.")


def build_platform_router(context: ApplicationContext) -> APIRouter:
    router = APIRouter(tags=["operations"])
    store = context.workspace_repository

    @router.get("/api/workspaces/{workspace_id}/imports")
    def list_imports(
        workspace_id: str,
        request: Request,
        limit: int = Query(50, ge=1, le=200),
    ) -> Dict[str, Any]:
        require_role(request, "viewer")
        return {"items": store.list_import_jobs(workspace_id, limit)}

    @router.post("/api/workspaces/{workspace_id}/imports/preview")
    async def preview_import(
        workspace_id: str,
        request: Request,
        kind: str = Query(..., pattern="^(teachers|templates)$"),
        file: UploadFile = File(...),
    ) -> Dict[str, Any]:
        actor = require_role(request, "operator")
        payload = await file.read()
        await file.close()
        if not payload:
            raise ApplicationError("Файл пуст.")
        try:
            source = parse_rows(payload, file.filename or "import.csv")
        except ValueError as exc:
            raise ApplicationError(str(exc)) from exc
        mapping = suggest_teacher_mapping(source["headers"]) if kind == "teachers" else {}
        preview = _classify_job(context, workspace_id, kind, source, mapping)
        job = store.create_import_job(
            workspace_id=workspace_id,
            actor=actor,
            kind=kind,
            filename=file.filename or "import.csv",
            source=source,
            mapping=mapping,
            preview=preview,
        )
        job["teacher_fields"] = [
            {"id": field, "name": TEACHER_LABELS[field]}
            for field in TEACHER_FIELDS
        ]
        return job

    @router.put("/api/workspaces/{workspace_id}/imports/{job_id}/preview")
    def recalculate_import(
        workspace_id: str,
        job_id: str,
        payload: ImportPreviewUpdate,
        request: Request,
    ) -> Dict[str, Any]:
        require_role(request, "operator")
        job = store.get_import_job(job_id)
        if job["workspace_id"] != workspace_id:
            raise ApplicationError("Импорт относится к другому пространству.", status_code=404)
        preview = _classify_job(context, workspace_id, job["kind"], job["source"], payload.mapping)
        updated = store.update_import_preview(job_id, mapping=payload.mapping, preview=preview)
        updated["teacher_fields"] = [
            {"id": field, "name": TEACHER_LABELS[field]}
            for field in TEACHER_FIELDS
        ]
        return updated

    @router.post("/api/workspaces/{workspace_id}/imports/{job_id}/commit")
    def commit_import(
        workspace_id: str,
        job_id: str,
        payload: ImportCommitRequest,
        request: Request,
    ) -> Dict[str, Any]:
        actor = require_role(request, "admin")
        job = store.get_import_job(job_id)
        if job["workspace_id"] != workspace_id:
            raise ApplicationError("Импорт относится к другому пространству.", status_code=404)
        return store.commit_import_job(job_id, actor=actor, decisions=payload.decisions)

    @router.get("/api/workspaces/{workspace_id}/imports/{job_id}/report.csv")
    def import_report(workspace_id: str, job_id: str, request: Request) -> Response:
        require_role(request, "viewer")
        job = store.get_import_job(job_id)
        if job["workspace_id"] != workspace_id:
            raise ApplicationError("Импорт относится к другому пространству.", status_code=404)
        return Response(
            csv_report(job["preview"].get("rows", [])),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="import-{job_id}.csv"'},
        )

    @router.get("/api/workspaces/{workspace_id}/templates/{template_id}/revisions")
    def template_revisions(workspace_id: str, template_id: str, request: Request) -> Dict[str, Any]:
        require_role(request, "viewer")
        return {"items": store.list_template_revisions(workspace_id, template_id)}

    @router.post("/api/workspaces/{workspace_id}/templates/{template_id}/restore")
    def restore_template(
        workspace_id: str,
        template_id: str,
        payload: RestoreRevisionRequest,
        request: Request,
    ) -> Dict[str, Any]:
        actor = require_role(request, "operator")
        template = store.restore_template_revision(
            workspace_id,
            template_id,
            payload.revision_no,
            actor_user_id=actor.get("id"),
        )
        store.audit(
            actor=actor,
            action="template.restore",
            entity_type="template",
            entity_id=template_id,
            workspace_id=workspace_id,
            summary=f"Восстановлена версия {payload.revision_no} шаблона «{template['name']}»",
        )
        return template

    @router.put("/api/workspaces/{workspace_id}/templates/{template_id}/profile")
    def update_template_profile(
        workspace_id: str,
        template_id: str,
        payload: TemplateProfileUpdate,
        request: Request,
    ) -> Dict[str, Any]:
        actor = require_role(request, "operator")
        templates = store.list_templates(workspace_id)
        current = next((item for item in templates if item["id"] == template_id), None)
        if not current:
            raise ApplicationError("Шаблон не найден.", status_code=404)
        update = {
            "layout": payload.layout or current["layout"],
            "composite": normalize_composite_rules(payload.composite),
            "fingerprint": payload.fingerprint,
            "comment": payload.comment,
            "actor_user_id": actor.get("id"),
        }
        return store.update_template(workspace_id, template_id, update)

    @router.get("/api/workspaces/{workspace_id}/runs")
    def list_runs(
        workspace_id: str,
        request: Request,
        limit: int = Query(100, ge=1, le=500),
    ) -> Dict[str, Any]:
        require_role(request, "viewer")
        return {"items": store.list_processing_runs(workspace_id, limit)}

    @router.get("/api/workspaces/{workspace_id}/runs/{run_id}")
    def run_details(workspace_id: str, run_id: str, request: Request) -> Dict[str, Any]:
        require_role(request, "viewer")
        run = store.get_processing_run(run_id)
        if run["workspace_id"] != workspace_id:
            raise ApplicationError("Запуск относится к другому пространству.", status_code=404)
        return run

    @router.get("/api/workspaces/{workspace_id}/audit")
    def audit_log(
        workspace_id: str,
        request: Request,
        limit: int = Query(200, ge=1, le=1000),
        offset: int = Query(0, ge=0),
    ) -> Dict[str, Any]:
        require_role(request, "viewer")
        return {"items": store.list_audit(workspace_id=workspace_id, limit=limit, offset=offset)}

    @router.get("/api/operations/summary")
    def operations_summary(request: Request) -> Dict[str, Any]:
        actor = actor_from_request(request)
        workspace_id = request.query_params.get("workspace_id") or store.default_workspace_id()
        runs = store.list_processing_runs(workspace_id, 20)
        imports = store.list_import_jobs(workspace_id, 20)
        templates = store.list_templates(workspace_id)
        return {
            "workspace_id": workspace_id,
            "actor": actor,
            "runs": {
                "total": len(runs),
                "success": sum(1 for item in runs if item["status"] == "success"),
                "attention": sum(1 for item in runs if item["status"] != "success"),
            },
            "imports": {
                "pending": sum(1 for item in imports if item["status"] == "preview"),
                "committed": sum(1 for item in imports if item["status"] == "committed"),
            },
            "templates": {
                "total": len(templates),
                "used": sum(1 for item in templates if item.get("last_used_at")),
                "average_quality": round(
                    sum(float(item.get("avg_quality") or 0) for item in templates) / max(1, len(templates)),
                    1,
                ),
            },
        }

    return router
