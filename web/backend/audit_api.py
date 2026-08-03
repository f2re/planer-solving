"""Administrative audit-log API."""
from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, Query

from src.operations_domain import AuthenticatedUser
from web.backend.app_context import ApplicationContext
from web.backend.auth import admin_dependency


def build_audit_router(context: ApplicationContext) -> APIRouter:
    router = APIRouter(tags=["audit"])
    admin = admin_dependency(context)

    @router.get("/api/audit")
    def list_audit(
        workspace_id: str | None = None,
        user_id: str | None = None,
        action: str | None = None,
        query: str | None = None,
        limit: int = Query(200, ge=1, le=500),
        offset: int = Query(0, ge=0),
        _: AuthenticatedUser = Depends(admin),
    ) -> List[Dict[str, Any]]:
        return context.operations.list_audit(
            workspace_id=workspace_id,
            user_id=user_id,
            action=action,
            query=query,
            limit=limit,
            offset=offset,
        )

    return router
