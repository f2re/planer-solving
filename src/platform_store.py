"""Operations platform storage layered on the transactional workspace repository."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence
import uuid

from .import_wizard import apply_teacher_decision, teacher_key
from .security import (
    hash_password,
    iso_now,
    new_session_token,
    session_expiry,
    token_digest,
    verify_password,
)
from .sqlite_workspace_store import SQLiteWorkspaceStore
from .template_learning import layout_diff, normalize_composite_rules
from .workspace_domain import (
    WorkspaceError,
    WorkspaceNotFound,
    normalize_teacher,
    normalize_template,
    now,
    text,
)

PLATFORM_SCHEMA_VERSION = 5
VALID_ROLES = {"admin", "operator", "viewer"}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _object(value: Any, fallback: Any) -> Any:
    if value is None or value == "":
        return deepcopy(fallback)
    if isinstance(value, (dict, list)):
        return deepcopy(value)
    try:
        parsed = json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return deepcopy(fallback)
    return parsed


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class PlatformStore:
    """One repository for imports, revisions, history, access and audit.

    Existing workspace CRUD remains delegated to ``SQLiteWorkspaceStore``. The
    additional tables are migrated in-place and use the same SQLite connection,
    transaction policy and compatibility mirrors.
    """

    def __init__(
        self,
        path: Path,
        legacy_json_path: Optional[Path] = None,
        legacy_teachers_path: Optional[Path] = None,
    ) -> None:
        self.base = SQLiteWorkspaceStore(path, legacy_json_path, legacy_teachers_path)
        self.path = self.base.path
        self.legacy_json = self.base.legacy_json
        self.legacy_teachers = self.base.legacy_teachers
        self._initialize_platform()

    def __getattr__(self, name: str) -> Any:
        return getattr(self.base, name)

    def _connect(self) -> sqlite3.Connection:
        return self.base._connect()

    def _transaction(self):
        return self.base._transaction()

    def _initialize_platform(self) -> None:
        with self._transaction() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    username TEXT NOT NULL COLLATE NOCASE UNIQUE,
                    display_name TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('admin','operator','viewer')),
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_login_at TEXT
                );

                CREATE TABLE IF NOT EXISTS auth_sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    workspace_id TEXT,
                    actor_user_id TEXT,
                    actor_name TEXT NOT NULL,
                    action TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    entity_id TEXT,
                    summary TEXT NOT NULL,
                    details_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE SET NULL,
                    FOREIGN KEY(actor_user_id) REFERENCES users(id) ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS import_jobs (
                    id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    actor_user_id TEXT,
                    kind TEXT NOT NULL CHECK(kind IN ('teachers','templates','workspace')),
                    filename TEXT NOT NULL,
                    source_json TEXT NOT NULL,
                    mapping_json TEXT NOT NULL DEFAULT '{}',
                    preview_json TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'preview',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    committed_at TEXT,
                    FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
                    FOREIGN KEY(actor_user_id) REFERENCES users(id) ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS template_profiles (
                    workspace_id TEXT NOT NULL,
                    template_id TEXT NOT NULL,
                    composite_json TEXT NOT NULL DEFAULT '[]',
                    fingerprint_json TEXT NOT NULL DEFAULT '{}',
                    current_revision INTEGER NOT NULL DEFAULT 1,
                    success_count INTEGER NOT NULL DEFAULT 0,
                    warning_count INTEGER NOT NULL DEFAULT 0,
                    failure_count INTEGER NOT NULL DEFAULT 0,
                    total_lessons INTEGER NOT NULL DEFAULT 0,
                    avg_quality REAL NOT NULL DEFAULT 0,
                    last_used_at TEXT,
                    PRIMARY KEY(workspace_id, template_id),
                    FOREIGN KEY(workspace_id, template_id)
                        REFERENCES templates(workspace_id, id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS template_revisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    workspace_id TEXT NOT NULL,
                    template_id TEXT NOT NULL,
                    revision_no INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    layout_json TEXT NOT NULL,
                    composite_json TEXT NOT NULL DEFAULT '[]',
                    fingerprint_json TEXT NOT NULL DEFAULT '{}',
                    comment TEXT NOT NULL DEFAULT '',
                    actor_user_id TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE(workspace_id, template_id, revision_no),
                    FOREIGN KEY(workspace_id, template_id)
                        REFERENCES templates(workspace_id, id) ON DELETE CASCADE,
                    FOREIGN KEY(actor_user_id) REFERENCES users(id) ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS processing_runs (
                    id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    session_id TEXT,
                    actor_user_id TEXT,
                    status TEXT NOT NULL,
                    source_count INTEGER NOT NULL DEFAULT 0,
                    lesson_count INTEGER NOT NULL DEFAULT 0,
                    warning_count INTEGER NOT NULL DEFAULT 0,
                    error_count INTEGER NOT NULL DEFAULT 0,
                    selected_templates_json TEXT NOT NULL DEFAULT '[]',
                    report_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    completed_at TEXT,
                    FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
                    FOREIGN KEY(actor_user_id) REFERENCES users(id) ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS processing_files (
                    run_id TEXT NOT NULL,
                    file_id TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    checksum TEXT NOT NULL DEFAULT '',
                    group_name TEXT NOT NULL DEFAULT '',
                    template_id TEXT,
                    template_revision INTEGER,
                    match_score REAL,
                    layout_json TEXT NOT NULL DEFAULT '{}',
                    report_json TEXT NOT NULL DEFAULT '{}',
                    PRIMARY KEY(run_id, file_id),
                    FOREIGN KEY(run_id) REFERENCES processing_runs(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS processing_artifacts (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    checksum TEXT NOT NULL,
                    size INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(run_id) REFERENCES processing_runs(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_sessions_user_expiry
                    ON auth_sessions(user_id, expires_at);
                CREATE INDEX IF NOT EXISTS idx_audit_workspace_time
                    ON audit_log(workspace_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_import_workspace_time
                    ON import_jobs(workspace_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_revision_template
                    ON template_revisions(workspace_id, template_id, revision_no DESC);
                CREATE INDEX IF NOT EXISTS idx_runs_workspace_time
                    ON processing_runs(workspace_id, created_at DESC);
                """
            )
            connection.execute(f"PRAGMA user_version = {PLATFORM_SCHEMA_VERSION}")
            self._seed_template_profiles(connection)

    def _seed_template_profiles(self, connection: sqlite3.Connection) -> None:
        rows = connection.execute(
            "SELECT workspace_id, id, name, description, layout_json, created_at FROM templates"
        ).fetchall()
        for row in rows:
            connection.execute(
                """
                INSERT OR IGNORE INTO template_profiles(workspace_id, template_id)
                VALUES (?, ?)
                """,
                (row["workspace_id"], row["id"]),
            )
            revision = connection.execute(
                """
                SELECT 1 FROM template_revisions
                WHERE workspace_id = ? AND template_id = ? LIMIT 1
                """,
                (row["workspace_id"], row["id"]),
            ).fetchone()
            if not revision:
                connection.execute(
                    """
                    INSERT INTO template_revisions(
                        workspace_id, template_id, revision_no, name, description,
                        layout_json, composite_json, fingerprint_json, comment,
                        actor_user_id, created_at
                    ) VALUES (?, ?, 1, ?, ?, ?, '[]', '{}', ?, NULL, ?)
                    """,
                    (
                        row["workspace_id"], row["id"], row["name"],
                        row["description"], row["layout_json"],
                        "Перенесено из версии 2.5", row["created_at"],
                    ),
                )

    def schema_version(self) -> int:
        connection = self._connect()
        try:
            return int(connection.execute("PRAGMA user_version").fetchone()[0])
        finally:
            connection.close()

    # ------------------------------------------------------------------
    # Template profiles and revisions
    # ------------------------------------------------------------------
    def _profile(self, connection: sqlite3.Connection, workspace_id: str, template_id: str) -> Dict[str, Any]:
        row = connection.execute(
            """
            SELECT * FROM template_profiles
            WHERE workspace_id = ? AND template_id = ?
            """,
            (workspace_id, template_id),
        ).fetchone()
        if not row:
            return {
                "composite": [], "fingerprint": {}, "current_revision": 1,
                "success_count": 0, "warning_count": 0, "failure_count": 0,
                "total_lessons": 0, "avg_quality": 0.0, "last_used_at": None,
            }
        return {
            "composite": _object(row["composite_json"], []),
            "fingerprint": _object(row["fingerprint_json"], {}),
            "current_revision": int(row["current_revision"]),
            "success_count": int(row["success_count"]),
            "warning_count": int(row["warning_count"]),
            "failure_count": int(row["failure_count"]),
            "total_lessons": int(row["total_lessons"]),
            "avg_quality": float(row["avg_quality"]),
            "last_used_at": row["last_used_at"],
        }

    def _enrich_template(self, workspace_id: str, template: Mapping[str, Any]) -> Dict[str, Any]:
        connection = self._connect()
        try:
            result = dict(template)
            result.update(self._profile(connection, workspace_id, str(template["id"])))
            return result
        finally:
            connection.close()

    def list_templates(self, workspace_id: str) -> List[Dict[str, Any]]:
        return [self._enrich_template(workspace_id, item) for item in self.base.list_templates(workspace_id)]

    def get_workspace(self, workspace_id: Optional[str] = None) -> Dict[str, Any]:
        workspace = self.base.get_workspace(workspace_id)
        workspace["templates"] = [
            self._enrich_template(workspace["id"], item)
            for item in workspace.get("templates", [])
        ]
        return workspace

    def _record_revision(
        self,
        connection: sqlite3.Connection,
        workspace_id: str,
        template: Mapping[str, Any],
        *,
        composite: Any = None,
        fingerprint: Any = None,
        comment: str = "",
        actor_user_id: Optional[str] = None,
    ) -> int:
        profile = self._profile(connection, workspace_id, str(template["id"]))
        revision_no = int(profile.get("current_revision") or 0) + 1
        normalized_composite = normalize_composite_rules(
            profile["composite"] if composite is None else composite
        )
        normalized_fingerprint = (
            profile["fingerprint"] if fingerprint is None else _object(fingerprint, {})
        )
        connection.execute(
            """
            INSERT INTO template_profiles(
                workspace_id, template_id, composite_json, fingerprint_json,
                current_revision
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(workspace_id, template_id) DO UPDATE SET
                composite_json = excluded.composite_json,
                fingerprint_json = excluded.fingerprint_json,
                current_revision = excluded.current_revision
            """,
            (
                workspace_id, template["id"], _json(normalized_composite),
                _json(normalized_fingerprint), revision_no,
            ),
        )
        connection.execute(
            """
            INSERT INTO template_revisions(
                workspace_id, template_id, revision_no, name, description,
                layout_json, composite_json, fingerprint_json, comment,
                actor_user_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                workspace_id, template["id"], revision_no, template["name"],
                template.get("description", ""), _json(template["layout"]),
                _json(normalized_composite), _json(normalized_fingerprint),
                text(comment, 1000), actor_user_id, iso_now(),
            ),
        )
        return revision_no

    def create_template(self, workspace_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        template = self.base.create_template(workspace_id, payload)
        with self._transaction() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO template_profiles(workspace_id, template_id, current_revision) VALUES (?, ?, 0)",
                (workspace_id, template["id"]),
            )
            self._record_revision(
                connection,
                workspace_id,
                template,
                composite=payload.get("composite", []),
                fingerprint=payload.get("fingerprint", {}),
                comment=payload.get("comment", "Создан шаблон"),
                actor_user_id=payload.get("actor_user_id"),
            )
        return self._enrich_template(workspace_id, template)

    def update_template(self, workspace_id: str, template_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        before = next(
            (item for item in self.base.list_templates(workspace_id) if item["id"] == template_id),
            None,
        )
        template = self.base.update_template(workspace_id, template_id, payload)
        with self._transaction() as connection:
            self._record_revision(
                connection,
                workspace_id,
                template,
                composite=payload.get("composite") if "composite" in payload else None,
                fingerprint=payload.get("fingerprint") if "fingerprint" in payload else None,
                comment=payload.get("comment", "Изменена разметка"),
                actor_user_id=payload.get("actor_user_id"),
            )
            if before:
                self._audit_connection(
                    connection,
                    actor=None,
                    action="template.update",
                    entity_type="template",
                    entity_id=template_id,
                    workspace_id=workspace_id,
                    summary=f"Обновлён шаблон «{template['name']}»",
                    details={"layout_changes": layout_diff(before.get("layout", {}), template["layout"])},
                )
        return self._enrich_template(workspace_id, template)

    def import_templates(self, workspace_id: str, records: List[Dict[str, Any]], mode: str = "append") -> Dict[str, int]:
        result = self.base.import_templates(workspace_id, records, mode)
        with self._transaction() as connection:
            self._seed_template_profiles(connection)
        return result

    def duplicate_workspace(self, workspace_id: str, name: Optional[str] = None) -> Dict[str, Any]:
        result = self.base.duplicate_workspace(workspace_id, name)
        with self._transaction() as connection:
            self._seed_template_profiles(connection)
        return result

    def import_workspace(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        result = self.base.import_workspace(payload)
        with self._transaction() as connection:
            self._seed_template_profiles(connection)
        return result

    def list_template_revisions(self, workspace_id: str, template_id: str) -> List[Dict[str, Any]]:
        connection = self._connect()
        try:
            rows = connection.execute(
                """
                SELECT r.*, u.display_name AS actor_name
                FROM template_revisions r
                LEFT JOIN users u ON u.id = r.actor_user_id
                WHERE r.workspace_id = ? AND r.template_id = ?
                ORDER BY r.revision_no DESC
                """,
                (workspace_id, template_id),
            ).fetchall()
            result = []
            previous_layout: Optional[Dict[str, Any]] = None
            for row in reversed(rows):
                layout = _object(row["layout_json"], {})
                item = {
                    "id": int(row["id"]),
                    "revision_no": int(row["revision_no"]),
                    "name": row["name"],
                    "description": row["description"],
                    "layout": layout,
                    "composite": _object(row["composite_json"], []),
                    "fingerprint": _object(row["fingerprint_json"], {}),
                    "comment": row["comment"],
                    "actor_name": row["actor_name"] or "Система",
                    "created_at": row["created_at"],
                    "changes": layout_diff(previous_layout or {}, layout),
                }
                result.append(item)
                previous_layout = layout
            return list(reversed(result))
        finally:
            connection.close()

    def restore_template_revision(
        self,
        workspace_id: str,
        template_id: str,
        revision_no: int,
        *,
        actor_user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        connection = self._connect()
        try:
            row = connection.execute(
                """
                SELECT * FROM template_revisions
                WHERE workspace_id = ? AND template_id = ? AND revision_no = ?
                """,
                (workspace_id, template_id, revision_no),
            ).fetchone()
        finally:
            connection.close()
        if not row:
            raise WorkspaceNotFound("Версия шаблона не найдена.")
        return self.update_template(
            workspace_id,
            template_id,
            {
                "name": row["name"],
                "description": row["description"],
                "layout": _object(row["layout_json"], {}),
                "composite": _object(row["composite_json"], []),
                "fingerprint": _object(row["fingerprint_json"], {}),
                "comment": f"Восстановлена версия {revision_no}",
                "actor_user_id": actor_user_id,
            },
        )

    def record_template_evaluation(
        self,
        workspace_id: str,
        template_id: str,
        *,
        status: str,
        quality: float,
        lesson_count: int,
    ) -> None:
        column = {
            "success": "success_count",
            "warning": "warning_count",
            "error": "failure_count",
        }.get(status, "warning_count")
        with self._transaction() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO template_profiles(workspace_id, template_id) VALUES (?, ?)",
                (workspace_id, template_id),
            )
            row = connection.execute(
                "SELECT success_count + warning_count + failure_count AS uses, avg_quality FROM template_profiles WHERE workspace_id = ? AND template_id = ?",
                (workspace_id, template_id),
            ).fetchone()
            uses = int(row["uses"] or 0)
            average = (float(row["avg_quality"] or 0) * uses + float(quality)) / (uses + 1)
            connection.execute(
                f"""
                UPDATE template_profiles SET
                    {column} = {column} + 1,
                    total_lessons = total_lessons + ?,
                    avg_quality = ?,
                    last_used_at = ?
                WHERE workspace_id = ? AND template_id = ?
                """,
                (int(lesson_count), average, iso_now(), workspace_id, template_id),
            )

    # ------------------------------------------------------------------
    # Local users, sessions and audit
    # ------------------------------------------------------------------
    def user_count(self) -> int:
        connection = self._connect()
        try:
            return int(connection.execute("SELECT COUNT(*) FROM users WHERE is_active = 1").fetchone()[0])
        finally:
            connection.close()

    def bootstrap_admin(self, username: str, display_name: str, password: str) -> Dict[str, Any]:
        with self._transaction() as connection:
            if int(connection.execute("SELECT COUNT(*) FROM users").fetchone()[0]):
                raise WorkspaceError("Первоначальный администратор уже создан.")
            return self._create_user_connection(
                connection,
                username=username,
                display_name=display_name,
                password=password,
                role="admin",
            )

    def _create_user_connection(
        self,
        connection: sqlite3.Connection,
        *,
        username: str,
        display_name: str,
        password: str,
        role: str,
    ) -> Dict[str, Any]:
        normalized_username = text(username, 80).casefold()
        normalized_display = text(display_name, 160) or normalized_username
        if not normalized_username or not all(character.isalnum() or character in "._-" for character in normalized_username):
            raise WorkspaceError("Логин может содержать буквы, цифры, точку, дефис и подчёркивание.")
        if role not in VALID_ROLES:
            raise WorkspaceError("Неизвестная роль пользователя.")
        user_id = str(uuid.uuid4())
        stamp = iso_now()
        try:
            connection.execute(
                """
                INSERT INTO users(
                    id, username, display_name, password_hash, role,
                    is_active, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (
                    user_id, normalized_username, normalized_display,
                    hash_password(password), role, stamp, stamp,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise WorkspaceError("Пользователь с таким логином уже существует.") from exc
        return {
            "id": user_id,
            "username": normalized_username,
            "display_name": normalized_display,
            "role": role,
            "is_active": True,
            "created_at": stamp,
        }

    def create_user(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        with self._transaction() as connection:
            return self._create_user_connection(
                connection,
                username=str(payload.get("username") or ""),
                display_name=str(payload.get("display_name") or ""),
                password=str(payload.get("password") or ""),
                role=str(payload.get("role") or "viewer"),
            )

    def list_users(self) -> List[Dict[str, Any]]:
        connection = self._connect()
        try:
            return [dict(row) for row in connection.execute(
                """
                SELECT id, username, display_name, role, is_active,
                       created_at, updated_at, last_login_at
                FROM users ORDER BY display_name COLLATE NOCASE
                """
            ).fetchall()]
        finally:
            connection.close()

    def update_user(self, user_id: str, payload: Mapping[str, Any]) -> Dict[str, Any]:
        with self._transaction() as connection:
            row = connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            if not row:
                raise WorkspaceNotFound("Пользователь не найден.")
            display_name = text(payload.get("display_name"), 160) if "display_name" in payload else row["display_name"]
            role = str(payload.get("role") or row["role"])
            active = int(bool(payload.get("is_active"))) if "is_active" in payload else int(row["is_active"])
            if role not in VALID_ROLES:
                raise WorkspaceError("Неизвестная роль пользователя.")
            if row["role"] == "admin" and (role != "admin" or not active):
                admins = int(connection.execute(
                    "SELECT COUNT(*) FROM users WHERE role = 'admin' AND is_active = 1"
                ).fetchone()[0])
                if admins <= 1:
                    raise WorkspaceError("Нельзя отключить или понизить последнего администратора.")
            connection.execute(
                "UPDATE users SET display_name = ?, role = ?, is_active = ?, updated_at = ? WHERE id = ?",
                (display_name, role, active, iso_now(), user_id),
            )
            if "password" in payload and payload.get("password"):
                connection.execute(
                    "UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?",
                    (hash_password(str(payload["password"])), iso_now(), user_id),
                )
                connection.execute("DELETE FROM auth_sessions WHERE user_id = ?", (user_id,))
            updated = connection.execute(
                "SELECT id, username, display_name, role, is_active, created_at, updated_at, last_login_at FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
            return dict(updated)

    def authenticate(self, username: str, password: str) -> Optional[Dict[str, Any]]:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT * FROM users WHERE username = ? COLLATE NOCASE AND is_active = 1",
                (text(username, 80),),
            ).fetchone()
            if not row or not verify_password(password, row["password_hash"]):
                return None
            return {
                "id": row["id"], "username": row["username"],
                "display_name": row["display_name"], "role": row["role"],
                "is_active": bool(row["is_active"]),
            }
        finally:
            connection.close()

    def create_session(self, user_id: str) -> str:
        raw, digest = new_session_token()
        with self._transaction() as connection:
            stamp = iso_now()
            connection.execute(
                """
                INSERT INTO auth_sessions(token_hash, user_id, created_at, expires_at, last_seen_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (digest, user_id, stamp, session_expiry(), stamp),
            )
            connection.execute(
                "UPDATE users SET last_login_at = ?, updated_at = ? WHERE id = ?",
                (stamp, stamp, user_id),
            )
        return raw

    def session_user(self, raw_token: str) -> Optional[Dict[str, Any]]:
        if not raw_token:
            return None
        connection = self._connect()
        try:
            row = connection.execute(
                """
                SELECT u.id, u.username, u.display_name, u.role, u.is_active,
                       s.expires_at
                FROM auth_sessions s
                JOIN users u ON u.id = s.user_id
                WHERE s.token_hash = ?
                """,
                (token_digest(raw_token),),
            ).fetchone()
            if not row or not row["is_active"]:
                return None
            if datetime.fromisoformat(row["expires_at"]) <= datetime.now(timezone.utc):
                return None
            connection.execute(
                "UPDATE auth_sessions SET last_seen_at = ? WHERE token_hash = ?",
                (iso_now(), token_digest(raw_token)),
            )
            connection.commit()
            return {
                "id": row["id"], "username": row["username"],
                "display_name": row["display_name"], "role": row["role"],
                "is_active": bool(row["is_active"]),
            }
        finally:
            connection.close()

    def delete_session(self, raw_token: str) -> None:
        if not raw_token:
            return
        with self._transaction() as connection:
            connection.execute(
                "DELETE FROM auth_sessions WHERE token_hash = ?",
                (token_digest(raw_token),),
            )

    def _audit_connection(
        self,
        connection: sqlite3.Connection,
        *,
        actor: Optional[Mapping[str, Any]],
        action: str,
        entity_type: str,
        entity_id: Optional[str],
        workspace_id: Optional[str],
        summary: str,
        details: Any = None,
    ) -> None:
        actor_id = str(actor.get("id")) if actor and actor.get("id") else None
        actor_name = str(actor.get("display_name") or actor.get("username")) if actor else "Система"
        connection.execute(
            """
            INSERT INTO audit_log(
                workspace_id, actor_user_id, actor_name, action, entity_type,
                entity_id, summary, details_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                workspace_id, actor_id, actor_name, action, entity_type,
                entity_id, text(summary, 500), _json(details or {}), iso_now(),
            ),
        )

    def audit(
        self,
        *,
        actor: Optional[Mapping[str, Any]],
        action: str,
        entity_type: str,
        entity_id: Optional[str] = None,
        workspace_id: Optional[str] = None,
        summary: str,
        details: Any = None,
    ) -> None:
        with self._transaction() as connection:
            self._audit_connection(
                connection,
                actor=actor,
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                workspace_id=workspace_id,
                summary=summary,
                details=details,
            )

    def list_audit(
        self,
        *,
        workspace_id: Optional[str] = None,
        limit: int = 200,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        connection = self._connect()
        try:
            if workspace_id:
                rows = connection.execute(
                    """
                    SELECT * FROM audit_log WHERE workspace_id = ?
                    ORDER BY id DESC LIMIT ? OFFSET ?
                    """,
                    (workspace_id, min(limit, 1000), max(offset, 0)),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM audit_log ORDER BY id DESC LIMIT ? OFFSET ?",
                    (min(limit, 1000), max(offset, 0)),
                ).fetchall()
            result = []
            for row in rows:
                item = dict(row)
                item["details"] = _object(item.pop("details_json"), {})
                result.append(item)
            return result
        finally:
            connection.close()

    # ------------------------------------------------------------------
    # Import preview and transactional commit
    # ------------------------------------------------------------------
    def create_import_job(
        self,
        *,
        workspace_id: str,
        actor: Optional[Mapping[str, Any]],
        kind: str,
        filename: str,
        source: Mapping[str, Any],
        mapping: Mapping[str, Any],
        preview: Mapping[str, Any],
    ) -> Dict[str, Any]:
        if kind not in {"teachers", "templates", "workspace"}:
            raise WorkspaceError("Неизвестный тип импорта.")
        job_id = str(uuid.uuid4())
        stamp = iso_now()
        with self._transaction() as connection:
            connection.execute(
                """
                INSERT INTO import_jobs(
                    id, workspace_id, actor_user_id, kind, filename,
                    source_json, mapping_json, preview_json, status,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'preview', ?, ?)
                """,
                (
                    job_id, workspace_id,
                    actor.get("id") if actor else None,
                    kind, Path(filename).name, _json(source), _json(mapping),
                    _json(preview), stamp, stamp,
                ),
            )
            self._audit_connection(
                connection,
                actor=actor,
                action="import.preview",
                entity_type="import_job",
                entity_id=job_id,
                workspace_id=workspace_id,
                summary=f"Подготовлен предварительный импорт «{Path(filename).name}»",
                details={"kind": kind, "counts": preview.get("counts", {})},
            )
        return self.get_import_job(job_id)

    def get_import_job(self, job_id: str) -> Dict[str, Any]:
        connection = self._connect()
        try:
            row = connection.execute("SELECT * FROM import_jobs WHERE id = ?", (job_id,)).fetchone()
            if not row:
                raise WorkspaceNotFound("Предварительный импорт не найден.")
            return {
                "id": row["id"], "workspace_id": row["workspace_id"],
                "kind": row["kind"], "filename": row["filename"],
                "source": _object(row["source_json"], {}),
                "mapping": _object(row["mapping_json"], {}),
                "preview": _object(row["preview_json"], {}),
                "status": row["status"], "created_at": row["created_at"],
                "updated_at": row["updated_at"], "committed_at": row["committed_at"],
            }
        finally:
            connection.close()

    def update_import_preview(
        self,
        job_id: str,
        *,
        mapping: Mapping[str, Any],
        preview: Mapping[str, Any],
    ) -> Dict[str, Any]:
        with self._transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE import_jobs SET mapping_json = ?, preview_json = ?, updated_at = ?
                WHERE id = ? AND status = 'preview'
                """,
                (_json(mapping), _json(preview), iso_now(), job_id),
            )
            if cursor.rowcount == 0:
                raise WorkspaceError("Импорт уже применён или не найден.")
        return self.get_import_job(job_id)

    def commit_import_job(
        self,
        job_id: str,
        *,
        actor: Optional[Mapping[str, Any]],
        decisions: Mapping[str, str],
    ) -> Dict[str, Any]:
        with self._transaction() as connection:
            row = connection.execute("SELECT * FROM import_jobs WHERE id = ?", (job_id,)).fetchone()
            if not row:
                raise WorkspaceNotFound("Предварительный импорт не найден.")
            if row["status"] != "preview":
                raise WorkspaceError("Этот импорт уже был применён.")
            preview = _object(row["preview_json"], {})
            workspace_id = row["workspace_id"]
            result = {"added": 0, "updated": 0, "skipped": 0, "errors": 0}
            if row["kind"] == "teachers":
                existing_rows = connection.execute(
                    "SELECT * FROM teachers WHERE workspace_id = ? ORDER BY id",
                    (workspace_id,),
                ).fetchall()
                existing_by_key = {
                    str(item["normalized_name"]): dict(item)
                    for item in existing_rows
                }
                next_id = int(connection.execute(
                    "SELECT COALESCE(MAX(id), 0) + 1 FROM teachers WHERE workspace_id = ?",
                    (workspace_id,),
                ).fetchone()[0])
                for item in preview.get("rows", []):
                    incoming = item.get("teacher")
                    if not isinstance(incoming, dict):
                        result["errors"] += 1
                        continue
                    decision = decisions.get(str(item.get("row")), item.get("decision", "skip"))
                    key = teacher_key(incoming)
                    current = existing_by_key.get(key)
                    resolved = apply_teacher_decision(current, incoming, decision)
                    if resolved is None:
                        result["skipped"] += 1
                        continue
                    if current:
                        teacher = normalize_teacher(resolved, int(current["id"]))
                        connection.execute(
                            """
                            UPDATE teachers SET short_name = ?, full_name = ?, position = ?,
                                rank = ?, academic_degree = ?, normalized_name = ?
                            WHERE workspace_id = ? AND id = ?
                            """,
                            (
                                teacher["short_name"], teacher["full_name"], teacher["position"],
                                teacher["rank"], teacher["academic_degree"], teacher_key(teacher),
                                workspace_id, teacher["id"],
                            ),
                        )
                        result["updated"] += 1
                    else:
                        teacher = normalize_teacher(resolved, next_id)
                        self.base._insert_teacher(connection, workspace_id, teacher)
                        existing_by_key[teacher_key(teacher)] = teacher
                        next_id += 1
                        result["added"] += 1
            elif row["kind"] == "templates":
                current_templates = {
                    str(item["name"]).casefold(): item
                    for item in self.base._workspace(connection, workspace_id)["templates"]
                }
                for item in preview.get("rows", []):
                    incoming = item.get("template")
                    if not isinstance(incoming, dict):
                        result["errors"] += 1
                        continue
                    decision = decisions.get(str(item.get("row")), item.get("decision", "skip"))
                    if decision == "skip":
                        result["skipped"] += 1
                        continue
                    current = current_templates.get(str(incoming.get("name", "")).casefold())
                    if current:
                        template = normalize_template({**current, **incoming}, current["id"])
                        connection.execute(
                            """
                            UPDATE templates SET name = ?, description = ?, layout_json = ?, updated_at = ?
                            WHERE workspace_id = ? AND id = ?
                            """,
                            (
                                template["name"], template["description"], _json(template["layout"]),
                                template["updated_at"], workspace_id, template["id"],
                            ),
                        )
                        self._record_revision(
                            connection, workspace_id, template,
                            composite=incoming.get("composite", []),
                            comment="Импортирована новая версия шаблона",
                            actor_user_id=actor.get("id") if actor else None,
                        )
                        result["updated"] += 1
                    else:
                        template = normalize_template(incoming, str(uuid.uuid4()))
                        self.base._insert_template(connection, workspace_id, template)
                        connection.execute(
                            "INSERT INTO template_profiles(workspace_id, template_id, current_revision) VALUES (?, ?, 0)",
                            (workspace_id, template["id"]),
                        )
                        self._record_revision(
                            connection, workspace_id, template,
                            composite=incoming.get("composite", []),
                            comment="Импортирован шаблон",
                            actor_user_id=actor.get("id") if actor else None,
                        )
                        current_templates[template["name"].casefold()] = template
                        result["added"] += 1
            else:
                raise WorkspaceError("Импорт целого пространства выполняется через основной API.")

            stamp = iso_now()
            connection.execute(
                "UPDATE import_jobs SET status = 'committed', committed_at = ?, updated_at = ? WHERE id = ?",
                (stamp, stamp, job_id),
            )
            connection.execute("UPDATE workspaces SET updated_at = ? WHERE id = ?", (stamp, workspace_id))
            self.base._write_compatibility_mirrors(connection)
            self._audit_connection(
                connection,
                actor=actor,
                action="import.commit",
                entity_type="import_job",
                entity_id=job_id,
                workspace_id=workspace_id,
                summary=f"Применён импорт «{row['filename']}»",
                details=result,
            )
            return result

    def list_import_jobs(self, workspace_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        connection = self._connect()
        try:
            rows = connection.execute(
                """
                SELECT id, kind, filename, status, created_at, updated_at, committed_at,
                       preview_json
                FROM import_jobs WHERE workspace_id = ?
                ORDER BY created_at DESC LIMIT ?
                """,
                (workspace_id, min(limit, 200)),
            ).fetchall()
            result = []
            for row in rows:
                preview = _object(row["preview_json"], {})
                result.append({
                    "id": row["id"], "kind": row["kind"], "filename": row["filename"],
                    "status": row["status"], "counts": preview.get("counts", {}),
                    "created_at": row["created_at"], "updated_at": row["updated_at"],
                    "committed_at": row["committed_at"],
                })
            return result
        finally:
            connection.close()

    # ------------------------------------------------------------------
    # Processing history and artifacts
    # ------------------------------------------------------------------
    def start_processing_run(
        self,
        *,
        workspace_id: str,
        session_id: str,
        actor: Optional[Mapping[str, Any]],
        source_count: int,
    ) -> str:
        run_id = str(uuid.uuid4())
        with self._transaction() as connection:
            connection.execute(
                """
                INSERT INTO processing_runs(
                    id, workspace_id, session_id, actor_user_id, status,
                    source_count, created_at
                ) VALUES (?, ?, ?, ?, 'running', ?, ?)
                """,
                (
                    run_id, workspace_id, session_id,
                    actor.get("id") if actor else None, int(source_count), iso_now(),
                ),
            )
        return run_id

    def record_processing_file(
        self,
        run_id: str,
        *,
        file_id: str,
        filename: str,
        file_path: Path,
        group_name: str,
        layout: Mapping[str, Any],
        report: Mapping[str, Any],
        template_match: Optional[Mapping[str, Any]] = None,
    ) -> None:
        template_match = dict(template_match or {})
        with self._transaction() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO processing_files(
                    run_id, file_id, filename, checksum, group_name, template_id,
                    template_revision, match_score, layout_json, report_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id, file_id, filename, _sha256(file_path), group_name,
                    template_match.get("template_id"),
                    template_match.get("revision_no"),
                    template_match.get("score"), _json(layout), _json(report),
                ),
            )

    def finish_processing_run(
        self,
        run_id: str,
        *,
        status: str,
        lesson_count: int,
        warning_count: int,
        error_count: int,
        selected_templates: Sequence[Mapping[str, Any]],
        report: Mapping[str, Any],
        artifacts: Sequence[Mapping[str, Any]],
        actor: Optional[Mapping[str, Any]],
    ) -> Dict[str, Any]:
        with self._transaction() as connection:
            connection.execute(
                """
                UPDATE processing_runs SET status = ?, lesson_count = ?,
                    warning_count = ?, error_count = ?, selected_templates_json = ?,
                    report_json = ?, completed_at = ? WHERE id = ?
                """,
                (
                    status, int(lesson_count), int(warning_count), int(error_count),
                    _json(list(selected_templates)), _json(report), iso_now(), run_id,
                ),
            )
            for artifact in artifacts:
                path = Path(str(artifact["path"]))
                connection.execute(
                    """
                    INSERT INTO processing_artifacts(
                        id, run_id, kind, filename, checksum, size, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid.uuid4()), run_id, artifact.get("kind", "schedule"),
                        path.name, _sha256(path), path.stat().st_size, iso_now(),
                    ),
                )
            row = connection.execute(
                "SELECT workspace_id FROM processing_runs WHERE id = ?", (run_id,)
            ).fetchone()
            self._audit_connection(
                connection,
                actor=actor,
                action="processing.finish",
                entity_type="processing_run",
                entity_id=run_id,
                workspace_id=row["workspace_id"] if row else None,
                summary=f"Обработка завершена: {lesson_count} занятий",
                details={
                    "status": status, "warnings": warning_count,
                    "errors": error_count, "artifacts": len(artifacts),
                },
            )
        return self.get_processing_run(run_id)

    def list_processing_runs(self, workspace_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        connection = self._connect()
        try:
            rows = connection.execute(
                """
                SELECT r.*, u.display_name AS actor_name,
                       (SELECT COUNT(*) FROM processing_artifacts a WHERE a.run_id = r.id) AS artifact_count
                FROM processing_runs r
                LEFT JOIN users u ON u.id = r.actor_user_id
                WHERE r.workspace_id = ?
                ORDER BY r.created_at DESC LIMIT ?
                """,
                (workspace_id, min(limit, 500)),
            ).fetchall()
            return [
                {
                    **dict(row),
                    "selected_templates": _object(row["selected_templates_json"], []),
                    "report": _object(row["report_json"], {}),
                }
                for row in rows
            ]
        finally:
            connection.close()

    def get_processing_run(self, run_id: str) -> Dict[str, Any]:
        connection = self._connect()
        try:
            row = connection.execute(
                """
                SELECT r.*, u.display_name AS actor_name
                FROM processing_runs r
                LEFT JOIN users u ON u.id = r.actor_user_id
                WHERE r.id = ?
                """,
                (run_id,),
            ).fetchone()
            if not row:
                raise WorkspaceNotFound("Запуск обработки не найден.")
            files = []
            for item in connection.execute(
                "SELECT * FROM processing_files WHERE run_id = ? ORDER BY filename",
                (run_id,),
            ).fetchall():
                record = dict(item)
                record["layout"] = _object(record.pop("layout_json"), {})
                record["report"] = _object(record.pop("report_json"), {})
                files.append(record)
            artifacts = [dict(item) for item in connection.execute(
                "SELECT * FROM processing_artifacts WHERE run_id = ? ORDER BY created_at",
                (run_id,),
            ).fetchall()]
            result = dict(row)
            result["selected_templates"] = _object(result.pop("selected_templates_json"), [])
            result["report"] = _object(result.pop("report_json"), {})
            result["files"] = files
            result["artifacts"] = artifacts
            return result
        finally:
            connection.close()
