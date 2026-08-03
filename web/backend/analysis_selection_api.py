"""Persist the operator's chosen template candidate in an analysis session."""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from src.operations_domain import AuthenticatedUser
from web.backend.app_context import ApplicationContext
from web.backend.auth import operator_dependency
from web.backend.errors import ApplicationError


class CandidateSelectionRequest(BaseModel):
    candidate_key: str


def build_analysis_selection_router(context: ApplicationContext) -> APIRouter:
    router = APIRouter(tags=["analysis"])
    operator = operator_dependency(context)

    @router.post("/api/analysis/{session_id}/files/{file_id}/select-template")
    def select_template_candidate(
        session_id: str,
        file_id: str,
        payload: CandidateSelectionRequest,
        _: AuthenticatedUser = Depends(operator),
    ) -> Dict[str, Any]:
        manifest = context.sessions.load_manifest(session_id)
        item = context.sessions.manifest_file(manifest, file_id)
        match = item.get("template_match") or {}
        candidates = match.get("candidates") or []
        selected = next(
            (
                candidate for candidate in candidates
                if candidate.get("candidate_key") == payload.candidate_key
            ),
            None,
        )
        if not selected:
            raise ApplicationError("Выбранный вариант разметки больше не доступен.")
        match["selected"] = {
            key: selected.get(key)
            for key in (
                "candidate_key", "source", "name", "template_id",
                "template_revision_id", "component_id", "component_label",
                "score", "quality_percent", "fingerprint_similarity",
                "metrics", "reasons", "layout", "usable",
            )
        }
        item["template_match"] = match
        context.sessions.save_manifest(session_id, manifest)
        return match["selected"]

    return router
