"""Authentication bootstrap, login and local user administration."""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field

from src.operations_domain import AuthenticatedUser
from web.backend.app_context import ApplicationContext
from web.backend.auth import SESSION_COOKIE, admin_dependency, optional_user, viewer_dependency


class BootstrapRequest(BaseModel):
    username: str = Field(min_length=3, max_length=80)
    display_name: str = Field(min_length=1, max_length=160)
    password: str = Field(min_length=10, max_length=512)


class LoginRequest(BaseModel):
    username: str
    password: str


class UserCreateRequest(BaseModel):
    username: str = Field(min_length=3, max_length=80)
    display_name: str = Field(min_length=1, max_length=160)
    password: str = Field(min_length=10, max_length=512)
    role: str


class UserUpdateRequest(BaseModel):
    display_name: Optional[str] = Field(default=None, min_length=1, max_length=160)
    password: Optional[str] = Field(default=None, min_length=10, max_length=512)
    role: Optional[str] = None
    active: Optional[bool] = None


def _secure_cookie() -> bool:
    return os.environ.get("PLANNER_SECURE_COOKIE", "").strip().lower() in {"1", "true", "yes"}


def _set_session_cookie(response: Response, session_id: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        session_id,
        httponly=True,
        secure=_secure_cookie(),
        samesite="strict",
        max_age=16 * 60 * 60,
        path="/",
    )


def _session_payload(session: Dict[str, Any]) -> Dict[str, Any]:
    user = dict(session["user"])
    user["role_label"] = {
        "admin": "Администратор",
        "operator": "Оператор",
        "viewer": "Просмотр",
    }.get(user.get("role"), user.get("role"))
    return {
        "authenticated": True,
        "setup_required": False,
        "user": user,
        "csrf_token": session["csrf_token"],
        "expires_at": session["expires_at"],
    }


def build_auth_router(context: ApplicationContext) -> APIRouter:
    router = APIRouter(prefix="/api/auth", tags=["auth"])
    optional = optional_user(context)
    viewer = viewer_dependency(context)
    admin = admin_dependency(context)

    @router.get("/status")
    def status(request: Request) -> Dict[str, Any]:
        setup_required = context.operations.user_count() == 0
        user = context.operations.session_user(request.cookies.get(SESSION_COOKIE))
        return {
            "authenticated": user is not None,
            "setup_required": setup_required,
            "user": user.to_dict() if user else None,
            "csrf_token": user.csrf_token if user else None,
        }

    @router.post("/bootstrap")
    def bootstrap(payload: BootstrapRequest, response: Response) -> Dict[str, Any]:
        user = context.operations.bootstrap_admin(
            payload.username,
            payload.display_name,
            payload.password,
        )
        session = context.operations.create_session(user["id"])
        _set_session_cookie(response, session["session_id"])
        return _session_payload(session)

    @router.post("/login")
    def login(payload: LoginRequest, response: Response) -> Dict[str, Any]:
        user = context.operations.authenticate(payload.username, payload.password)
        session = context.operations.create_session(user["id"])
        _set_session_cookie(response, session["session_id"])
        context.operations.record_audit(
            user_id=user["id"],
            action="login",
            entity_type="session",
            entity_id=None,
            workspace_id=None,
            summary=f"Пользователь {user['display_name']} вошёл в систему.",
        )
        return _session_payload(session)

    @router.post("/logout")
    def logout(
        request: Request,
        response: Response,
        user: AuthenticatedUser = Depends(viewer),
    ) -> Dict[str, str]:
        context.operations.revoke_session(request.cookies.get(SESSION_COOKIE))
        response.delete_cookie(SESSION_COOKIE, path="/")
        context.operations.record_audit(
            user_id=user.id,
            action="logout",
            entity_type="session",
            entity_id=None,
            workspace_id=None,
            summary=f"Пользователь {user.display_name} вышел из системы.",
        )
        return {"status": "success"}

    @router.get("/users", response_model=List[Dict[str, Any]])
    def list_users(_: AuthenticatedUser = Depends(admin)) -> List[Dict[str, Any]]:
        return context.operations.list_users()

    @router.post("/users")
    def create_user(
        payload: UserCreateRequest,
        actor: AuthenticatedUser = Depends(admin),
    ) -> Dict[str, Any]:
        return context.operations.create_user(
            username=payload.username,
            display_name=payload.display_name,
            password=payload.password,
            role=payload.role,
            actor_user_id=actor.id,
        )

    @router.put("/users/{user_id}")
    def update_user(
        user_id: str,
        payload: UserUpdateRequest,
        actor: AuthenticatedUser = Depends(admin),
    ) -> Dict[str, Any]:
        values = payload.model_dump(exclude_unset=True) if hasattr(payload, "model_dump") else payload.dict(exclude_unset=True)
        return context.operations.update_user(user_id, values, actor.id)

    return router
