"""Local authentication, role policy and audit middleware."""
from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, FastAPI, Request, Response
from pydantic import BaseModel

from web.backend.app_context import ApplicationContext
from web.backend.errors import ApplicationError

SESSION_COOKIE = "planner_session"
ROLE_LEVEL = {"viewer": 1, "operator": 2, "admin": 3}


class LoginRequest(BaseModel):
    username: str
    password: str = ""


class BootstrapRequest(BaseModel):
    username: str = "admin"
    display_name: str = "Администратор"
    password: str = ""


class UserCreateRequest(BaseModel):
    username: str
    display_name: str
    password: str = ""
    role: str = "viewer"


class UserUpdateRequest(BaseModel):
    display_name: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None
    password: Optional[str] = None


class PasswordResetRequest(BaseModel):
    password: str = ""


def _model_dict(model: BaseModel, *, exclude_unset: bool = False) -> Dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(exclude_unset=exclude_unset)
    return model.dict(exclude_unset=exclude_unset)


def _json_response(status_code: int, detail: str, code: str) -> Response:
    return Response(
        content=json.dumps({"detail": detail, "code": code}, ensure_ascii=False),
        status_code=status_code,
        media_type="application/json",
    )


def actor_from_request(request: Request) -> Dict[str, Any]:
    actor = getattr(request.state, "actor", None)
    if not actor:
        raise ApplicationError(
            "Требуется вход в систему.",
            status_code=401,
            code="authentication_required",
        )
    return dict(actor)


def require_role(request: Request, role: str) -> Dict[str, Any]:
    actor = actor_from_request(request)
    if ROLE_LEVEL.get(str(actor.get("role")), 0) < ROLE_LEVEL[role]:
        raise ApplicationError(
            "Недостаточно прав для выполнения операции.",
            status_code=403,
            code="permission_denied",
        )
    return actor


def _required_role(method: str, path: str) -> Optional[str]:
    if not path.startswith("/api/"):
        return None
    if path in {
        "/api/health", "/api/system/version", "/api/auth/status",
        "/api/auth/login", "/api/auth/bootstrap",
    }:
        return None
    if path == "/api/auth/logout":
        return "viewer"
    if path.startswith("/api/admin/") or "/users" in path:
        return "admin"
    if method in {"GET", "HEAD", "OPTIONS"}:
        return "viewer"
    if path.endswith("/commit") and "/imports/" in path:
        return "admin"
    if path == "/api/workspaces/import":
        return "admin"
    if "/teachers" in path and method != "GET":
        return "admin"
    if path.startswith("/api/workspaces") and method == "DELETE":
        return "admin"
    if path == "/api/workspaces" and method == "POST":
        return "admin"
    return "operator"


def _cookie_kwargs() -> Dict[str, Any]:
    return {
        "httponly": True,
        "samesite": "lax",
        "secure": os.environ.get("PLANNER_COOKIE_SECURE", "0") == "1",
        "path": "/",
        "max_age": 14 * 24 * 60 * 60,
    }


def _origin_valid(request: Request) -> bool:
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return True
    origin = request.headers.get("origin")
    if not origin:
        return True
    host = request.headers.get("host")
    return origin.rstrip("/") in {f"http://{host}", f"https://{host}"}


def install_auth(app: FastAPI, context: ApplicationContext) -> None:
    store = context.workspace_repository

    @app.middleware("http")
    async def authentication_middleware(request: Request, call_next):
        if not _origin_valid(request):
            return _json_response(
                403,
                "Запрос отклонён: источник страницы не совпадает с сервером.",
                "origin_mismatch",
            )
        bootstrap_required = store.user_count() == 0
        actor: Optional[Dict[str, Any]] = None
        if bootstrap_required:
            actor = {
                "id": None,
                "username": "local-setup",
                "display_name": "Локальный администратор",
                "role": "admin",
                "bootstrap": True,
            }
        else:
            actor = store.session_user(request.cookies.get(SESSION_COOKIE, ""))
        request.state.actor = actor
        request.state.bootstrap_required = bootstrap_required
        required = _required_role(request.method, request.url.path)
        if required and not actor:
            return _json_response(401, "Требуется вход в систему.", "authentication_required")
        if required and ROLE_LEVEL.get(str(actor.get("role")), 0) < ROLE_LEVEL[required]:
            return _json_response(403, "Недостаточно прав для выполнения операции.", "permission_denied")
        response = await call_next(request)
        if (
            request.method not in {"GET", "HEAD", "OPTIONS"}
            and request.url.path.startswith("/api/")
            and not request.url.path.startswith("/api/auth/")
            and response.status_code < 400
        ):
            try:
                store.audit(
                    actor=actor,
                    action=f"http.{request.method.lower()}",
                    entity_type="api",
                    entity_id=None,
                    workspace_id=None,
                    summary=f"{request.method} {request.url.path}",
                    details={"status": response.status_code},
                )
            except Exception:
                pass
        return response


def build_auth_router(context: ApplicationContext) -> APIRouter:
    router = APIRouter(tags=["auth"])
    store = context.workspace_repository

    @router.get("/api/auth/status")
    def status(request: Request) -> Dict[str, Any]:
        actor = getattr(request.state, "actor", None)
        bootstrap_required = bool(getattr(request.state, "bootstrap_required", False))
        return {
            "authenticated": bool(actor and not actor.get("bootstrap")),
            "bootstrap_required": bootstrap_required,
            "setup_access": bool(actor),
            "user": actor,
            "password_policy": "none",
            "roles": [
                {"id": "admin", "name": "Администратор"},
                {"id": "operator", "name": "Оператор"},
                {"id": "viewer", "name": "Просмотр"},
            ],
        }

    @router.post("/api/auth/bootstrap")
    def bootstrap(payload: BootstrapRequest, response: Response) -> Dict[str, Any]:
        user = store.bootstrap_admin(payload.username, payload.display_name, payload.password)
        raw_token = store.create_session(user["id"])
        response.set_cookie(SESSION_COOKIE, raw_token, **_cookie_kwargs())
        store.audit(
            actor=user,
            action="auth.bootstrap",
            entity_type="user",
            entity_id=user["id"],
            summary="Создан первоначальный администратор",
        )
        return {"user": user}

    @router.post("/api/auth/login")
    def login(payload: LoginRequest, response: Response) -> Dict[str, Any]:
        user = store.authenticate(payload.username, payload.password)
        if not user:
            raise ApplicationError(
                "Неверный логин или пароль.",
                status_code=401,
                code="invalid_credentials",
            )
        raw_token = store.create_session(user["id"])
        response.set_cookie(SESSION_COOKIE, raw_token, **_cookie_kwargs())
        store.audit(
            actor=user,
            action="auth.login",
            entity_type="user",
            entity_id=user["id"],
            summary="Вход в систему",
        )
        return {"user": user}

    @router.post("/api/auth/logout")
    def logout(request: Request, response: Response) -> Dict[str, str]:
        actor = actor_from_request(request)
        store.delete_session(request.cookies.get(SESSION_COOKIE, ""))
        response.delete_cookie(SESSION_COOKIE, path="/")
        store.audit(
            actor=actor,
            action="auth.logout",
            entity_type="user",
            entity_id=actor.get("id"),
            summary="Выход из системы",
        )
        return {"status": "success"}

    @router.get("/api/auth/me")
    def me(request: Request) -> Dict[str, Any]:
        return {"user": actor_from_request(request)}

    @router.get("/api/admin/users")
    def list_users(request: Request) -> Dict[str, Any]:
        require_role(request, "admin")
        return {"users": store.list_users()}

    @router.post("/api/admin/users")
    def create_user(payload: UserCreateRequest, request: Request) -> Dict[str, Any]:
        actor = require_role(request, "admin")
        user = store.create_user(_model_dict(payload))
        store.audit(
            actor=actor,
            action="user.create",
            entity_type="user",
            entity_id=user["id"],
            summary=f"Создан пользователь «{user['display_name']}»",
            details={"role": user["role"]},
        )
        return user

    @router.put("/api/admin/users/{user_id}")
    def update_user(user_id: str, payload: UserUpdateRequest, request: Request) -> Dict[str, Any]:
        actor = require_role(request, "admin")
        values = _model_dict(payload, exclude_unset=True)
        if values.get("password") is None:
            values.pop("password", None)
        user = store.update_user(user_id, values)
        store.audit(
            actor=actor,
            action="user.update",
            entity_type="user",
            entity_id=user_id,
            summary=f"Изменён пользователь «{user['display_name']}»",
            details={"role": user["role"], "is_active": bool(user["is_active"])},
        )
        return user

    @router.post("/api/admin/users/{user_id}/reset-password")
    def reset_password(
        user_id: str,
        payload: PasswordResetRequest,
        request: Request,
    ) -> Dict[str, Any]:
        actor = require_role(request, "admin")
        user = store.reset_user_password(user_id, payload.password)
        store.audit(
            actor=actor,
            action="user.password_reset",
            entity_type="user",
            entity_id=user_id,
            summary=f"Сброшен пароль пользователя «{user['display_name']}»",
            details={"empty_password": payload.password == ""},
        )
        return user

    return router
