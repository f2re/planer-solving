"""Compatibility exports for workspace domain rules.

The JSON repository was removed in version 2.5. Runtime persistence is provided
only by :class:`src.sqlite_workspace_store.SQLiteWorkspaceStore`. New code should
import these symbols from :mod:`src.workspace_domain` directly.
"""
from .workspace_domain import (
    COLOR_RE,
    DEFAULT_COLOR,
    DEFAULT_SETTINGS,
    WorkspaceError,
    WorkspaceNotFound,
    color,
    default_semester_settings,
    normalize_teacher,
    normalize_template,
    now,
    teacher_key,
    text,
    unique_name,
)

__all__ = [
    "COLOR_RE",
    "DEFAULT_COLOR",
    "DEFAULT_SETTINGS",
    "WorkspaceError",
    "WorkspaceNotFound",
    "color",
    "default_semester_settings",
    "normalize_teacher",
    "normalize_template",
    "now",
    "teacher_key",
    "text",
    "unique_name",
]
