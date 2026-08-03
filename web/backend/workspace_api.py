"""Role-aware workspace, teacher and revisioned-template API."""
from __future__ import annotations

import csv
import io
import json
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, FastAPI, Query
from fastapi.responses import Response

from src.operations_domain import AuthenticatedUser
from src.revision_bootstrap import ensure_template_revisions
from src.workspace_domain import WorkspaceNotFound
from web.backend.app_context import ApplicationContext
from web.backend.auth import admin_dependency, operator_dependency, viewer_dependency
from web.backend.schemas import (
    LayoutTemplate,
    Teacher,
    TeacherCreate,
    TeacherUpdate,
    TemplateCreate,
    TemplateUpdate,
    WorkspaceCreate,
    WorkspaceDuplicateRequest,
    WorkspaceSummary,
    WorkspaceUpdate,
)


def model_dict(model: Any, exclude_unset: bool = False) -> Dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(exclude_unset=exclude_unset, mode="json")
    return model.dict(exclude_unset=exclude_unset)


def json_download(payload: Any, filename: str) -> Response:
    return Response(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _find_teacher(repository: Any, workspace_id: str, teacher_id: int) -> Dict[str, Any]:
    for item in repository.list_teachers(workspace_id):
        if int(item["id"]) == int(teacher_id):
            return item
    raise WorkspaceNotFound("Преподаватель не найден.")


def _find_template(repository: Any, workspace_id: str, template_id: str) -> Dict[str, Any]:
    for item in repository.list_templates(workspace_id):
        if item["id"] == template_id:
            return item
    raise WorkspaceNotFound("Шаблон не найден.")


def build_workspace_router(context: ApplicationContext) -> APIRouter:
    router = APIRouter(tags=["workspaces"])
    repository = context.workspace_repository
    viewer = viewer_dependency(context)
    operator = operator_dependency(context)
    admin = admin_dependency(context)

    @router.get("/api/workspaces", response_model=List[WorkspaceSummary])
    def list_workspaces(_: AuthenticatedUser = Depends(viewer)) -> List[Dict[str, Any]]:
        return repository.list_workspaces()

    @router.post("/api/workspaces", response_model=WorkspaceSummary)
    def create_workspace(
        payload: WorkspaceCreate,
        user: AuthenticatedUser = Depends(admin),
    ) -> Dict[str, Any]:
        created = repository.create_workspace(model_dict(payload, True))
        context.operations.record_audit(
            user_id=user.id,
            action="create",
            entity_type="workspace",
            entity_id=created["id"],
            workspace_id=created["id"],
            summary=f"Создано пространство «{created['name']}».",
        )
        return created

    @router.put("/api/workspaces/{workspace_id}", response_model=WorkspaceSummary)
    def update_workspace(
        workspace_id: str,
        payload: WorkspaceUpdate,
        user: AuthenticatedUser = Depends(admin),
    ) -> Dict[str, Any]:
        updated = repository.update_workspace(workspace_id, model_dict(payload, True))
        context.operations.record_audit(
            user_id=user.id,
            action="update",
            entity_type="workspace",
            entity_id=workspace_id,
            workspace_id=workspace_id,
            summary=f"Изменено пространство «{updated['name']}».",
            details=model_dict(payload, True),
        )
        return updated

    @router.delete("/api/workspaces/{workspace_id}")
    def delete_workspace(
        workspace_id: str,
        user: AuthenticatedUser = Depends(admin),
    ) -> Dict[str, str]:
        selected = repository.get_workspace(workspace_id)
        repository.delete_workspace(workspace_id)
        context.operations.record_audit(
            user_id=user.id,
            action="delete",
            entity_type="workspace",
            entity_id=workspace_id,
            workspace_id=None,
            summary=f"Удалено пространство «{selected['name']}».",
        )
        return {"status": "success"}

    @router.post("/api/workspaces/{workspace_id}/duplicate", response_model=WorkspaceSummary)
    def duplicate_workspace(
        workspace_id: str,
        payload: WorkspaceDuplicateRequest,
        user: AuthenticatedUser = Depends(admin),
    ) -> Dict[str, Any]:
        duplicate = repository.duplicate_workspace(workspace_id, payload.name)
        ensure_template_revisions(context.operations)
        context.operations.record_audit(
            user_id=user.id,
            action="duplicate",
            entity_type="workspace",
            entity_id=duplicate["id"],
            workspace_id=duplicate["id"],
            summary=f"Создана копия пространства «{duplicate['name']}».",
            details={"source_workspace_id": workspace_id},
        )
        return duplicate

    @router.get("/api/workspaces/{workspace_id}/export")
    def export_workspace(
        workspace_id: str,
        _: AuthenticatedUser = Depends(viewer),
    ) -> Response:
        return json_download(repository.export_workspace(workspace_id), "planner-workspace.json")

    @router.get("/api/workspaces/{workspace_id}/teachers", response_model=List[Teacher])
    def list_teachers(
        workspace_id: str,
        _: AuthenticatedUser = Depends(viewer),
    ) -> List[Dict[str, Any]]:
        return repository.list_teachers(workspace_id)

    @router.post("/api/workspaces/{workspace_id}/teachers", response_model=Teacher)
    def create_teacher(
        workspace_id: str,
        payload: TeacherCreate,
        user: AuthenticatedUser = Depends(admin),
    ) -> Dict[str, Any]:
        created = repository.create_teacher(workspace_id, model_dict(payload))
        context.operations.record_audit(
            user_id=user.id,
            action="create",
            entity_type="teacher",
            entity_id=str(created["id"]),
            workspace_id=workspace_id,
            summary=f"Добавлен преподаватель {created['short_name']}.",
        )
        return created

    @router.put("/api/workspaces/{workspace_id}/teachers/{teacher_id}", response_model=Teacher)
    def update_teacher(
        workspace_id: str,
        teacher_id: int,
        payload: TeacherUpdate,
        user: AuthenticatedUser = Depends(admin),
    ) -> Dict[str, Any]:
        updated = repository.update_teacher(workspace_id, teacher_id, model_dict(payload, True))
        context.operations.record_audit(
            user_id=user.id,
            action="update",
            entity_type="teacher",
            entity_id=str(teacher_id),
            workspace_id=workspace_id,
            summary=f"Изменён преподаватель {updated['short_name']}.",
            details=model_dict(payload, True),
        )
        return updated

    @router.delete("/api/workspaces/{workspace_id}/teachers/{teacher_id}")
    def delete_teacher(
        workspace_id: str,
        teacher_id: int,
        user: AuthenticatedUser = Depends(admin),
    ) -> Dict[str, str]:
        selected = _find_teacher(repository, workspace_id, teacher_id)
        repository.delete_teacher(workspace_id, teacher_id)
        context.operations.record_audit(
            user_id=user.id,
            action="delete",
            entity_type="teacher",
            entity_id=str(teacher_id),
            workspace_id=workspace_id,
            summary=f"Удалён преподаватель {selected['short_name']}.",
        )
        return {"status": "success"}

    @router.get("/api/workspaces/{workspace_id}/teachers/export")
    def export_teachers(
        workspace_id: str,
        format: str = Query("csv", pattern="^(csv|json)$"),
        _: AuthenticatedUser = Depends(viewer),
    ) -> Response:
        teachers = repository.list_teachers(workspace_id)
        if format == "json":
            return json_download({"teachers": teachers}, "teachers.json")
        buffer = io.StringIO()
        fields = ["short_name", "full_name", "position", "rank", "academic_degree"]
        writer = csv.DictWriter(buffer, fieldnames=fields, delimiter=";")
        writer.writeheader()
        writer.writerows({key: item.get(key, "") for key in fields} for item in teachers)
        return Response(
            "\ufeff" + buffer.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="teachers.csv"'},
        )

    @router.get("/api/workspaces/{workspace_id}/templates", response_model=List[LayoutTemplate])
    def list_templates(
        workspace_id: str,
        _: AuthenticatedUser = Depends(viewer),
    ) -> List[Dict[str, Any]]:
        templates = repository.list_templates(workspace_id)
        for template in templates:
            revisions = context.operations.list_template_revisions(workspace_id, template["id"])
            if revisions:
                template["current_revision_id"] = revisions[0]["id"]
                template["revision_number"] = revisions[0]["revision_number"]
            learning = context.operations.template_learning_summary(template["id"])
            template["success_count"] = learning["successes"]
            template["failure_count"] = learning["failures"]
        return templates

    @router.post("/api/workspaces/{workspace_id}/templates", response_model=LayoutTemplate)
    def create_template(
        workspace_id: str,
        payload: TemplateCreate,
        user: AuthenticatedUser = Depends(operator),
    ) -> Dict[str, Any]:
        values = model_dict(payload)
        return context.operations.create_template_with_revision(
            workspace_id=workspace_id,
            name=values["name"],
            description=values.get("description", ""),
            definition=values["layout"],
            comment=values.get("comment", ""),
            source="manual",
            user_id=user.id,
        )

    @router.put("/api/workspaces/{workspace_id}/templates/{template_id}", response_model=LayoutTemplate)
    def update_template(
        workspace_id: str,
        template_id: str,
        payload: TemplateUpdate,
        user: AuthenticatedUser = Depends(operator),
    ) -> Dict[str, Any]:
        values = model_dict(payload, True)
        comment = values.pop("comment", "")
        return context.operations.update_template_with_revision(
            workspace_id=workspace_id,
            template_id=template_id,
            payload=values,
            comment=comment,
            source="manual",
            user_id=user.id,
        )

    @router.delete("/api/workspaces/{workspace_id}/templates/{template_id}")
    def delete_template(
        workspace_id: str,
        template_id: str,
        user: AuthenticatedUser = Depends(operator),
    ) -> Dict[str, str]:
        selected = _find_template(repository, workspace_id, template_id)
        repository.delete_template(workspace_id, template_id)
        context.operations.record_audit(
            user_id=user.id,
            action="delete",
            entity_type="template",
            entity_id=template_id,
            workspace_id=workspace_id,
            summary=f"Удалён шаблон «{selected['name']}».",
        )
        return {"status": "success"}

    @router.get("/api/workspaces/{workspace_id}/templates/export")
    def export_templates(
        workspace_id: str,
        _: AuthenticatedUser = Depends(viewer),
    ) -> Response:
        return json_download(
            {"templates": repository.list_templates(workspace_id)},
            "layout-templates.json",
        )

    @router.get("/api/teachers", response_model=List[Teacher])
    def legacy_list_teachers(_: AuthenticatedUser = Depends(viewer)) -> List[Dict[str, Any]]:
        return repository.list_teachers(repository.default_workspace_id())

    @router.post("/api/teachers", response_model=Teacher)
    def legacy_create_teacher(
        payload: TeacherCreate,
        user: AuthenticatedUser = Depends(admin),
    ) -> Dict[str, Any]:
        return create_teacher(repository.default_workspace_id(), payload, user)

    @router.put("/api/teachers/{teacher_id}", response_model=Teacher)
    def legacy_update_teacher(
        teacher_id: int,
        payload: TeacherUpdate,
        user: AuthenticatedUser = Depends(admin),
    ) -> Dict[str, Any]:
        return update_teacher(repository.default_workspace_id(), teacher_id, payload, user)

    @router.delete("/api/teachers/{teacher_id}")
    def legacy_delete_teacher(
        teacher_id: int,
        user: AuthenticatedUser = Depends(admin),
    ) -> Dict[str, str]:
        return delete_teacher(repository.default_workspace_id(), teacher_id, user)

    return router


def install_workspace_api(app: FastAPI, context: ApplicationContext) -> FastAPI:
    app.include_router(build_workspace_router(context))
    return app
