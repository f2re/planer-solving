"""Workspace API for concise teacher assignment preferences."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from src.teacher_assignment_rules import (
    list_teacher_assignment_rules,
    replace_teacher_assignment_rules,
)
from web.backend.app_context import ApplicationContext
from web.backend.auth import actor_from_request


class TeacherAssignmentRulePayload(BaseModel):
    subject: str = Field(min_length=1, max_length=300)
    lecturer: Optional[str] = Field(default="", max_length=200)
    practice: Optional[str] = Field(default="", max_length=200)
    reserve: Optional[str] = Field(default="", max_length=200)


class TeacherAssignmentRulesPayload(BaseModel):
    rules: List[TeacherAssignmentRulePayload] = Field(default_factory=list, max_length=2000)


def _model_dict(model: BaseModel) -> Dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model.dict()


def build_teacher_assignment_router(context: ApplicationContext) -> APIRouter:
    router = APIRouter(tags=["teacher-assignments"])
    repository = context.workspace_repository

    @router.get("/api/workspaces/{workspace_id}/teacher-assignment-rules")
    def list_rules(workspace_id: str) -> Dict[str, Any]:
        items = list_teacher_assignment_rules(repository, workspace_id)
        return {"workspace_id": workspace_id, "items": items, "count": len(items)}

    @router.put("/api/workspaces/{workspace_id}/teacher-assignment-rules")
    def replace_rules(
        workspace_id: str,
        payload: TeacherAssignmentRulesPayload,
        request: Request,
    ) -> Dict[str, Any]:
        actor = actor_from_request(request)
        items = replace_teacher_assignment_rules(
            repository,
            workspace_id,
            [_model_dict(item) for item in payload.rules],
        )
        repository.audit(
            actor=actor,
            action="teacher_assignment_rules.replace",
            entity_type="teacher_assignment_rules",
            entity_id=workspace_id,
            workspace_id=workspace_id,
            summary=f"Обновлены правила назначения преподавателей: {len(items)} дисциплин",
            details={"rule_count": len(items)},
        )
        return {"workspace_id": workspace_id, "items": items, "count": len(items)}

    return router
