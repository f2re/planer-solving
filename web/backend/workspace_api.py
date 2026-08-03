"""Workspace, teacher and server-side layout-template API."""
from __future__ import annotations

import csv
import io
import json
from typing import Any, Dict, List

from fastapi import APIRouter, FastAPI, File, Query, Request, UploadFile
from fastapi.responses import Response

from web.backend.app_context import ApplicationContext
from web.backend.auth import actor_from_request
from web.backend.errors import ApplicationError
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


async def read_json_upload(file: UploadFile) -> Any:
    payload = await file.read()
    await file.close()
    if not payload:
        raise ApplicationError("Файл пуст.")
    for encoding in ("utf-8-sig", "utf-8", "cp1251"):
        try:
            decoded = payload.decode(encoding)
            break
        except UnicodeDecodeError:
            decoded = ""
    if not decoded:
        raise ApplicationError("Не удалось определить кодировку JSON-файла.")
    try:
        return json.loads(decoded)
    except json.JSONDecodeError as exc:
        raise ApplicationError(f"Некорректный JSON: {exc}") from exc


def build_workspace_router(context: ApplicationContext) -> APIRouter:
    router = APIRouter(tags=["workspaces"])
    repository = context.workspace_repository

    @router.get("/api/workspaces", response_model=List[WorkspaceSummary])
    def list_workspaces() -> List[Dict[str, Any]]:
        return repository.list_workspaces()

    @router.post("/api/workspaces", response_model=WorkspaceSummary)
    def create_workspace(payload: WorkspaceCreate, request: Request) -> Dict[str, Any]:
        actor = actor_from_request(request)
        result = repository.create_workspace(model_dict(payload, True))
        repository.audit(
            actor=actor,
            action="workspace.create",
            entity_type="workspace",
            entity_id=result["id"],
            workspace_id=result["id"],
            summary=f"Создано пространство «{result['name']}»",
        )
        return result

    @router.put("/api/workspaces/{workspace_id}", response_model=WorkspaceSummary)
    def update_workspace(
        workspace_id: str,
        payload: WorkspaceUpdate,
        request: Request,
    ) -> Dict[str, Any]:
        actor = actor_from_request(request)
        result = repository.update_workspace(workspace_id, model_dict(payload, True))
        repository.audit(
            actor=actor,
            action="workspace.update",
            entity_type="workspace",
            entity_id=workspace_id,
            workspace_id=workspace_id,
            summary=f"Изменено пространство «{result['name']}»",
        )
        return result

    @router.delete("/api/workspaces/{workspace_id}")
    def delete_workspace(workspace_id: str, request: Request) -> Dict[str, str]:
        actor = actor_from_request(request)
        current = repository.get_workspace(workspace_id)
        repository.audit(
            actor=actor,
            action="workspace.delete",
            entity_type="workspace",
            entity_id=workspace_id,
            workspace_id=workspace_id,
            summary=f"Удалено пространство «{current['name']}»",
        )
        repository.delete_workspace(workspace_id)
        return {"status": "success"}

    @router.post("/api/workspaces/{workspace_id}/duplicate", response_model=WorkspaceSummary)
    def duplicate_workspace(
        workspace_id: str,
        payload: WorkspaceDuplicateRequest,
        request: Request,
    ) -> Dict[str, Any]:
        actor = actor_from_request(request)
        result = repository.duplicate_workspace(workspace_id, payload.name)
        repository.audit(
            actor=actor,
            action="workspace.duplicate",
            entity_type="workspace",
            entity_id=result["id"],
            workspace_id=result["id"],
            summary=f"Создана копия пространства «{result['name']}»",
            details={"source_workspace_id": workspace_id},
        )
        return result

    @router.get("/api/workspaces/{workspace_id}/export")
    def export_workspace(workspace_id: str) -> Response:
        return json_download(repository.export_workspace(workspace_id), "planner-workspace.json")

    @router.post("/api/workspaces/import", response_model=WorkspaceSummary)
    async def import_workspace(
        request: Request,
        file: UploadFile = File(...),
    ) -> Dict[str, Any]:
        actor = actor_from_request(request)
        result = repository.import_workspace(await read_json_upload(file))
        repository.audit(
            actor=actor,
            action="workspace.import",
            entity_type="workspace",
            entity_id=result["id"],
            workspace_id=result["id"],
            summary=f"Импортировано пространство «{result['name']}»",
        )
        return result

    @router.get("/api/workspaces/{workspace_id}/teachers", response_model=List[Teacher])
    def list_teachers(workspace_id: str) -> List[Dict[str, Any]]:
        return repository.list_teachers(workspace_id)

    @router.post("/api/workspaces/{workspace_id}/teachers", response_model=Teacher)
    def create_teacher(
        workspace_id: str,
        payload: TeacherCreate,
        request: Request,
    ) -> Dict[str, Any]:
        actor = actor_from_request(request)
        result = repository.create_teacher(workspace_id, model_dict(payload))
        repository.audit(
            actor=actor,
            action="teacher.create",
            entity_type="teacher",
            entity_id=str(result["id"]),
            workspace_id=workspace_id,
            summary=f"Добавлен преподаватель «{result['full_name']}»",
        )
        return result

    @router.put("/api/workspaces/{workspace_id}/teachers/{teacher_id}", response_model=Teacher)
    def update_teacher(
        workspace_id: str,
        teacher_id: int,
        payload: TeacherUpdate,
        request: Request,
    ) -> Dict[str, Any]:
        actor = actor_from_request(request)
        result = repository.update_teacher(
            workspace_id,
            teacher_id,
            model_dict(payload, True),
        )
        repository.audit(
            actor=actor,
            action="teacher.update",
            entity_type="teacher",
            entity_id=str(teacher_id),
            workspace_id=workspace_id,
            summary=f"Изменён преподаватель «{result['full_name']}»",
        )
        return result

    @router.delete("/api/workspaces/{workspace_id}/teachers/{teacher_id}")
    def delete_teacher(
        workspace_id: str,
        teacher_id: int,
        request: Request,
    ) -> Dict[str, str]:
        actor = actor_from_request(request)
        current = next(
            (item for item in repository.list_teachers(workspace_id) if item["id"] == teacher_id),
            None,
        )
        repository.delete_teacher(workspace_id, teacher_id)
        repository.audit(
            actor=actor,
            action="teacher.delete",
            entity_type="teacher",
            entity_id=str(teacher_id),
            workspace_id=workspace_id,
            summary=f"Удалён преподаватель «{(current or {}).get('full_name', teacher_id)}»",
        )
        return {"status": "success"}

    @router.get("/api/workspaces/{workspace_id}/teachers/export")
    def export_teachers(
        workspace_id: str,
        format: str = Query("csv", pattern="^(csv|json)$"),
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

    @router.post("/api/workspaces/{workspace_id}/teachers/import")
    def direct_teacher_import_disabled(workspace_id: str) -> None:
        raise ApplicationError(
            "Прямой импорт отключён. Используйте мастер предварительного импорта.",
            status_code=409,
            code="import_preview_required",
        )

    @router.get("/api/workspaces/{workspace_id}/templates", response_model=List[LayoutTemplate])
    def list_templates(workspace_id: str) -> List[Dict[str, Any]]:
        return repository.list_templates(workspace_id)

    @router.post("/api/workspaces/{workspace_id}/templates", response_model=LayoutTemplate)
    def create_template(
        workspace_id: str,
        payload: TemplateCreate,
        request: Request,
    ) -> Dict[str, Any]:
        actor = actor_from_request(request)
        values = model_dict(payload)
        values["actor_user_id"] = actor.get("id")
        result = repository.create_template(workspace_id, values)
        repository.audit(
            actor=actor,
            action="template.create",
            entity_type="template",
            entity_id=result["id"],
            workspace_id=workspace_id,
            summary=f"Создан шаблон «{result['name']}»",
        )
        return result

    @router.put("/api/workspaces/{workspace_id}/templates/{template_id}", response_model=LayoutTemplate)
    def update_template(
        workspace_id: str,
        template_id: str,
        payload: TemplateUpdate,
        request: Request,
    ) -> Dict[str, Any]:
        actor = actor_from_request(request)
        values = model_dict(payload, True)
        values["actor_user_id"] = actor.get("id")
        return repository.update_template(workspace_id, template_id, values)

    @router.delete("/api/workspaces/{workspace_id}/templates/{template_id}")
    def delete_template(
        workspace_id: str,
        template_id: str,
        request: Request,
    ) -> Dict[str, str]:
        actor = actor_from_request(request)
        current = next(
            (item for item in repository.list_templates(workspace_id) if item["id"] == template_id),
            None,
        )
        repository.delete_template(workspace_id, template_id)
        repository.audit(
            actor=actor,
            action="template.delete",
            entity_type="template",
            entity_id=template_id,
            workspace_id=workspace_id,
            summary=f"Удалён шаблон «{(current or {}).get('name', template_id)}»",
        )
        return {"status": "success"}

    @router.get("/api/workspaces/{workspace_id}/templates/export")
    def export_templates(workspace_id: str) -> Response:
        return json_download(
            {"templates": repository.list_templates(workspace_id)},
            "layout-templates.json",
        )

    @router.post("/api/workspaces/{workspace_id}/templates/import")
    def direct_template_import_disabled(workspace_id: str) -> None:
        raise ApplicationError(
            "Прямой импорт отключён. Используйте мастер предварительного импорта.",
            status_code=409,
            code="import_preview_required",
        )

    # Read-compatible routes for old clients. Writes remain subject to role policy.
    @router.get("/api/teachers", response_model=List[Teacher])
    def legacy_list_teachers() -> List[Dict[str, Any]]:
        return repository.list_teachers(repository.default_workspace_id())

    @router.post("/api/teachers", response_model=Teacher)
    def legacy_create_teacher(payload: TeacherCreate, request: Request) -> Dict[str, Any]:
        return create_teacher(repository.default_workspace_id(), payload, request)

    @router.put("/api/teachers/{teacher_id}", response_model=Teacher)
    def legacy_update_teacher(
        teacher_id: int,
        payload: TeacherUpdate,
        request: Request,
    ) -> Dict[str, Any]:
        return update_teacher(repository.default_workspace_id(), teacher_id, payload, request)

    @router.delete("/api/teachers/{teacher_id}")
    def legacy_delete_teacher(teacher_id: int, request: Request) -> Dict[str, str]:
        return delete_teacher(repository.default_workspace_id(), teacher_id, request)

    return router


def install_workspace_api(app: FastAPI, context: ApplicationContext) -> FastAPI:
    app.include_router(build_workspace_router(context))
    return app
