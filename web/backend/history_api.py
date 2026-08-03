"""Processing history, preserved artifacts and repeatable operator sessions."""
from __future__ import annotations

from pathlib import Path
import shutil
from typing import Any, Dict, List
import uuid

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse

from src.operations_domain import AuthenticatedUser, PermissionDenied
from web.backend.app_context import ApplicationContext
from web.backend.auth import operator_dependency, viewer_dependency
from web.backend.schemas import AnalysisFile, AnalyzeResponse


def build_history_router(context: ApplicationContext) -> APIRouter:
    router = APIRouter(tags=["history"])
    viewer = viewer_dependency(context)
    operator = operator_dependency(context)

    @router.get("/api/workspaces/{workspace_id}/history")
    def list_history(
        workspace_id: str,
        status: str | None = None,
        query: str | None = None,
        limit: int = Query(100, ge=1, le=300),
        offset: int = Query(0, ge=0),
        _: AuthenticatedUser = Depends(viewer),
    ) -> List[Dict[str, Any]]:
        return context.operations.list_processing_runs(
            workspace_id=workspace_id,
            status=status,
            query=query,
            limit=limit,
            offset=offset,
        )

    @router.get("/api/history/{run_id}")
    def history_detail(
        run_id: str,
        user: AuthenticatedUser = Depends(viewer),
    ) -> Dict[str, Any]:
        return context.operations.get_processing_run(run_id)

    @router.get("/api/history/artifacts/{artifact_id}")
    def download_history_artifact(
        artifact_id: str,
        _: AuthenticatedUser = Depends(viewer),
    ) -> FileResponse:
        artifact = context.operations.get_processing_artifact(artifact_id)
        path = Path(artifact["stored_path"]).resolve()
        history_root = context.paths.history_root.resolve()
        if history_root not in path.parents or not path.is_file():
            raise PermissionDenied("Файл истории отсутствует или находится вне хранилища.")
        return FileResponse(
            path=str(path),
            filename=artifact["filename"],
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    @router.post("/api/history/{run_id}/reopen", response_model=AnalyzeResponse)
    def reopen_history(
        run_id: str,
        _: AuthenticatedUser = Depends(operator),
    ) -> AnalyzeResponse:
        run = context.operations.get_processing_run(run_id)
        session_id, session_dir = context.sessions.create()
        manifest_files: List[Dict[str, Any]] = []
        response_files: List[AnalysisFile] = []
        for historical in run.get("files", []):
            source = Path(historical["source_path"]).resolve()
            if context.paths.history_root.resolve() not in source.parents or not source.is_file():
                continue
            extension = source.suffix.lower() or ".xlsx"
            file_id = str(uuid.uuid4())
            stored_name = f"{file_id}{extension}"
            shutil.copy2(source, session_dir / stored_name)
            analysis = dict(historical.get("analysis") or {})
            if historical.get("layout"):
                analysis["layout"] = historical["layout"]
            item = {
                "file_id": file_id,
                "filename": historical["original_name"],
                "group_name": historical["group_name"],
                "stored_name": stored_name,
                "status": "warning",
                "message": "Восстановлено из истории; выполните контрольную проверку.",
                "analysis": analysis,
                "history_run_id": run_id,
                "template_match": {
                    "selected": {
                        "template_id": historical.get("template_id"),
                        "template_revision_id": historical.get("template_revision_id"),
                        "component_id": historical.get("component_id"),
                    }
                },
            }
            manifest_files.append(item)
            response_files.append(AnalysisFile(
                file_id=file_id,
                filename=item["filename"],
                group_name=item["group_name"],
                status=item["status"],
                message=item["message"],
                analysis=analysis,
            ))
        manifest = {
            "session_id": session_id,
            "created_at": run.get("started_at"),
            "files": manifest_files,
            "reopened_from_run_id": run_id,
        }
        context.sessions.save_manifest(session_id, manifest)
        return AnalyzeResponse(session_id=session_id, files=response_files)

    return router
