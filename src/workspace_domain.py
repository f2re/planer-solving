"""Domain rules shared by workspace repositories and APIs."""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timezone
import re
from typing import Any, Dict, Iterable, Optional
import uuid

DEFAULT_COLOR = "#315EFB"
COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


class WorkspaceError(ValueError):
    """A user-correctable workspace-domain violation."""


class WorkspaceNotFound(WorkspaceError):
    """Requested workspace entity does not exist."""


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def default_semester_settings(reference: Optional[date] = None) -> Dict[str, str]:
    """Return a useful academic-semester range without a hard-coded year."""

    current = reference or date.today()
    if current.month <= 6:
        start = date(current.year, 2, 1)
        end = date(current.year, 6, 30)
    else:
        start = date(current.year, 9, 1)
        end = date(current.year + 1, 1, 31)
    return {
        "schedule_start_date": start.isoformat(),
        "schedule_end_date": end.isoformat(),
    }


DEFAULT_SETTINGS = default_semester_settings()


def text(value: Any, limit: int = 300) -> str:
    return str(value or "").strip()[:limit]


def color(value: Any) -> str:
    normalized = text(value, 7).upper()
    return normalized if COLOR_RE.fullmatch(normalized) else DEFAULT_COLOR


def unique_name(name: str, existing: Iterable[str]) -> str:
    used = {item.casefold() for item in existing}
    base = name.strip() or "Новое пространство"
    if base.casefold() not in used:
        return base
    index = 2
    while f"{base} ({index})".casefold() in used:
        index += 1
    return f"{base} ({index})"


def teacher_key(item: Dict[str, Any]) -> str:
    value = text(item.get("full_name"), 200) or text(item.get("short_name"), 120)
    return value.casefold().replace("ё", "е")


def normalize_teacher(item: Dict[str, Any], teacher_id: int) -> Dict[str, Any]:
    short_name = text(item.get("short_name"), 120)
    full_name = text(item.get("full_name"), 200)
    short_name, full_name = short_name or full_name, full_name or short_name
    if not short_name:
        raise WorkspaceError("У преподавателя не задано имя.")
    try:
        normalized_id = int(teacher_id)
    except (TypeError, ValueError) as exc:
        raise WorkspaceError("Некорректный идентификатор преподавателя.") from exc
    if normalized_id < 1:
        raise WorkspaceError("Идентификатор преподавателя должен быть положительным.")
    return {
        "id": normalized_id,
        "short_name": short_name,
        "full_name": full_name,
        "position": text(item.get("position"), 160),
        "rank": text(item.get("rank"), 160),
        "academic_degree": text(item.get("academic_degree"), 160),
    }


def normalize_template(
    item: Dict[str, Any],
    template_id: Optional[str] = None,
) -> Dict[str, Any]:
    name = text(item.get("name"), 160)
    if not name:
        raise WorkspaceError("У шаблона не задано название.")
    if not isinstance(item.get("layout"), dict):
        raise WorkspaceError(f"Шаблон «{name}» не содержит разметку.")
    stamp = now()
    return {
        "id": template_id or text(item.get("id"), 64) or str(uuid.uuid4()),
        "name": name,
        "description": text(item.get("description"), 1000),
        "layout": deepcopy(item["layout"]),
        "created_at": text(item.get("created_at"), 64) or stamp,
        "updated_at": stamp,
    }
