"""Transactional SQLite storage for workspaces, teachers and layout templates."""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import date
import json
import os
from pathlib import Path
import sqlite3
from typing import Any, Dict, Iterable, Iterator, List, Optional
import uuid

from .workspace_store import (
    DEFAULT_COLOR,
    DEFAULT_SETTINGS,
    WorkspaceError,
    WorkspaceNotFound,
    color,
    normalize_teacher,
    normalize_template,
    now,
    teacher_key,
    text,
    unique_name,
)

SQLITE_SCHEMA_VERSION = 1


def _settings(payload: Any, current: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    result = deepcopy(current or DEFAULT_SETTINGS)
    if isinstance(payload, dict):
        for key in DEFAULT_SETTINGS:
            if key in payload:
                result[key] = text(payload[key], 100)
    try:
        start = date.fromisoformat(result["schedule_start_date"])
        end = date.fromisoformat(result["schedule_end_date"])
    except (KeyError, ValueError) as exc:
        raise WorkspaceError("Даты семестра должны быть заданы в формате ГГГГ-ММ-ДД.") from exc
    if start > end:
        raise WorkspaceError("Дата начала семестра не может быть позже даты окончания.")
    return result


def _atomic_write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


class SQLiteWorkspaceStore:
    """Workspace repository with one short SQLite transaction per operation.

    The public API intentionally matches ``WorkspaceStore`` so callers can switch
    storage engines without changing HTTP or domain code. Existing JSON data is
    imported on first start and remains an atomic compatibility mirror.
    """

    def __init__(
        self,
        path: Path,
        legacy_json_path: Optional[Path] = None,
        legacy_teachers_path: Optional[Path] = None,
    ) -> None:
        self.path = Path(path)
        self.legacy_json = Path(legacy_json_path) if legacy_json_path else None
        self.legacy_teachers = Path(legacy_teachers_path) if legacy_teachers_path else None
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        connection = self._connect()
        try:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS workspaces (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                    color TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    schedule_start_date TEXT NOT NULL,
                    schedule_end_date TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS teachers (
                    workspace_id TEXT NOT NULL,
                    id INTEGER NOT NULL,
                    short_name TEXT NOT NULL,
                    full_name TEXT NOT NULL,
                    position TEXT NOT NULL DEFAULT '',
                    rank TEXT NOT NULL DEFAULT '',
                    academic_degree TEXT NOT NULL DEFAULT '',
                    normalized_name TEXT NOT NULL,
                    PRIMARY KEY (workspace_id, id),
                    UNIQUE (workspace_id, normalized_name),
                    FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS templates (
                    workspace_id TEXT NOT NULL,
                    id TEXT NOT NULL,
                    name TEXT NOT NULL COLLATE NOCASE,
                    description TEXT NOT NULL DEFAULT '',
                    layout_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (workspace_id, id),
                    UNIQUE (workspace_id, name),
                    FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_teachers_workspace
                    ON teachers(workspace_id, id);
                CREATE INDEX IF NOT EXISTS idx_templates_workspace
                    ON templates(workspace_id, name);
                """
            )
            connection.execute(f"PRAGMA user_version = {SQLITE_SCHEMA_VERSION}")
            connection.commit()
        finally:
            connection.close()

        with self._transaction() as connection:
            count = int(connection.execute("SELECT COUNT(*) FROM workspaces").fetchone()[0])
            if count == 0:
                self._insert_document(connection, self._legacy_document())
            self._repair_default(connection)
            self._write_compatibility_mirrors(connection)

    def _legacy_document(self) -> Dict[str, Any]:
        if self.legacy_json and self.legacy_json.exists():
            try:
                payload = json.loads(self.legacy_json.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise WorkspaceError(f"Не удалось прочитать прежнее хранилище: {exc}") from exc
            if not isinstance(payload, dict) or not isinstance(payload.get("workspaces"), list):
                raise WorkspaceError("Прежнее хранилище пространств имеет неверную структуру.")
            return payload

        teachers: List[Dict[str, Any]] = []
        if self.legacy_teachers and self.legacy_teachers.exists():
            try:
                raw = json.loads(self.legacy_teachers.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise WorkspaceError(f"Не удалось прочитать прежний список преподавателей: {exc}") from exc
            if isinstance(raw, list):
                teachers = [item for item in raw if isinstance(item, dict)]

        stamp = now()
        workspace_id = str(uuid.uuid4())
        normalized: List[Dict[str, Any]] = []
        for index, item in enumerate(teachers, 1):
            try:
                normalized.append(normalize_teacher(item, index))
            except WorkspaceError:
                continue
        return {
            "version": SQLITE_SCHEMA_VERSION,
            "default_workspace_id": workspace_id,
            "workspaces": [{
                "id": workspace_id,
                "name": "Основное пространство",
                "color": DEFAULT_COLOR,
                "description": "Создано автоматически из существующего списка преподавателей.",
                "created_at": stamp,
                "updated_at": stamp,
                "teachers": normalized,
                "templates": [],
                "settings": deepcopy(DEFAULT_SETTINGS),
            }],
        }

    def _insert_document(self, connection: sqlite3.Connection, payload: Dict[str, Any]) -> None:
        raw_workspaces = payload.get("workspaces")
        if not isinstance(raw_workspaces, list) or not raw_workspaces:
            raise WorkspaceError("В переносимом хранилище нет рабочих пространств.")

        used_names: List[str] = []
        inserted_ids: List[str] = []
        requested_default = text(payload.get("default_workspace_id"), 64)
        for raw in raw_workspaces:
            if not isinstance(raw, dict):
                continue
            workspace_id = text(raw.get("id"), 64) or str(uuid.uuid4())
            if workspace_id in inserted_ids:
                workspace_id = str(uuid.uuid4())
            name = unique_name(text(raw.get("name"), 160), used_names)
            used_names.append(name)
            settings = _settings(raw.get("settings"))
            stamp = now()
            connection.execute(
                """
                INSERT INTO workspaces(
                    id, name, color, description, created_at, updated_at,
                    schedule_start_date, schedule_end_date
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    workspace_id,
                    name,
                    color(raw.get("color")),
                    text(raw.get("description"), 1000),
                    text(raw.get("created_at"), 64) or stamp,
                    text(raw.get("updated_at"), 64) or stamp,
                    settings["schedule_start_date"],
                    settings["schedule_end_date"],
                ),
            )
            inserted_ids.append(workspace_id)

            teacher_keys: set[str] = set()
            next_teacher_id = 1
            for item in raw.get("teachers") or []:
                if not isinstance(item, dict):
                    continue
                candidate_id = item.get("id") if isinstance(item.get("id"), int) else next_teacher_id
                try:
                    teacher = normalize_teacher(item, int(candidate_id))
                except (WorkspaceError, TypeError, ValueError):
                    continue
                key = teacher_key(teacher)
                if not key or key in teacher_keys:
                    continue
                while connection.execute(
                    "SELECT 1 FROM teachers WHERE workspace_id = ? AND id = ?",
                    (workspace_id, teacher["id"]),
                ).fetchone():
                    teacher["id"] += 1
                self._insert_teacher(connection, workspace_id, teacher)
                teacher_keys.add(key)
                next_teacher_id = max(next_teacher_id, teacher["id"] + 1)

            template_names: set[str] = set()
            for item in raw.get("templates") or []:
                if not isinstance(item, dict):
                    continue
                try:
                    template = normalize_template(item, text(item.get("id"), 64) or str(uuid.uuid4()))
                except (WorkspaceError, AttributeError):
                    continue
                folded = template["name"].casefold()
                if folded in template_names:
                    continue
                self._insert_template(connection, workspace_id, template)
                template_names.add(folded)

        if not inserted_ids:
            raise WorkspaceError("В переносимом хранилище нет пригодных рабочих пространств.")
        default_id = requested_default if requested_default in inserted_ids else inserted_ids[0]
        self._set_meta(connection, "default_workspace_id", default_id)
        self._set_meta(connection, "document_version", str(SQLITE_SCHEMA_VERSION))

    @staticmethod
    def _insert_teacher(connection: sqlite3.Connection, workspace_id: str, teacher: Dict[str, Any]) -> None:
        connection.execute(
            """
            INSERT INTO teachers(
                workspace_id, id, short_name, full_name, position, rank,
                academic_degree, normalized_name
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                workspace_id,
                teacher["id"],
                teacher["short_name"],
                teacher["full_name"],
                teacher.get("position", ""),
                teacher.get("rank", ""),
                teacher.get("academic_degree", ""),
                teacher_key(teacher),
            ),
        )

    @staticmethod
    def _insert_template(connection: sqlite3.Connection, workspace_id: str, template: Dict[str, Any]) -> None:
        connection.execute(
            """
            INSERT INTO templates(
                workspace_id, id, name, description, layout_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                workspace_id,
                template["id"],
                template["name"],
                template.get("description", ""),
                json.dumps(template["layout"], ensure_ascii=False, separators=(",", ":")),
                template.get("created_at") or now(),
                template.get("updated_at") or now(),
            ),
        )

    @staticmethod
    def _set_meta(connection: sqlite3.Connection, key: str, value: str) -> None:
        connection.execute(
            "INSERT INTO metadata(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )

    @staticmethod
    def _get_meta(connection: sqlite3.Connection, key: str) -> Optional[str]:
        row = connection.execute("SELECT value FROM metadata WHERE key = ?", (key,)).fetchone()
        return str(row["value"]) if row else None

    def _repair_default(self, connection: sqlite3.Connection) -> str:
        default_id = self._get_meta(connection, "default_workspace_id")
        if default_id and connection.execute(
            "SELECT 1 FROM workspaces WHERE id = ?", (default_id,)
        ).fetchone():
            return default_id
        row = connection.execute("SELECT id FROM workspaces ORDER BY created_at, id LIMIT 1").fetchone()
        if not row:
            raise WorkspaceError("Хранилище не содержит рабочих пространств.")
        default_id = str(row["id"])
        self._set_meta(connection, "default_workspace_id", default_id)
        return default_id

    def _workspace(self, connection: sqlite3.Connection, workspace_id: str) -> Dict[str, Any]:
        row = connection.execute("SELECT * FROM workspaces WHERE id = ?", (workspace_id,)).fetchone()
        if not row:
            raise WorkspaceNotFound("Пространство не найдено.")
        teachers = [dict(item) for item in connection.execute(
            """
            SELECT id, short_name, full_name, position, rank, academic_degree
            FROM teachers WHERE workspace_id = ? ORDER BY id
            """,
            (workspace_id,),
        ).fetchall()]
        templates = []
        for item in connection.execute(
            """
            SELECT id, name, description, layout_json, created_at, updated_at
            FROM templates WHERE workspace_id = ? ORDER BY name COLLATE NOCASE
            """,
            (workspace_id,),
        ).fetchall():
            template = dict(item)
            template["layout"] = json.loads(template.pop("layout_json"))
            templates.append(template)
        return {
            "id": str(row["id"]),
            "name": str(row["name"]),
            "color": str(row["color"]),
            "description": str(row["description"] or ""),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
            "teachers": teachers,
            "templates": templates,
            "settings": {
                "schedule_start_date": str(row["schedule_start_date"]),
                "schedule_end_date": str(row["schedule_end_date"]),
            },
        }

    def _document(self, connection: sqlite3.Connection) -> Dict[str, Any]:
        default_id = self._repair_default(connection)
        ids = [str(row["id"]) for row in connection.execute(
            "SELECT id FROM workspaces ORDER BY created_at, id"
        ).fetchall()]
        return {
            "version": SQLITE_SCHEMA_VERSION,
            "default_workspace_id": default_id,
            "workspaces": [self._workspace(connection, workspace_id) for workspace_id in ids],
        }

    def _write_compatibility_mirrors(self, connection: sqlite3.Connection) -> None:
        document = self._document(connection)
        if self.legacy_json:
            _atomic_write(self.legacy_json, document)
        if self.legacy_teachers:
            default = next(
                item for item in document["workspaces"]
                if item["id"] == document["default_workspace_id"]
            )
            _atomic_write(self.legacy_teachers, default["teachers"])

    @staticmethod
    def summary(workspace: Dict[str, Any], default_id: str) -> Dict[str, Any]:
        return {
            "id": workspace["id"],
            "name": workspace["name"],
            "color": workspace["color"],
            "description": workspace.get("description", ""),
            "teacher_count": len(workspace.get("teachers", [])),
            "template_count": len(workspace.get("templates", [])),
            "is_default": workspace["id"] == default_id,
            "created_at": workspace.get("created_at", ""),
            "updated_at": workspace.get("updated_at", ""),
            "settings": deepcopy(workspace.get("settings", DEFAULT_SETTINGS)),
        }

    def load(self) -> Dict[str, Any]:
        connection = self._connect()
        try:
            return self._document(connection)
        finally:
            connection.close()

    def schema_version(self) -> int:
        connection = self._connect()
        try:
            return int(connection.execute("PRAGMA user_version").fetchone()[0])
        finally:
            connection.close()

    def list_workspaces(self) -> List[Dict[str, Any]]:
        document = self.load()
        return [self.summary(item, document["default_workspace_id"]) for item in document["workspaces"]]

    def default_workspace_id(self) -> str:
        connection = self._connect()
        try:
            return self._repair_default(connection)
        finally:
            connection.close()

    def get_workspace(self, workspace_id: Optional[str] = None) -> Dict[str, Any]:
        connection = self._connect()
        try:
            target = workspace_id or self._repair_default(connection)
            return self._workspace(connection, target)
        finally:
            connection.close()

    def create_workspace(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        with self._transaction() as connection:
            names = [str(row["name"]) for row in connection.execute("SELECT name FROM workspaces")]
            workspace_id = str(uuid.uuid4())
            stamp = now()
            settings = _settings(payload.get("settings"))
            workspace_name = unique_name(text(payload.get("name"), 160), names)
            connection.execute(
                """
                INSERT INTO workspaces(
                    id, name, color, description, created_at, updated_at,
                    schedule_start_date, schedule_end_date
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    workspace_id, workspace_name, color(payload.get("color")),
                    text(payload.get("description"), 1000), stamp, stamp,
                    settings["schedule_start_date"], settings["schedule_end_date"],
                ),
            )
            self._write_compatibility_mirrors(connection)
            workspace = self._workspace(connection, workspace_id)
            return self.summary(workspace, self._repair_default(connection))

    def update_workspace(self, workspace_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        with self._transaction() as connection:
            current = self._workspace(connection, workspace_id)
            name = current["name"]
            if "name" in payload:
                name = text(payload.get("name"), 160)
                if not name:
                    raise WorkspaceError("Название пространства не может быть пустым.")
                duplicate = connection.execute(
                    "SELECT 1 FROM workspaces WHERE id <> ? AND name = ? COLLATE NOCASE",
                    (workspace_id, name),
                ).fetchone()
                if duplicate:
                    raise WorkspaceError("Пространство с таким названием уже существует.")
            selected_color = current["color"]
            if "color" in payload:
                raw_color = text(payload.get("color"), 7).upper()
                selected_color = color(raw_color)
                if selected_color != raw_color:
                    raise WorkspaceError("Цвет должен быть задан в формате #RRGGBB.")
            description = (
                text(payload.get("description"), 1000)
                if "description" in payload else current["description"]
            )
            settings = _settings(payload.get("settings"), current["settings"])
            connection.execute(
                """
                UPDATE workspaces SET
                    name = ?, color = ?, description = ?, updated_at = ?,
                    schedule_start_date = ?, schedule_end_date = ?
                WHERE id = ?
                """,
                (
                    name, selected_color, description, now(),
                    settings["schedule_start_date"], settings["schedule_end_date"],
                    workspace_id,
                ),
            )
            if payload.get("is_default"):
                self._set_meta(connection, "default_workspace_id", workspace_id)
            self._write_compatibility_mirrors(connection)
            workspace = self._workspace(connection, workspace_id)
            return self.summary(workspace, self._repair_default(connection))

    def delete_workspace(self, workspace_id: str) -> None:
        with self._transaction() as connection:
            count = int(connection.execute("SELECT COUNT(*) FROM workspaces").fetchone()[0])
            if count <= 1:
                raise WorkspaceError("Нельзя удалить последнее пространство.")
            cursor = connection.execute("DELETE FROM workspaces WHERE id = ?", (workspace_id,))
            if cursor.rowcount == 0:
                raise WorkspaceNotFound("Пространство не найдено.")
            self._repair_default(connection)
            self._write_compatibility_mirrors(connection)

    def duplicate_workspace(self, workspace_id: str, name: Optional[str] = None) -> Dict[str, Any]:
        with self._transaction() as connection:
            source = self._workspace(connection, workspace_id)
            names = [str(row["name"]) for row in connection.execute("SELECT name FROM workspaces")]
            new_id = str(uuid.uuid4())
            stamp = now()
            new_name = unique_name(name or f"{source['name']} — копия", names)
            settings = source["settings"]
            connection.execute(
                """
                INSERT INTO workspaces(
                    id, name, color, description, created_at, updated_at,
                    schedule_start_date, schedule_end_date
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    new_id, new_name, source["color"], source["description"], stamp, stamp,
                    settings["schedule_start_date"], settings["schedule_end_date"],
                ),
            )
            for teacher in source["teachers"]:
                self._insert_teacher(connection, new_id, teacher)
            for template in source["templates"]:
                duplicated = deepcopy(template)
                duplicated.update({"id": str(uuid.uuid4()), "created_at": stamp, "updated_at": stamp})
                self._insert_template(connection, new_id, duplicated)
            self._write_compatibility_mirrors(connection)
            workspace = self._workspace(connection, new_id)
            return self.summary(workspace, self._repair_default(connection))

    def export_workspace(self, workspace_id: str) -> Dict[str, Any]:
        return {
            "format": "planner-solving-workspace",
            "version": SQLITE_SCHEMA_VERSION,
            "exported_at": now(),
            "workspace": self.get_workspace(workspace_id),
        }

    def import_workspace(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        source = payload.get("workspace") if isinstance(payload.get("workspace"), dict) else payload
        if not isinstance(source, dict):
            raise WorkspaceError("Файл не содержит пространства.")
        with self._transaction() as connection:
            names = [str(row["name"]) for row in connection.execute("SELECT name FROM workspaces")]
            workspace_id = str(uuid.uuid4())
            stamp = now()
            settings = _settings(source.get("settings"))
            workspace_name = unique_name(text(source.get("name"), 160), names)
            connection.execute(
                """
                INSERT INTO workspaces(
                    id, name, color, description, created_at, updated_at,
                    schedule_start_date, schedule_end_date
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    workspace_id, workspace_name, color(source.get("color")),
                    text(source.get("description"), 1000), stamp, stamp,
                    settings["schedule_start_date"], settings["schedule_end_date"],
                ),
            )
            seen_teachers: set[str] = set()
            next_id = 1
            for raw in source.get("teachers") or []:
                if not isinstance(raw, dict):
                    continue
                try:
                    teacher = normalize_teacher(raw, next_id)
                except WorkspaceError:
                    continue
                key = teacher_key(teacher)
                if not key or key in seen_teachers:
                    continue
                self._insert_teacher(connection, workspace_id, teacher)
                seen_teachers.add(key)
                next_id += 1
            seen_templates: set[str] = set()
            for raw in source.get("templates") or []:
                if not isinstance(raw, dict):
                    continue
                try:
                    template = normalize_template(raw, str(uuid.uuid4()))
                except WorkspaceError:
                    continue
                key = template["name"].casefold()
                if key in seen_templates:
                    continue
                self._insert_template(connection, workspace_id, template)
                seen_templates.add(key)
            self._write_compatibility_mirrors(connection)
            workspace = self._workspace(connection, workspace_id)
            return self.summary(workspace, self._repair_default(connection))

    def list_teachers(self, workspace_id: str) -> List[Dict[str, Any]]:
        return self.get_workspace(workspace_id)["teachers"]

    def create_teacher(self, workspace_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        with self._transaction() as connection:
            self._workspace(connection, workspace_id)
            next_id = int(connection.execute(
                "SELECT COALESCE(MAX(id), 0) + 1 FROM teachers WHERE workspace_id = ?",
                (workspace_id,),
            ).fetchone()[0])
            teacher = normalize_teacher(payload, next_id)
            try:
                self._insert_teacher(connection, workspace_id, teacher)
            except sqlite3.IntegrityError as exc:
                raise WorkspaceError("Такой преподаватель уже есть в пространстве.") from exc
            connection.execute("UPDATE workspaces SET updated_at = ? WHERE id = ?", (now(), workspace_id))
            self._write_compatibility_mirrors(connection)
            return deepcopy(teacher)

    def update_teacher(self, workspace_id: str, teacher_id: int, payload: Dict[str, Any]) -> Dict[str, Any]:
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM teachers WHERE workspace_id = ? AND id = ?",
                (workspace_id, teacher_id),
            ).fetchone()
            if not row:
                raise WorkspaceNotFound("Преподаватель не найден.")
            current = {
                "id": int(row["id"]), "short_name": row["short_name"],
                "full_name": row["full_name"], "position": row["position"],
                "rank": row["rank"], "academic_degree": row["academic_degree"],
            }
            teacher = normalize_teacher({**current, **payload}, teacher_id)
            try:
                connection.execute(
                    """
                    UPDATE teachers SET
                        short_name = ?, full_name = ?, position = ?, rank = ?,
                        academic_degree = ?, normalized_name = ?
                    WHERE workspace_id = ? AND id = ?
                    """,
                    (
                        teacher["short_name"], teacher["full_name"], teacher["position"],
                        teacher["rank"], teacher["academic_degree"], teacher_key(teacher),
                        workspace_id, teacher_id,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise WorkspaceError("Такой преподаватель уже есть в пространстве.") from exc
            connection.execute("UPDATE workspaces SET updated_at = ? WHERE id = ?", (now(), workspace_id))
            self._write_compatibility_mirrors(connection)
            return deepcopy(teacher)

    def delete_teacher(self, workspace_id: str, teacher_id: int) -> None:
        with self._transaction() as connection:
            cursor = connection.execute(
                "DELETE FROM teachers WHERE workspace_id = ? AND id = ?",
                (workspace_id, teacher_id),
            )
            if cursor.rowcount == 0:
                raise WorkspaceNotFound("Преподаватель не найден.")
            connection.execute("UPDATE workspaces SET updated_at = ? WHERE id = ?", (now(), workspace_id))
            self._write_compatibility_mirrors(connection)

    def import_teachers(self, workspace_id: str, records: List[Dict[str, Any]], mode: str = "append") -> Dict[str, int]:
        if mode not in {"append", "replace"}:
            raise WorkspaceError("Неизвестный режим импорта.")
        with self._transaction() as connection:
            self._workspace(connection, workspace_id)
            if mode == "replace":
                connection.execute("DELETE FROM teachers WHERE workspace_id = ?", (workspace_id,))
            existing = {
                str(row["normalized_name"])
                for row in connection.execute(
                    "SELECT normalized_name FROM teachers WHERE workspace_id = ?", (workspace_id,)
                ).fetchall()
            }
            next_id = int(connection.execute(
                "SELECT COALESCE(MAX(id), 0) + 1 FROM teachers WHERE workspace_id = ?",
                (workspace_id,),
            ).fetchone()[0])
            added = skipped = 0
            for raw in records:
                try:
                    teacher = normalize_teacher(raw, next_id)
                except (WorkspaceError, AttributeError):
                    skipped += 1
                    continue
                key = teacher_key(teacher)
                if not key or key in existing:
                    skipped += 1
                    continue
                self._insert_teacher(connection, workspace_id, teacher)
                existing.add(key)
                next_id += 1
                added += 1
            connection.execute("UPDATE workspaces SET updated_at = ? WHERE id = ?", (now(), workspace_id))
            self._write_compatibility_mirrors(connection)
            total = int(connection.execute(
                "SELECT COUNT(*) FROM teachers WHERE workspace_id = ?", (workspace_id,)
            ).fetchone()[0])
            return {"added": added, "skipped": skipped, "total": total}

    def list_templates(self, workspace_id: str) -> List[Dict[str, Any]]:
        return self.get_workspace(workspace_id)["templates"]

    def create_template(self, workspace_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        with self._transaction() as connection:
            self._workspace(connection, workspace_id)
            template = normalize_template(payload)
            try:
                self._insert_template(connection, workspace_id, template)
            except sqlite3.IntegrityError as exc:
                raise WorkspaceError("Шаблон с таким названием уже существует.") from exc
            connection.execute("UPDATE workspaces SET updated_at = ? WHERE id = ?", (now(), workspace_id))
            self._write_compatibility_mirrors(connection)
            return deepcopy(template)

    def update_template(self, workspace_id: str, template_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM templates WHERE workspace_id = ? AND id = ?",
                (workspace_id, template_id),
            ).fetchone()
            if not row:
                raise WorkspaceNotFound("Шаблон не найден.")
            current = {
                "id": row["id"], "name": row["name"], "description": row["description"],
                "layout": json.loads(row["layout_json"]), "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            template = normalize_template({**current, **payload}, template_id)
            template["created_at"] = current["created_at"]
            try:
                connection.execute(
                    """
                    UPDATE templates SET
                        name = ?, description = ?, layout_json = ?, updated_at = ?
                    WHERE workspace_id = ? AND id = ?
                    """,
                    (
                        template["name"], template["description"],
                        json.dumps(template["layout"], ensure_ascii=False, separators=(",", ":")),
                        template["updated_at"], workspace_id, template_id,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise WorkspaceError("Шаблон с таким названием уже существует.") from exc
            connection.execute("UPDATE workspaces SET updated_at = ? WHERE id = ?", (now(), workspace_id))
            self._write_compatibility_mirrors(connection)
            return deepcopy(template)

    def delete_template(self, workspace_id: str, template_id: str) -> None:
        with self._transaction() as connection:
            cursor = connection.execute(
                "DELETE FROM templates WHERE workspace_id = ? AND id = ?",
                (workspace_id, template_id),
            )
            if cursor.rowcount == 0:
                raise WorkspaceNotFound("Шаблон не найден.")
            connection.execute("UPDATE workspaces SET updated_at = ? WHERE id = ?", (now(), workspace_id))
            self._write_compatibility_mirrors(connection)

    def import_templates(self, workspace_id: str, records: List[Dict[str, Any]], mode: str = "append") -> Dict[str, int]:
        if mode not in {"append", "replace"}:
            raise WorkspaceError("Неизвестный режим импорта.")
        with self._transaction() as connection:
            self._workspace(connection, workspace_id)
            if mode == "replace":
                connection.execute("DELETE FROM templates WHERE workspace_id = ?", (workspace_id,))
            names = {
                str(row["name"]).casefold()
                for row in connection.execute(
                    "SELECT name FROM templates WHERE workspace_id = ?", (workspace_id,)
                ).fetchall()
            }
            added = skipped = 0
            for raw in records:
                try:
                    template = normalize_template(raw, str(uuid.uuid4()))
                except (WorkspaceError, AttributeError):
                    skipped += 1
                    continue
                key = template["name"].casefold()
                if key in names:
                    skipped += 1
                    continue
                self._insert_template(connection, workspace_id, template)
                names.add(key)
                added += 1
            connection.execute("UPDATE workspaces SET updated_at = ? WHERE id = ?", (now(), workspace_id))
            self._write_compatibility_mirrors(connection)
            total = int(connection.execute(
                "SELECT COUNT(*) FROM templates WHERE workspace_id = ?", (workspace_id,)
            ).fetchone()[0])
            return {"added": added, "skipped": skipped, "total": total}
