"""Atomic storage for isolated workspaces, teachers and layout templates."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from typing import Any, Dict, Iterable, List, Optional
import uuid

DEFAULT_COLOR = "#315EFB"
DEFAULT_SETTINGS = {"schedule_start_date": "2026-02-10", "schedule_end_date": "2026-06-30"}
COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


class WorkspaceError(ValueError):
    pass


class WorkspaceNotFound(WorkspaceError):
    pass


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def text(value: Any, limit: int = 300) -> str:
    return str(value or "").strip()[:limit]


def color(value: Any) -> str:
    value = text(value, 7).upper()
    return value if COLOR_RE.fullmatch(value) else DEFAULT_COLOR


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
    return (text(item.get("full_name"), 200) or text(item.get("short_name"), 120)).casefold().replace("ё", "е")


def normalize_teacher(item: Dict[str, Any], teacher_id: int) -> Dict[str, Any]:
    short_name = text(item.get("short_name"), 120)
    full_name = text(item.get("full_name"), 200)
    short_name, full_name = short_name or full_name, full_name or short_name
    if not short_name:
        raise WorkspaceError("У преподавателя не задано имя.")
    return {
        "id": int(teacher_id), "short_name": short_name, "full_name": full_name,
        "position": text(item.get("position"), 160), "rank": text(item.get("rank"), 160),
        "academic_degree": text(item.get("academic_degree"), 160),
    }


def normalize_template(item: Dict[str, Any], template_id: Optional[str] = None) -> Dict[str, Any]:
    name = text(item.get("name"), 160)
    if not name:
        raise WorkspaceError("У шаблона не задано название.")
    if not isinstance(item.get("layout"), dict):
        raise WorkspaceError(f"Шаблон «{name}» не содержит разметку.")
    stamp = now()
    return {
        "id": template_id or text(item.get("id"), 64) or str(uuid.uuid4()),
        "name": name, "description": text(item.get("description"), 1000),
        "layout": deepcopy(item["layout"]),
        "created_at": text(item.get("created_at"), 64) or stamp,
        "updated_at": stamp,
    }


class WorkspaceStore:
    def __init__(self, path: Path, legacy_teachers_path: Optional[Path] = None):
        self.path = Path(path)
        self.legacy = Path(legacy_teachers_path) if legacy_teachers_path else None

    def _legacy_teachers(self) -> List[Dict[str, Any]]:
        try:
            data = json.loads(self.legacy.read_text(encoding="utf-8")) if self.legacy and self.legacy.exists() else []
        except (OSError, json.JSONDecodeError):
            data = []
        return data if isinstance(data, list) else []

    def _new_workspace(self, teachers: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        stamp = now()
        normalized = []
        for index, item in enumerate(teachers or [], 1):
            try:
                normalized.append(normalize_teacher(item, index))
            except WorkspaceError:
                pass
        return {
            "id": str(uuid.uuid4()), "name": "Основное пространство", "color": DEFAULT_COLOR,
            "description": "Создано автоматически из существующего списка преподавателей.",
            "created_at": stamp, "updated_at": stamp, "teachers": normalized, "templates": [],
            "settings": deepcopy(DEFAULT_SETTINGS),
        }

    def _initial(self) -> Dict[str, Any]:
        workspace = self._new_workspace(self._legacy_teachers())
        return {"version": 1, "default_workspace_id": workspace["id"], "workspaces": [workspace]}

    def _write(self, data: Dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, self.path)
        default = next((w for w in data["workspaces"] if w["id"] == data["default_workspace_id"]), None)
        if self.legacy and default:
            temporary = self.legacy.with_suffix(self.legacy.suffix + ".tmp")
            temporary.write_text(json.dumps(default["teachers"], ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(temporary, self.legacy)

    def _normalize(self, raw: Any) -> Dict[str, Any]:
        if not isinstance(raw, dict) or not isinstance(raw.get("workspaces"), list) or not raw["workspaces"]:
            return self._initial()
        result, used = [], set()
        for source in raw["workspaces"]:
            if not isinstance(source, dict):
                continue
            workspace_id = text(source.get("id"), 64) or str(uuid.uuid4())
            if workspace_id in used:
                workspace_id = str(uuid.uuid4())
            used.add(workspace_id)
            teachers = []
            for index, item in enumerate(source.get("teachers") or [], 1):
                try:
                    teachers.append(normalize_teacher(item, item.get("id") if isinstance(item, dict) and isinstance(item.get("id"), int) else index))
                except (WorkspaceError, AttributeError):
                    pass
            templates = []
            for item in source.get("templates") or []:
                try:
                    template = normalize_template(item)
                    template["updated_at"] = text(item.get("updated_at"), 64) or template["updated_at"]
                    templates.append(template)
                except (WorkspaceError, AttributeError):
                    pass
            settings = deepcopy(DEFAULT_SETTINGS)
            if isinstance(source.get("settings"), dict):
                settings.update({k: text(v, 100) for k, v in source["settings"].items() if k in DEFAULT_SETTINGS})
            stamp = now()
            result.append({
                "id": workspace_id, "name": text(source.get("name"), 160) or "Без названия",
                "color": color(source.get("color")), "description": text(source.get("description"), 1000),
                "created_at": text(source.get("created_at"), 64) or stamp,
                "updated_at": text(source.get("updated_at"), 64) or stamp,
                "teachers": teachers, "templates": templates, "settings": settings,
            })
        if not result:
            return self._initial()
        default_id = text(raw.get("default_workspace_id"), 64)
        if default_id not in {item["id"] for item in result}:
            default_id = result[0]["id"]
        return {"version": 1, "default_workspace_id": default_id, "workspaces": result}

    def load(self) -> Dict[str, Any]:
        if not self.path.exists():
            data = self._initial(); self._write(data); return data
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raw = None
        data = self._normalize(raw)
        if data != raw:
            self._write(data)
        return data

    @staticmethod
    def summary(workspace: Dict[str, Any], default_id: str) -> Dict[str, Any]:
        return {
            "id": workspace["id"], "name": workspace["name"], "color": workspace["color"],
            "description": workspace.get("description", ""), "teacher_count": len(workspace["teachers"]),
            "template_count": len(workspace["templates"]), "is_default": workspace["id"] == default_id,
            "created_at": workspace.get("created_at", ""), "updated_at": workspace.get("updated_at", ""),
            "settings": deepcopy(workspace.get("settings", DEFAULT_SETTINGS)),
        }

    def list_workspaces(self) -> List[Dict[str, Any]]:
        data = self.load()
        return [self.summary(item, data["default_workspace_id"]) for item in data["workspaces"]]

    def default_workspace_id(self) -> str:
        return self.load()["default_workspace_id"]

    def _mutable(self, workspace_id: str) -> tuple[Dict[str, Any], Dict[str, Any]]:
        data = self.load()
        workspace = next((w for w in data["workspaces"] if w["id"] == workspace_id), None)
        if not workspace:
            raise WorkspaceNotFound("Пространство не найдено.")
        return data, workspace

    def get_workspace(self, workspace_id: Optional[str] = None) -> Dict[str, Any]:
        data = self.load(); target = workspace_id or data["default_workspace_id"]
        workspace = next((w for w in data["workspaces"] if w["id"] == target), None)
        if not workspace:
            raise WorkspaceNotFound("Пространство не найдено.")
        return deepcopy(workspace)

    def create_workspace(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        data = self.load(); workspace = self._new_workspace([])
        workspace.update({
            "name": unique_name(text(payload.get("name"), 160), [w["name"] for w in data["workspaces"]]),
            "color": color(payload.get("color")), "description": text(payload.get("description"), 1000),
        })
        if isinstance(payload.get("settings"), dict):
            workspace["settings"].update({k: text(v, 100) for k, v in payload["settings"].items() if k in DEFAULT_SETTINGS})
        data["workspaces"].append(workspace); self._write(data)
        return self.summary(workspace, data["default_workspace_id"])

    def update_workspace(self, workspace_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        data, workspace = self._mutable(workspace_id)
        if "name" in payload:
            candidate = text(payload["name"], 160)
            if not candidate: raise WorkspaceError("Название пространства не может быть пустым.")
            if any(w["id"] != workspace_id and w["name"].casefold() == candidate.casefold() for w in data["workspaces"]):
                raise WorkspaceError("Пространство с таким названием уже существует.")
            workspace["name"] = candidate
        if "color" in payload:
            candidate = text(payload["color"], 7).upper()
            if not COLOR_RE.fullmatch(candidate): raise WorkspaceError("Цвет должен быть задан в формате #RRGGBB.")
            workspace["color"] = candidate
        if "description" in payload: workspace["description"] = text(payload["description"], 1000)
        if isinstance(payload.get("settings"), dict):
            workspace["settings"].update({k: text(v, 100) for k, v in payload["settings"].items() if k in DEFAULT_SETTINGS})
        if payload.get("is_default"): data["default_workspace_id"] = workspace_id
        workspace["updated_at"] = now(); self._write(data)
        return self.summary(workspace, data["default_workspace_id"])

    def delete_workspace(self, workspace_id: str) -> None:
        data = self.load()
        if len(data["workspaces"]) == 1: raise WorkspaceError("Нельзя удалить последнее пространство.")
        updated = [w for w in data["workspaces"] if w["id"] != workspace_id]
        if len(updated) == len(data["workspaces"]): raise WorkspaceNotFound("Пространство не найдено.")
        data["workspaces"] = updated
        if data["default_workspace_id"] == workspace_id: data["default_workspace_id"] = updated[0]["id"]
        self._write(data)

    def duplicate_workspace(self, workspace_id: str, name: Optional[str] = None) -> Dict[str, Any]:
        data, source = self._mutable(workspace_id); copy = deepcopy(source); stamp = now()
        copy.update({"id": str(uuid.uuid4()), "name": unique_name(name or f"{source['name']} — копия", [w["name"] for w in data["workspaces"]]), "created_at": stamp, "updated_at": stamp})
        for template in copy["templates"]: template.update({"id": str(uuid.uuid4()), "created_at": stamp, "updated_at": stamp})
        data["workspaces"].append(copy); self._write(data)
        return self.summary(copy, data["default_workspace_id"])

    def export_workspace(self, workspace_id: str) -> Dict[str, Any]:
        return {"format": "planner-solving-workspace", "version": 1, "exported_at": now(), "workspace": self.get_workspace(workspace_id)}

    def import_workspace(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        source = payload.get("workspace") if isinstance(payload.get("workspace"), dict) else payload
        if not isinstance(source, dict): raise WorkspaceError("Файл не содержит пространства.")
        data = self.load(); workspace = self._new_workspace([])
        workspace.update({"name": unique_name(text(source.get("name"), 160), [w["name"] for w in data["workspaces"]]), "color": color(source.get("color")), "description": text(source.get("description"), 1000)})
        workspace["teachers"] = [normalize_teacher(item, index) for index, item in enumerate(source.get("teachers") or [], 1) if isinstance(item, dict)]
        workspace["templates"] = [normalize_template(item, str(uuid.uuid4())) for item in source.get("templates") or [] if isinstance(item, dict)]
        if isinstance(source.get("settings"), dict): workspace["settings"].update({k: text(v, 100) for k, v in source["settings"].items() if k in DEFAULT_SETTINGS})
        data["workspaces"].append(workspace); self._write(data)
        return self.summary(workspace, data["default_workspace_id"])

    def list_teachers(self, workspace_id: str) -> List[Dict[str, Any]]:
        return self.get_workspace(workspace_id)["teachers"]

    def create_teacher(self, workspace_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        data, workspace = self._mutable(workspace_id); next_id = max((t["id"] for t in workspace["teachers"]), default=0) + 1
        teacher = normalize_teacher(payload, next_id)
        if teacher_key(teacher) in {teacher_key(t) for t in workspace["teachers"]}: raise WorkspaceError("Такой преподаватель уже есть в пространстве.")
        workspace["teachers"].append(teacher); workspace["updated_at"] = now(); self._write(data); return deepcopy(teacher)

    def update_teacher(self, workspace_id: str, teacher_id: int, payload: Dict[str, Any]) -> Dict[str, Any]:
        data, workspace = self._mutable(workspace_id); teacher = next((t for t in workspace["teachers"] if t["id"] == teacher_id), None)
        if not teacher: raise WorkspaceNotFound("Преподаватель не найден.")
        normalized = normalize_teacher({**teacher, **payload}, teacher_id)
        if any(t["id"] != teacher_id and teacher_key(t) == teacher_key(normalized) for t in workspace["teachers"]): raise WorkspaceError("Такой преподаватель уже есть в пространстве.")
        teacher.clear(); teacher.update(normalized); workspace["updated_at"] = now(); self._write(data); return deepcopy(teacher)

    def delete_teacher(self, workspace_id: str, teacher_id: int) -> None:
        data, workspace = self._mutable(workspace_id); updated = [t for t in workspace["teachers"] if t["id"] != teacher_id]
        if len(updated) == len(workspace["teachers"]): raise WorkspaceNotFound("Преподаватель не найден.")
        workspace["teachers"] = updated; workspace["updated_at"] = now(); self._write(data)

    def import_teachers(self, workspace_id: str, records: List[Dict[str, Any]], mode: str = "append") -> Dict[str, int]:
        if mode not in {"append", "replace"}: raise WorkspaceError("Неизвестный режим импорта.")
        data, workspace = self._mutable(workspace_id); current = [] if mode == "replace" else deepcopy(workspace["teachers"])
        keys, next_id, added, skipped = {teacher_key(t) for t in current}, max((t["id"] for t in current), default=0) + 1, 0, 0
        for raw in records:
            try: teacher = normalize_teacher(raw, next_id)
            except (WorkspaceError, AttributeError): skipped += 1; continue
            if teacher_key(teacher) in keys: skipped += 1; continue
            current.append(teacher); keys.add(teacher_key(teacher)); next_id += 1; added += 1
        workspace["teachers"] = current; workspace["updated_at"] = now(); self._write(data)
        return {"added": added, "skipped": skipped, "total": len(current)}

    def list_templates(self, workspace_id: str) -> List[Dict[str, Any]]:
        return sorted(self.get_workspace(workspace_id)["templates"], key=lambda item: item["name"].casefold())

    def create_template(self, workspace_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        data, workspace = self._mutable(workspace_id); template = normalize_template(payload)
        if template["name"].casefold() in {t["name"].casefold() for t in workspace["templates"]}: raise WorkspaceError("Шаблон с таким названием уже существует.")
        workspace["templates"].append(template); workspace["updated_at"] = now(); self._write(data); return deepcopy(template)

    def update_template(self, workspace_id: str, template_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        data, workspace = self._mutable(workspace_id); template = next((t for t in workspace["templates"] if t["id"] == template_id), None)
        if not template: raise WorkspaceNotFound("Шаблон не найден.")
        normalized = normalize_template({**template, **payload}, template_id)
        if any(t["id"] != template_id and t["name"].casefold() == normalized["name"].casefold() for t in workspace["templates"]): raise WorkspaceError("Шаблон с таким названием уже существует.")
        template.clear(); template.update(normalized); workspace["updated_at"] = now(); self._write(data); return deepcopy(template)

    def delete_template(self, workspace_id: str, template_id: str) -> None:
        data, workspace = self._mutable(workspace_id); updated = [t for t in workspace["templates"] if t["id"] != template_id]
        if len(updated) == len(workspace["templates"]): raise WorkspaceNotFound("Шаблон не найден.")
        workspace["templates"] = updated; workspace["updated_at"] = now(); self._write(data)

    def import_templates(self, workspace_id: str, records: List[Dict[str, Any]], mode: str = "append") -> Dict[str, int]:
        if mode not in {"append", "replace"}: raise WorkspaceError("Неизвестный режим импорта.")
        data, workspace = self._mutable(workspace_id); current = [] if mode == "replace" else deepcopy(workspace["templates"])
        names, added, skipped = {t["name"].casefold() for t in current}, 0, 0
        for raw in records:
            try: template = normalize_template(raw, str(uuid.uuid4()))
            except (WorkspaceError, AttributeError): skipped += 1; continue
            if template["name"].casefold() in names: skipped += 1; continue
            current.append(template); names.add(template["name"].casefold()); added += 1
        workspace["templates"] = current; workspace["updated_at"] = now(); self._write(data)
        return {"added": added, "skipped": skipped, "total": len(current)}
