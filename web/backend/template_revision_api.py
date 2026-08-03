"""Template revisions, composite components, rollback and learned format rules."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from src.operations_domain import AuthenticatedUser
from src.template_definition import (
    add_component,
    delete_component,
    normalize_definition,
    wrap_layout,
)
from src.workbook_fingerprint import selected_sheet_fingerprint
from web.backend.app_context import ApplicationContext
from web.backend.auth import operator_dependency, viewer_dependency


class RevisionUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    layout: Optional[Dict[str, Any]] = None
    comment: str = ""


class RollbackRequest(BaseModel):
    revision_id: str
    comment: str = ""


class LearnTemplateRequest(BaseModel):
    session_id: str
    file_id: str
    layout: Dict[str, Any]
    template_id: Optional[str] = None
    template_name: Optional[str] = None
    description: str = ""
    component_label: str = ""
    replace_component_id: Optional[str] = None
    comment: str = ""
    priority: int = Field(default=0, ge=-100, le=100)


class DeleteComponentRequest(BaseModel):
    component_id: str
    comment: str = ""


def build_template_revision_router(context: ApplicationContext) -> APIRouter:
    router = APIRouter(tags=["template-revisions"])
    viewer = viewer_dependency(context)
    operator = operator_dependency(context)

    @router.get("/api/workspaces/{workspace_id}/templates/{template_id}/revisions")
    def list_revisions(
        workspace_id: str,
        template_id: str,
        _: AuthenticatedUser = Depends(viewer),
    ) -> List[Dict[str, Any]]:
        return context.operations.list_template_revisions(workspace_id, template_id)

    @router.get("/api/template-revisions/compare")
    def compare_revisions(
        from_revision: str = Query(..., alias="from"),
        to_revision: str = Query(..., alias="to"),
        _: AuthenticatedUser = Depends(viewer),
    ) -> Dict[str, Any]:
        return context.operations.compare_template_revisions(from_revision, to_revision)

    @router.post("/api/workspaces/{workspace_id}/templates/{template_id}/revision")
    def update_template_revision(
        workspace_id: str,
        template_id: str,
        payload: RevisionUpdateRequest,
        user: AuthenticatedUser = Depends(operator),
    ) -> Dict[str, Any]:
        values = payload.model_dump(exclude_unset=True) if hasattr(payload, "model_dump") else payload.dict(exclude_unset=True)
        comment = values.pop("comment", "")
        return context.operations.update_template_with_revision(
            workspace_id=workspace_id,
            template_id=template_id,
            payload=values,
            comment=comment,
            source="manual",
            user_id=user.id,
        )

    @router.post("/api/workspaces/{workspace_id}/templates/{template_id}/rollback")
    def rollback_template(
        workspace_id: str,
        template_id: str,
        payload: RollbackRequest,
        user: AuthenticatedUser = Depends(operator),
    ) -> Dict[str, Any]:
        return context.operations.rollback_template(
            workspace_id=workspace_id,
            template_id=template_id,
            revision_id=payload.revision_id,
            comment=payload.comment,
            user_id=user.id,
        )

    @router.post("/api/workspaces/{workspace_id}/templates/learn")
    def learn_template(
        workspace_id: str,
        payload: LearnTemplateRequest,
        user: AuthenticatedUser = Depends(operator),
    ) -> Dict[str, Any]:
        manifest = context.sessions.load_manifest(payload.session_id)
        file_item = context.sessions.manifest_file(manifest, payload.file_id)
        analysis = file_item.get("analysis") or {}
        workbook_fingerprint = analysis.get("fingerprint") or {}
        sheet_name = str(payload.layout.get("sheet_name") or analysis.get("selected_sheet") or "")
        sheet_fingerprint = selected_sheet_fingerprint(workbook_fingerprint, sheet_name)
        label = payload.component_label.strip() or sheet_name or "Новый формат"
        selector = {
            "sheet_name": sheet_name,
            "keywords": sheet_fingerprint.get("header_tokens", [])[:12],
        }
        if payload.template_id:
            current = next(
                item for item in context.workspace_repository.list_templates(workspace_id)
                if item["id"] == payload.template_id
            )
            definition = add_component(
                current.get("layout") or {},
                layout=payload.layout,
                label=label,
                fingerprint=sheet_fingerprint,
                selector=selector,
                replace_component_id=payload.replace_component_id,
            )
            template = context.operations.update_template_with_revision(
                workspace_id=workspace_id,
                template_id=payload.template_id,
                payload={"layout": definition},
                comment=payload.comment or f"Добавлен формат «{label}».",
                source="learned",
                user_id=user.id,
            )
            template_id = payload.template_id
        else:
            definition = wrap_layout(
                payload.layout,
                label=label,
                fingerprint=sheet_fingerprint,
                selector=selector,
            )
            template = context.operations.create_template_with_revision(
                workspace_id=workspace_id,
                name=(payload.template_name or label).strip(),
                description=payload.description,
                definition=definition,
                comment=payload.comment or "Создано из подтверждённой оператором разметки.",
                source="learned",
                user_id=user.id,
            )
            template_id = template["id"]
        revision_id = template.get("current_revision_id")
        component_id = normalize_definition(template["layout"])["components"][-1]["id"]
        rule = context.operations.create_format_rule(
            workspace_id=workspace_id,
            template_id=template_id,
            revision_id=revision_id,
            component_id=component_id,
            fingerprint={
                **sheet_fingerprint,
                "workbook_signature": workbook_fingerprint.get("signature"),
                "sheet_signature": sheet_fingerprint.get("signature"),
            },
            priority=payload.priority,
            user_id=user.id,
        )
        return {"template": template, "rule": rule}

    @router.delete("/api/workspaces/{workspace_id}/templates/{template_id}/components")
    def remove_component(
        workspace_id: str,
        template_id: str,
        payload: DeleteComponentRequest,
        user: AuthenticatedUser = Depends(operator),
    ) -> Dict[str, Any]:
        current = next(
            item for item in context.workspace_repository.list_templates(workspace_id)
            if item["id"] == template_id
        )
        definition = delete_component(current.get("layout") or {}, payload.component_id)
        return context.operations.update_template_with_revision(
            workspace_id=workspace_id,
            template_id=template_id,
            payload={"layout": definition},
            comment=payload.comment or "Удалён компонент составного шаблона.",
            source="manual",
            user_id=user.id,
        )

    @router.get("/api/workspaces/{workspace_id}/format-rules")
    def list_rules(
        workspace_id: str,
        _: AuthenticatedUser = Depends(viewer),
    ) -> List[Dict[str, Any]]:
        return context.operations.list_format_rules(workspace_id)

    return router
