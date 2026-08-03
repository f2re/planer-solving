"""Domain types and errors for authentication, imports and operation history."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable

ROLE_ADMIN = "admin"
ROLE_OPERATOR = "operator"
ROLE_VIEWER = "viewer"
ROLES = {ROLE_ADMIN, ROLE_OPERATOR, ROLE_VIEWER}
ROLE_LABELS = {
    ROLE_ADMIN: "Администратор",
    ROLE_OPERATOR: "Оператор",
    ROLE_VIEWER: "Просмотр",
}


class OperationsError(ValueError):
    """Base error for a user-correctable operational action."""


class AuthenticationRequired(OperationsError):
    pass


class SetupRequired(OperationsError):
    pass


class PermissionDenied(OperationsError):
    pass


class InvalidCredentials(OperationsError):
    pass


class ImportJobNotFound(OperationsError):
    pass


class ProcessingRunNotFound(OperationsError):
    pass


class RevisionNotFound(OperationsError):
    pass


@dataclass(frozen=True)
class AuthenticatedUser:
    id: str
    username: str
    display_name: str
    role: str
    csrf_token: str

    @property
    def role_label(self) -> str:
        return ROLE_LABELS.get(self.role, self.role)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "username": self.username,
            "display_name": self.display_name,
            "role": self.role,
            "role_label": self.role_label,
        }


def validate_role(role: str) -> str:
    normalized = str(role or "").strip().lower()
    if normalized not in ROLES:
        raise OperationsError("Неизвестная роль пользователя.")
    return normalized


def can_access(role: str, allowed: Iterable[str]) -> bool:
    return role in set(allowed)
