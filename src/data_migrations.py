"""Versioned, transactional migrations for Planner Solving persistent data."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple
import uuid

from .workspace_domain import DEFAULT_COLOR, default_semester_settings

CURRENT_SCHEMA_VERSION = 1
DEFAULT_SETTINGS = default_semester_settings()
MAIN_WORKSPACE_NAME = "Основное пространство"


class MigrationError(RuntimeError):
    """Raised when stored data cannot be migrated safely."""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _text(value: Any, limit: int = 300) -> str:
    return str(value or "").strip()[:limit]


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as exc:
        raise MigrationError(f"Не удалось прочитать {path}: {exc}") from exc


def atomic_json_write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _normalized_teacher(source: Dict[str, Any], teacher_id: int) -> Optional[Dict[str, Any]]:
    short_name = _text(source.get("short_name"), 120)
    full_name = _text(source.get("full_name"), 200)
    short_name, full_name = short_name or full_name, full_name or short_name
    if not short_name:
        return None
    return {
        "id": teacher_id,
        "short_name": short_name,
        "full_name": full_name,
        "position": _text(source.get("position"), 160),
        "rank": _text(source.get("rank"), 160),
        "academic_degree": _text(source.get("academic_degree"), 160),
    }


def _teacher_identity(source: Dict[str, Any]) -> str:
    value = _text(source.get("full_name"), 200) or _text(source.get("short_name"), 120)
    return value.casefold().replace("ё", "е")


def _workspace_from_teachers(teachers: List[Dict[str, Any]]) -> Dict[str, Any]:
    stamp = utc_now()
    normalized: List[Dict[str, Any]] = []
    for index, item in enumerate(teachers, 1):
        if not isinstance(item, dict):
            continue
        teacher = _normalized_teacher(item, index)
        if teacher:
            normalized.append(teacher)
    return {
        "id": str(uuid.uuid4()),
        "name": MAIN_WORKSPACE_NAME,
        "color": DEFAULT_COLOR,
        "description": "Создано миграцией из прежнего списка преподавателей.",
        "created_at": stamp,
        "updated_at": stamp,
        "teachers": normalized,
        "templates": [],
        "settings": default_semester_settings(),
    }


def _legacy_owner_workspace(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    workspaces = payload.get("workspaces")
    if not isinstance(workspaces, list):
        return None
    valid = [item for item in workspaces if isinstance(item, dict) and _text(item.get("id"), 64)]
    if not valid:
        return None
    named_main = next(
        (
            item for item in valid
            if _text(item.get("name"), 160).casefold() == MAIN_WORKSPACE_NAME.casefold()
        ),
        None,
    )
    if named_main:
        return named_main
    requested_default = _text(payload.get("default_workspace_id"), 64)
    explicit_default = next(
        (item for item in valid if _text(item.get("id"), 64) == requested_default),
        None,
    )
    return explicit_default or valid[0]


def _merge_legacy_teachers(workspace: Dict[str, Any], candidates: Iterable[Dict[str, Any]]) -> None:
    existing = [deepcopy(item) for item in workspace.get("teachers") or [] if isinstance(item, dict)]
    identities = {_teacher_identity(item) for item in existing if _teacher_identity(item)}
    used_ids = {
        int(item["id"])
        for item in existing
        if isinstance(item.get("id"), int) and int(item["id"]) > 0
    }
    next_id = max(used_ids, default=0) + 1
    for raw in candidates:
        if not isinstance(raw, dict):
            continue
        identity = _teacher_identity(raw)
        if not identity or identity in identities:
            continue
        requested_id = raw.get("id")
        teacher_id = requested_id if isinstance(requested_id, int) and requested_id > 0 else next_id
        if teacher_id in used_ids:
            teacher_id = next_id
            while teacher_id in used_ids:
                teacher_id += 1
        teacher = _normalized_teacher(raw, teacher_id)
        if not teacher:
            continue
        existing.append(teacher)
        identities.add(identity)
        used_ids.add(teacher_id)
        next_id = max(next_id, teacher_id + 1)
    workspace["teachers"] = existing


def _merge_legacy_templates(workspace: Dict[str, Any], candidates: Iterable[Dict[str, Any]]) -> None:
    existing = [deepcopy(item) for item in workspace.get("templates") or [] if isinstance(item, dict)]
    names = {_text(item.get("name"), 160).casefold() for item in existing if _text(item.get("name"), 160)}
    ids = {_text(item.get("id"), 64) for item in existing if _text(item.get("id"), 64)}
    stamp = utc_now()
    for raw in candidates:
        if not isinstance(raw, dict):
            continue
        name = _text(raw.get("name"), 160)
        if not name or name.casefold() in names or not isinstance(raw.get("layout"), dict):
            continue
        item = deepcopy(raw)
        template_id = _text(item.get("id"), 64)
        if not template_id or template_id in ids:
            template_id = str(uuid.uuid4())
        item["id"] = template_id
        item["name"] = name
        item["description"] = _text(item.get("description"), 1000)
        item["created_at"] = _text(item.get("created_at"), 64) or stamp
        item["updated_at"] = _text(item.get("updated_at"), 64) or stamp
        existing.append(item)
        names.add(name.casefold())
        ids.add(template_id)
    workspace["templates"] = existing


def _canonicalize_legacy_ownership(
    payload: Dict[str, Any],
    legacy_teachers: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Attach every pre-workspace record to one deterministic workspace only.

    Historical builds could have top-level teachers/templates without an
    explicit workspace. Such records are never copied into every workspace. If
    a workspace named ``Основное пространство`` exists, it owns legacy data.
    Otherwise the valid default workspace is used, then the first valid
    workspace as a final recovery fallback.
    """

    result = deepcopy(payload)
    owner = _legacy_owner_workspace(result)
    if owner is None:
        return result

    valid_ids = {
        _text(item.get("id"), 64)
        for item in result.get("workspaces") or []
        if isinstance(item, dict) and _text(item.get("id"), 64)
    }
    if _text(result.get("default_workspace_id"), 64) not in valid_ids:
        result["default_workspace_id"] = _text(owner.get("id"), 64)

    teacher_candidates: List[Dict[str, Any]] = []
    if isinstance(result.get("teachers"), list):
        teacher_candidates.extend(item for item in result["teachers"] if isinstance(item, dict))
    teacher_candidates.extend(item for item in (legacy_teachers or []) if isinstance(item, dict))
    if teacher_candidates:
        _merge_legacy_teachers(owner, teacher_candidates)

    template_candidates: List[Dict[str, Any]] = []
    for key in ("templates", "layout_profiles"):
        if isinstance(result.get(key), list):
            template_candidates.extend(item for item in result[key] if isinstance(item, dict))
    if template_candidates:
        _merge_legacy_templates(owner, template_candidates)

    # Top-level collections are legacy/global representations. Keeping them
    # after migration would re-introduce an ambiguous "visible everywhere"
    # interpretation, so the canonical document contains only workspace-owned
    # collections.
    result.pop("teachers", None)
    result.pop("templates", None)
    result.pop("layout_profiles", None)
    return result


def detect_schema_version(payload: Any) -> int:
    """Return zero for supported legacy documents without an explicit version."""
    if payload is None or isinstance(payload, list):
        return 0
    if not isinstance(payload, dict):
        raise MigrationError("Файл данных должен содержать JSON-объект или прежний список преподавателей.")
    raw_version = payload.get("version", 0)
    if isinstance(raw_version, bool) or not isinstance(raw_version, int) or raw_version < 0:
        raise MigrationError("Поле version в файле данных имеет недопустимое значение.")
    return raw_version


def migrate_0_to_1(
    payload: Any,
    legacy_teachers: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Convert legacy teachers or unversioned workspace documents to schema v1."""
    if isinstance(payload, list):
        workspace = _workspace_from_teachers(payload)
        return {
            "version": 1,
            "default_workspace_id": workspace["id"],
            "workspaces": [workspace],
        }

    if isinstance(payload, dict) and isinstance(payload.get("workspaces"), list):
        migrated = deepcopy(payload)
        migrated["version"] = 1
        if not migrated.get("default_workspace_id") and migrated["workspaces"]:
            owner = _legacy_owner_workspace(migrated)
            if owner is not None:
                migrated["default_workspace_id"] = _text(owner.get("id"), 64)
        return migrated

    workspace = _workspace_from_teachers(legacy_teachers or [])
    return {
        "version": 1,
        "default_workspace_id": workspace["id"],
        "workspaces": [workspace],
    }


MIGRATIONS: Dict[
    int,
    Callable[[Any, Optional[List[Dict[str, Any]]]], Dict[str, Any]],
] = {
    0: migrate_0_to_1,
}


def validate_document(payload: Any) -> None:
    if not isinstance(payload, dict):
        raise MigrationError("После миграции корневое значение не является объектом.")
    version = detect_schema_version(payload)
    if version != CURRENT_SCHEMA_VERSION:
        raise MigrationError(
            f"После миграции получена версия {version}, ожидалась {CURRENT_SCHEMA_VERSION}."
        )
    workspaces = payload.get("workspaces")
    if not isinstance(workspaces, list) or not workspaces:
        raise MigrationError("После миграции отсутствуют рабочие пространства.")
    ids = {
        _text(item.get("id"), 64)
        for item in workspaces
        if isinstance(item, dict) and _text(item.get("id"), 64)
    }
    if not ids:
        raise MigrationError("После миграции пространства не имеют идентификаторов.")
    if _text(payload.get("default_workspace_id"), 64) not in ids:
        raise MigrationError("Основное пространство не найдено среди сохранённых пространств.")
    for key in ("teachers", "templates", "layout_profiles"):
        if key in payload:
            raise MigrationError(
                f"После миграции поле {key} осталось вне пространства; принадлежность данных неоднозначна."
            )


def migrate_document(
    payload: Any,
    *,
    target_version: int = CURRENT_SCHEMA_VERSION,
    legacy_teachers: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[Dict[str, Any], List[str]]:
    version = detect_schema_version(payload)
    source_version = version
    if version > target_version:
        raise MigrationError(
            f"Данные имеют версию {version}, которая новее поддерживаемой {target_version}. "
            "Установите более новую версию приложения."
        )
    result = deepcopy(payload)
    applied: List[str] = []
    while version < target_version:
        migration = MIGRATIONS.get(version)
        if migration is None:
            raise MigrationError(f"Не найдена миграция данных с версии {version}.")
        result = migration(result, legacy_teachers)
        next_version = detect_schema_version(result)
        if next_version <= version:
            raise MigrationError(f"Миграция версии {version} не повысила номер схемы.")
        applied.append(f"{version}->{next_version}")
        version = next_version

    # teachers.json is a genuine legacy source only while converting schema 0.
    # In schema 1 it is merely a compatibility mirror of the current default
    # workspace and must never be re-imported into another workspace.
    external_legacy_teachers = legacy_teachers if source_version == 0 else None
    canonical = _canonicalize_legacy_ownership(result, external_legacy_teachers)
    if canonical != result:
        applied.append("legacy->main-workspace")
    result = canonical
    validate_document(result)
    return result, applied


def create_backup(
    source: Path,
    backup_dir: Path,
    label: str = "before-migration",
) -> Optional[Path]:
    if not source.exists():
        return None
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    destination = backup_dir / f"{source.stem}.{label}.{stamp}{source.suffix}"
    counter = 2
    while destination.exists():
        destination = backup_dir / f"{source.stem}.{label}.{stamp}-{counter}{source.suffix}"
        counter += 1
    shutil.copy2(source, destination)
    return destination


def migrate_file(
    path: Path,
    *,
    legacy_teachers_path: Optional[Path] = None,
    backup_dir: Optional[Path] = None,
    dry_run: bool = False,
    target_version: int = CURRENT_SCHEMA_VERSION,
) -> Dict[str, Any]:
    path = Path(path)
    original = _read_json(path)
    legacy_teachers: List[Dict[str, Any]] = []
    if legacy_teachers_path:
        legacy = _read_json(Path(legacy_teachers_path))
        if isinstance(legacy, list):
            legacy_teachers = [item for item in legacy if isinstance(item, dict)]

    source_version = detect_schema_version(original)
    migrated, applied = migrate_document(
        original,
        target_version=target_version,
        legacy_teachers=legacy_teachers,
    )
    changed = original != migrated
    backup: Optional[Path] = None
    if changed and not dry_run:
        if backup_dir:
            backup = create_backup(path, Path(backup_dir))
        atomic_json_write(path, migrated)

    return {
        "path": str(path),
        "from_version": source_version,
        "to_version": target_version,
        "changed": changed,
        "dry_run": dry_run,
        "applied": applied,
        "backup": str(backup) if backup else None,
        "workspace_count": len(migrated.get("workspaces", [])),
    }
