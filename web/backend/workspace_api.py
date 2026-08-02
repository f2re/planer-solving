"""Workspace, teacher and server-side layout-template API."""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, FastAPI, File, Query, UploadFile
from fastapi.responses import Response

from web.backend.app_context import ApplicationContext
from web.backend.errors import ApplicationError
from web.backend.schemas import (
    ImportResult,
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
        return model.model_dump(exclude_unset=exclude_unset)
    return model.dict(exclude_unset=exclude_unset)


def json_download(payload: Any, filename: str) -> Response:
    return Response(
        json.dumps(payload, ensure_ascii=False, indent=2),
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


async def bytes_from(file: UploadFile) -> bytes:
    payload = await file.read()
    await file.close()
    if not payload:
        raise ApplicationError("Файл пуст.")
    return payload


def decode(payload: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1251"):
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ApplicationError("Не удалось определить кодировку файла.")


def teacher_records(payload: bytes, filename: str) -> List[Dict[str, Any]]:
    decoded = decode(payload)
    if Path(filename).suffix.lower() == ".json":
        try:
            data = json.loads(decoded)
        except json.JSONDecodeError as exc:
            raise ApplicationError(f"Некорректный JSON: {exc}") from exc
        data = data.get("teachers", data.get("items", [])) if isinstance(data, dict) else data
        if not isinstance(data, list):
            raise ApplicationError("JSON должен содержать список teachers.")
        return [item for item in data if isinstance(item, dict)]
    if Path(filename).suffix.lower() not in {".csv", ".txt"}:
        raise ApplicationError("Поддерживаются JSON и CSV.")
    try:
        dialect = csv.Sniffer().sniff(decoded[:4096], delimiters=";,\t,")
        rows = list(csv.DictReader(io.StringIO(decoded), dialect=dialect))
    except csv.Error:
        rows = list(csv.DictReader(io.StringIO(decoded), delimiter=";"))
    aliases = {
        "short_name": {"short_name", "краткое имя", "фио кратко", "краткое фио", "сокращение"},
        "full_name": {"full_name", "полное фио", "фио", "полное имя"},
        "position": {"position", "должность"},
        "rank": {"rank", "звание", "ученое звание", "учёное звание"},
        "academic_degree": {"academic_degree", "степень", "ученая степень", "учёная степень"},
    }
    result = []
    for row in rows:
        normalized = {str(key or "").strip().casefold(): value for key, value in row.items()}
        result.append({
            target: next((normalized[name] for name in names if name in normalized), "")
            for target, names in aliases.items()
        })
    return result


def template_records(payload: bytes, filename: str) -> List[Dict[str, Any]]:
    if Path(filename).suffix.lower() != ".json":
        raise ApplicationError("Шаблоны импортируются из JSON.")
    try:
        data = json.loads(decode(payload))
    except json.JSONDecodeError as exc:
        raise ApplicationError(f"Некорректный JSON: {exc}") from exc
    data = data.get("templates", data.get("items", [])) if isinstance(data, dict) else data
    if not isinstance(data, list):
        raise ApplicationError("JSON должен содержать список templates.")
    return [item for item in data if isinstance(item, dict)]


def build_workspace_router(context: ApplicationContext) -> APIRouter:
    router = APIRouter(tags=["workspaces"])
    repository = context.workspace_repository

    @router.get("/api/workspaces", response_model=List[WorkspaceSummary])
    def list_workspaces() -> List[Dict[str, Any]]:
        return repository.list_workspaces()

    @router.post("/api/workspaces", response_model=WorkspaceSummary)
    def create_workspace(payload: WorkspaceCreate) -> Dict[str, Any]:
        return repository.create_workspace(model_dict(payload, True))

    @router.put("/api/workspaces/{workspace_id}", response_model=WorkspaceSummary)
    def update_workspace(workspace_id: str, payload: WorkspaceUpdate) -> Dict[str, Any]:
        return repository.update_workspace(workspace_id, model_dict(payload, True))

    @router.delete("/api/workspaces/{workspace_id}")
    def delete_workspace(workspace_id: str) -> Dict[str, str]:
        repository.delete_workspace(workspace_id)
        return {"status": "success"}

    @router.post("/api/workspaces/{workspace_id}/duplicate", response_model=WorkspaceSummary)
    def duplicate_workspace(
        workspace_id: str,
        payload: WorkspaceDuplicateRequest,
    ) -> Dict[str, Any]:
        return repository.duplicate_workspace(workspace_id, payload.name)

    @router.get("/api/workspaces/{workspace_id}/export")
    def export_workspace(workspace_id: str) -> Response:
        return json_download(repository.export_workspace(workspace_id), "planner-workspace.json")

    @router.post("/api/workspaces/import", response_model=WorkspaceSummary)
    async def import_workspace(file: UploadFile = File(...)) -> Dict[str, Any]:
        try:
            data = json.loads(decode(await bytes_from(file)))
        except json.JSONDecodeError as exc:
            raise ApplicationError(f"Некорректный JSON: {exc}") from exc
        return repository.import_workspace(data)

    @router.get("/api/workspaces/{workspace_id}/teachers", response_model=List[Teacher])
    def list_teachers(workspace_id: str) -> List[Dict[str, Any]]:
        return repository.list_teachers(workspace_id)

    @router.post("/api/workspaces/{workspace_id}/teachers", response_model=Teacher)
    def create_teacher(workspace_id: str, payload: TeacherCreate) -> Dict[str, Any]:
        return repository.create_teacher(workspace_id, model_dict(payload))

    @router.put("/api/workspaces/{workspace_id}/teachers/{teacher_id}", response_model=Teacher)
    def update_teacher(
        workspace_id: str,
        teacher_id: int,
        payload: TeacherUpdate,
    ) -> Dict[str, Any]:
        return repository.update_teacher(
            workspace_id,
            teacher_id,
            model_dict(payload, True),
        )

    @router.delete("/api/workspaces/{workspace_id}/teachers/{teacher_id}")
    def delete_teacher(workspace_id: str, teacher_id: int) -> Dict[str, str]:
        repository.delete_teacher(workspace_id, teacher_id)
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

    @router.post("/api/workspaces/{workspace_id}/teachers/import", response_model=ImportResult)
    async def import_teachers(
        workspace_id: str,
        file: UploadFile = File(...),
        mode: str = Query("append", pattern="^(append|replace)$"),
    ) -> Dict[str, int]:
        records = teacher_records(await bytes_from(file), file.filename or "teachers.csv")
        return repository.import_teachers(workspace_id, records, mode)

    @router.get("/api/workspaces/{workspace_id}/templates", response_model=List[LayoutTemplate])
    def list_templates(workspace_id: str) -> List[Dict[str, Any]]:
        return repository.list_templates(workspace_id)

    @router.post("/api/workspaces/{workspace_id}/templates", response_model=LayoutTemplate)
    def create_template(workspace_id: str, payload: TemplateCreate) -> Dict[str, Any]:
        return repository.create_template(workspace_id, model_dict(payload))

    @router.put("/api/workspaces/{workspace_id}/templates/{template_id}", response_model=LayoutTemplate)
    def update_template(
        workspace_id: str,
        template_id: str,
        payload: TemplateUpdate,
    ) -> Dict[str, Any]:
        return repository.update_template(
            workspace_id,
            template_id,
            model_dict(payload, True),
        )

    @router.delete("/api/workspaces/{workspace_id}/templates/{template_id}")
    def delete_template(workspace_id: str, template_id: str) -> Dict[str, str]:
        repository.delete_template(workspace_id, template_id)
        return {"status": "success"}

    @router.get("/api/workspaces/{workspace_id}/templates/export")
    def export_templates(workspace_id: str) -> Response:
        return json_download(
            {"templates": repository.list_templates(workspace_id)},
            "layout-templates.json",
        )

    @router.post("/api/workspaces/{workspace_id}/templates/import", response_model=ImportResult)
    async def import_templates(
        workspace_id: str,
        file: UploadFile = File(...),
        mode: str = Query("append", pattern="^(append|replace)$"),
    ) -> Dict[str, int]:
        records = template_records(await bytes_from(file), file.filename or "templates.json")
        return repository.import_templates(workspace_id, records, mode)

    # Compatibility routes for old clients. They operate on the default workspace.
    @router.get("/api/teachers", response_model=List[Teacher])
    def legacy_list_teachers() -> List[Dict[str, Any]]:
        return repository.list_teachers(repository.default_workspace_id())

    @router.post("/api/teachers", response_model=Teacher)
    def legacy_create_teacher(payload: TeacherCreate) -> Dict[str, Any]:
        return repository.create_teacher(
            repository.default_workspace_id(),
            model_dict(payload),
        )

    @router.put("/api/teachers/{teacher_id}", response_model=Teacher)
    def legacy_update_teacher(teacher_id: int, payload: TeacherUpdate) -> Dict[str, Any]:
        return repository.update_teacher(
            repository.default_workspace_id(),
            teacher_id,
            model_dict(payload, True),
        )

    @router.delete("/api/teachers/{teacher_id}")
    def legacy_delete_teacher(teacher_id: int) -> Dict[str, str]:
        repository.delete_teacher(repository.default_workspace_id(), teacher_id)
        return {"status": "success"}

    return router


def install_workspace_api(app: FastAPI, context: ApplicationContext) -> FastAPI:
    """Compatibility wrapper for extensions written before the app factory."""

    app.include_router(build_workspace_router(context))
    return app
