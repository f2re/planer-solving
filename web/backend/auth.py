"""Cookie authentication, CSRF verification and role dependencies."""
from __future__ import annotations

from typing import Callable, Iterable, Optional

from fastapi import Depends, Request

from src.operations_domain import (
    AuthenticatedUser,
    AuthenticationRequired,
    PermissionDenied,
    SetupRequired,
    can_access,
)
from web.backend.app_context import ApplicationContext

SESSION_COOKIE = "planner_session"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def optional_user(context: ApplicationContext) -> Callable[[Request], Optional[AuthenticatedUser]]:
    def dependency(request: Request) -> Optional[AuthenticatedUser]:
        return context.operations.session_user(request.cookies.get(SESSION_COOKIE))
    return dependency


def require_roles(
    context: ApplicationContext,
    *roles: str,
) -> Callable[[Request], AuthenticatedUser]:
    allowed = tuple(roles)

    def dependency(request: Request) -> AuthenticatedUser:
        if context.operations.user_count() == 0:
            raise SetupRequired("Сначала создайте первоначального администратора.")
        user = context.operations.session_user(request.cookies.get(SESSION_COOKIE))
        if user is None:
            raise AuthenticationRequired("Требуется вход в систему.")
        if allowed and not can_access(user.role, allowed):
            raise PermissionDenied("Недостаточно прав для выполнения действия.")
        if request.method.upper() not in SAFE_METHODS:
            supplied = request.headers.get("X-CSRF-Token", "")
            if not supplied or supplied != user.csrf_token:
                raise PermissionDenied("Защитный токен запроса устарел. Обновите страницу.")
        return user

    return dependency


def viewer_dependency(context: ApplicationContext):
    return require_roles(context, "viewer", "operator", "admin")


def operator_dependency(context: ApplicationContext):
    return require_roles(context, "operator", "admin")


def admin_dependency(context: ApplicationContext):
    return require_roles(context, "admin")
