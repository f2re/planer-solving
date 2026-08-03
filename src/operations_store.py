"""Operational persistence for authentication, imports, revisions and history."""
from __future__ import annotations

from base64 import b64decode, b64encode
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import sqlite3
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional, Sequence
import uuid

from .operations_domain import (
    AuthenticatedUser,
    ImportJobNotFound,
    InvalidCredentials,
    OperationsError,
    ProcessingRunNotFound,
    RevisionNotFound,
    ROLE_ADMIN,
    validate_role,
)
from .template_definition import (
    definition_summary,
    diff_values,
    normalize_definition,
    stable_hash,
)
from .workspace_domain import (
    WorkspaceError,
    normalize_teacher,
    normalize_template,
    now,
    teacher_key,
    text,
)

OPERATIONS_SCHEMA_VERSION = 4
PASSWORD_ITERATIONS = 310_000
SESSION_HOURS = 16


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _iso(value: datetime | None = None) -> str:
    return (value or _utc_now()).isoformat()


def _json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)


def _loads(payload: Any, fallback: Any) -> Any:
    if payload in (None, ""):
        return deepcopy(fallback)
    try:
        return json.loads(str(payload))
    except (TypeError, ValueError, json.JSONDecodeError):
        return deepcopy(fallback)


def _atomic_write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2, default=str)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _password_hash(password: str, salt: bytes | None = None) -> tuple[str, str]:
    value = str(password or "")
    if len(value) < 10:
        raise OperationsError("Пароль должен содержать не менее 10 символов.")
    selected_salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        value.encode("utf-8"),
        selected_salt,
        PASSWORD_ITERATIONS,
    )
    return b64encode(selected_salt).decode("ascii"), b64encode(digest).decode("ascii")


def _verify_password(password: str, salt_text: str, digest_text: str) -> bool:
    try:
        salt = b64decode(salt_text.encode("ascii"))
        expected = b64decode(digest_text.encode("ascii"))
    except Exception:
        return False
    actual = hashlib.pbkdf2_hmac(
        "sha256",
        str(password or "").encode("utf-8"),
        salt,
        PASSWORD_ITERATIONS,
    )
    return hmac.compare_digest(actual, expected)


class OperationsStore:
    """Shared operational services backed by the Planner SQLite database."""

    def __init__(
        self,
        database_path: Path,
        legacy_json_path: Path | None = None,
        legacy_teachers_path: Path | None = None,
    ) -> None:
        self.path = Path(database_path)
        self.legacy_json = Path(legacy_json_path) if legacy_json_path else None
        self.legacy_teachers = Path(legacy_teachers_path) if legacy_teachers_path else None
        self._migrate()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
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

    @staticmethod
    def _meta(connection: sqlite3.Connection, key: str) -> Optional[str]:
        row = connection.execute("SELECT value FROM metadata WHERE key = ?", (key,)).fetchone()
        return str(row["value"]) if row else None

    @staticmethod
    def _set_meta(connection: sqlite3.Connection, key: str, value: str) -> None:
        connection.execute(
            "INSERT INTO metadata(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )

    def _migrate(self) -> None:
        with self.transaction() as connection:
            current = int(self._meta(connection, "operations_schema_version") or 0)
            if current > OPERATIONS_SCHEMA_VERSION:
                raise OperationsError(
                    f"Операционная схема имеет версию {current}, поддерживается "
                    f"{OPERATIONS_SCHEMA_VERSION}."
                )
            while current < OPERATIONS_SCHEMA_VERSION:
                migration = getattr(self, f"_migrate_{current}_to_{current + 1}")
                migration(connection)
                current += 1
                self._set_meta(connection, "operations_schema_version", str(current))
            self._bootstrap_template_revisions(connection)

    @staticmethod
    def _migrate_0_to_1(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                username TEXT NOT NULL COLLATE NOCASE UNIQUE,
                display_name TEXT NOT NULL,
                password_salt TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('admin','operator','viewer')),
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_login_at TEXT
            );

            CREATE TABLE IF NOT EXISTS auth_sessions (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                csrf_token TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_auth_sessions_user ON auth_sessions(user_id);
            CREATE INDEX IF NOT EXISTS idx_auth_sessions_expiry ON auth_sessions(expires_at);

            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workspace_id TEXT,
                user_id TEXT,
                action TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                entity_id TEXT,
                summary TEXT NOT NULL,
                details_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE SET NULL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE SET NULL
            );
            CREATE INDEX IF NOT EXISTS idx_audit_workspace_time
                ON audit_log(workspace_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_audit_user_time
                ON audit_log(user_id, created_at DESC);

            CREATE TABLE IF NOT EXISTS import_jobs (
                id TEXT PRIMARY KEY,
                workspace_id TEXT,
                user_id TEXT,
                kind TEXT NOT NULL,
                filename TEXT NOT NULL,
                source_path TEXT,
                source_json TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                mapping_json TEXT NOT NULL DEFAULT '{}',
                evaluation_json TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'preview',
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                committed_at TEXT,
                FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE SET NULL
            );
            CREATE INDEX IF NOT EXISTS idx_import_jobs_expiry ON import_jobs(expires_at);
            """
        )

    @staticmethod
    def _migrate_1_to_2(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS template_revisions (
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                template_id TEXT NOT NULL,
                revision_number INTEGER NOT NULL,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                definition_json TEXT NOT NULL,
                definition_hash TEXT NOT NULL,
                summary_json TEXT NOT NULL DEFAULT '{}',
                comment TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL DEFAULT 'manual',
                author_user_id TEXT,
                created_at TEXT NOT NULL,
                UNIQUE(template_id, revision_number),
                FOREIGN KEY(workspace_id, template_id)
                    REFERENCES templates(workspace_id, id) ON DELETE CASCADE,
                FOREIGN KEY(author_user_id) REFERENCES users(id) ON DELETE SET NULL
            );
            CREATE INDEX IF NOT EXISTS idx_template_revisions_template
                ON template_revisions(template_id, revision_number DESC);

            CREATE TABLE IF NOT EXISTS template_learning (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                workspace_id TEXT NOT NULL,
                template_id TEXT NOT NULL,
                revision_id TEXT,
                workbook_signature TEXT,
                sheet_signature TEXT,
                fingerprint_json TEXT NOT NULL DEFAULT '{}',
                outcome TEXT NOT NULL,
                score REAL NOT NULL DEFAULT 0,
                quality_percent INTEGER NOT NULL DEFAULT 0,
                metrics_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                FOREIGN KEY(workspace_id, template_id)
                    REFERENCES templates(workspace_id, id) ON DELETE CASCADE,
                FOREIGN KEY(revision_id) REFERENCES template_revisions(id) ON DELETE SET NULL
            );
            CREATE INDEX IF NOT EXISTS idx_template_learning_template
                ON template_learning(template_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_template_learning_signature
                ON template_learning(workbook_signature, template_id);
            """
        )
        columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(templates)").fetchall()
        }
        if "current_revision_id" not in columns:
            connection.execute("ALTER TABLE templates ADD COLUMN current_revision_id TEXT")
        if "success_count" not in columns:
            connection.execute("ALTER TABLE templates ADD COLUMN success_count INTEGER NOT NULL DEFAULT 0")
        if "failure_count" not in columns:
            connection.execute("ALTER TABLE templates ADD COLUMN failure_count INTEGER NOT NULL DEFAULT 0")
        if "last_used_at" not in columns:
            connection.execute("ALTER TABLE templates ADD COLUMN last_used_at TEXT")

    @staticmethod
    def _migrate_2_to_3(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS processing_runs (
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                user_id TEXT,
                source_session_id TEXT,
                status TEXT NOT NULL,
                message TEXT NOT NULL DEFAULT '',
                settings_json TEXT NOT NULL DEFAULT '{}',
                total_files INTEGER NOT NULL DEFAULT 0,
                success_files INTEGER NOT NULL DEFAULT 0,
                warning_files INTEGER NOT NULL DEFAULT 0,
                error_files INTEGER NOT NULL DEFAULT 0,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE SET NULL
            );
            CREATE INDEX IF NOT EXISTS idx_processing_runs_workspace
                ON processing_runs(workspace_id, started_at DESC);

            CREATE TABLE IF NOT EXISTS processing_files (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                original_name TEXT NOT NULL,
                group_name TEXT NOT NULL,
                source_sha256 TEXT NOT NULL,
                source_path TEXT NOT NULL,
                template_id TEXT,
                template_revision_id TEXT,
                component_id TEXT,
                layout_json TEXT NOT NULL,
                analysis_json TEXT NOT NULL DEFAULT '{}',
                validation_json TEXT NOT NULL DEFAULT '{}',
                lesson_count INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL,
                message TEXT NOT NULL DEFAULT '',
                FOREIGN KEY(run_id) REFERENCES processing_runs(id) ON DELETE CASCADE,
                FOREIGN KEY(template_revision_id) REFERENCES template_revisions(id) ON DELETE SET NULL
            );
            CREATE INDEX IF NOT EXISTS idx_processing_files_run ON processing_files(run_id);
            CREATE INDEX IF NOT EXISTS idx_processing_files_hash ON processing_files(source_sha256);

            CREATE TABLE IF NOT EXISTS processing_artifacts (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                filename TEXT NOT NULL,
                stored_path TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                size INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(run_id) REFERENCES processing_runs(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_processing_artifacts_run
                ON processing_artifacts(run_id, created_at);
            """
        )

    @staticmethod
    def _migrate_3_to_4(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS format_rules (
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                template_id TEXT NOT NULL,
                revision_id TEXT,
                component_id TEXT,
                workbook_signature TEXT,
                sheet_signature TEXT,
                fingerprint_json TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                priority INTEGER NOT NULL DEFAULT 0,
                success_count INTEGER NOT NULL DEFAULT 0,
                failure_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(workspace_id, template_id)
                    REFERENCES templates(workspace_id, id) ON DELETE CASCADE,
                FOREIGN KEY(revision_id) REFERENCES template_revisions(id) ON DELETE SET NULL
            );
            CREATE INDEX IF NOT EXISTS idx_format_rules_workspace
                ON format_rules(workspace_id, enabled, priority DESC);
            CREATE INDEX IF NOT EXISTS idx_format_rules_signature
                ON format_rules(workbook_signature, sheet_signature);
            """
        )

    def _bootstrap_template_revisions(self, connection: sqlite3.Connection) -> None:
        rows = connection.execute(
            """
            SELECT workspace_id, id, name, description, layout_json, created_at, updated_at,
                   current_revision_id
            FROM templates
            """
        ).fetchall()
        for row in rows:
            existing = connection.execute(
                "SELECT id FROM template_revisions WHERE template_id = ? LIMIT 1",
                (row["id"],),
            ).fetchone()
            if existing:
                if not row["current_revision_id"]:
                    latest = connection.execute(
                        "SELECT id FROM template_revisions WHERE template_id = ? "
                        "ORDER BY revision_number DESC LIMIT 1",
                        (row["id"],),
                    ).fetchone()
                    if latest:
                        connection.execute(
                            "UPDATE templates SET current_revision_id = ? "
                            "WHERE workspace_id = ? AND id = ?",
                            (latest["id"], row["workspace_id"], row["id"]),
                        )
                continue
            raw_definition = _loads(row["layout_json"], {})
            try:
                definition = normalize_definition(raw_definition)
            except ValueError:
                definition = normalize_definition({"sheet_name": ""})
            revision_id = str(uuid.uuid4())
            connection.execute(
                """
                INSERT INTO template_revisions(
                    id, workspace_id, template_id, revision_number, name, description,
                    definition_json, definition_hash, summary_json, comment, source,
                    author_user_id, created_at
                ) VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?, ?, 'bootstrap', NULL, ?)
                """,
                (
                    revision_id,
                    row["workspace_id"],
                    row["id"],
                    row["name"],
                    row["description"],
                    _json(definition),
                    stable_hash(definition),
                    _json(definition_summary(definition)),
                    "Начальная ревизия, созданная при обновлении системы.",
                    row["updated_at"] or row["created_at"] or now(),
                ),
            )
            connection.execute(
                "UPDATE templates SET layout_json = ?, current_revision_id = ? "
                "WHERE workspace_id = ? AND id = ?",
                (_json(definition), revision_id, row["workspace_id"], row["id"]),
            )

    # ------------------------------------------------------------------ auth

    def user_count(self) -> int:
        connection = self._connect()
        try:
            return int(connection.execute("SELECT COUNT(*) FROM users").fetchone()[0])
        finally:
            connection.close()

    def bootstrap_admin(self, username: str, display_name: str, password: str) -> Dict[str, Any]:
        with self.transaction() as connection:
            if int(connection.execute("SELECT COUNT(*) FROM users").fetchone()[0]):
                raise OperationsError("Первоначальный администратор уже создан.")
            user = self._insert_user(
                connection,
                username=username,
                display_name=display_name,
                password=password,
                role=ROLE_ADMIN,
            )
            self._audit(
                connection,
                user["id"],
                "bootstrap",
                "user",
                user["id"],
                None,
                "Создан первоначальный администратор.",
                {"username": user["username"]},
            )
            return user

    def _insert_user(
        self,
        connection: sqlite3.Connection,
        *,
        username: str,
        display_name: str,
        password: str,
        role: str,
    ) -> Dict[str, Any]:
        normalized_username = text(username, 80).casefold()
        if not normalized_username or not all(
            character.isalnum() or character in "._-" for character in normalized_username
        ):
            raise OperationsError(
                "Логин должен содержать буквы, цифры, точку, дефис или подчёркивание."
            )
        selected_display_name = text(display_name, 160) or normalized_username
        selected_role = validate_role(role)
        salt, digest = _password_hash(password)
        stamp = _iso()
        user_id = str(uuid.uuid4())
        try:
            connection.execute(
                """
                INSERT INTO users(
                    id, username, display_name, password_salt, password_hash,
                    role, active, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (
                    user_id, normalized_username, selected_display_name, salt, digest,
                    selected_role, stamp, stamp,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise OperationsError("Пользователь с таким логином уже существует.") from exc
        return {
            "id": user_id,
            "username": normalized_username,
            "display_name": selected_display_name,
            "role": selected_role,
            "active": True,
            "created_at": stamp,
            "updated_at": stamp,
            "last_login_at": None,
        }

    def create_user(
        self,
        *,
        username: str,
        display_name: str,
        password: str,
        role: str,
        actor_user_id: str,
    ) -> Dict[str, Any]:
        with self.transaction() as connection:
            user = self._insert_user(
                connection,
                username=username,
                display_name=display_name,
                password=password,
                role=role,
            )
            self._audit(
                connection, actor_user_id, "create", "user", user["id"], None,
                f"Создан пользователь {user['display_name']}.",
                {"username": user["username"], "role": user["role"]},
            )
            return user

    def list_users(self) -> List[Dict[str, Any]]:
        connection = self._connect()
        try:
            return [dict(row) for row in connection.execute(
                """
                SELECT id, username, display_name, role, active,
                       created_at, updated_at, last_login_at
                FROM users ORDER BY active DESC, display_name COLLATE NOCASE
                """
            ).fetchall()]
        finally:
            connection.close()

    def update_user(
        self,
        user_id: str,
        payload: Mapping[str, Any],
        actor_user_id: str,
    ) -> Dict[str, Any]:
        with self.transaction() as connection:
            row = connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            if not row:
                raise OperationsError("Пользователь не найден.")
            display_name = text(payload.get("display_name"), 160) if "display_name" in payload else row["display_name"]
            role = validate_role(payload.get("role")) if "role" in payload else row["role"]
            active = int(bool(payload.get("active"))) if "active" in payload else int(row["active"])
            if user_id == actor_user_id and not active:
                raise OperationsError("Нельзя отключить текущего пользователя.")
            if row["role"] == ROLE_ADMIN and (role != ROLE_ADMIN or not active):
                active_admins = int(connection.execute(
                    "SELECT COUNT(*) FROM users WHERE role = 'admin' AND active = 1"
                ).fetchone()[0])
                if active_admins <= 1:
                    raise OperationsError("Нельзя отключить или понизить последнего администратора.")
            connection.execute(
                "UPDATE users SET display_name = ?, role = ?, active = ?, updated_at = ? WHERE id = ?",
                (display_name, role, active, _iso(), user_id),
            )
            if payload.get("password"):
                salt, digest = _password_hash(str(payload["password"]))
                connection.execute(
                    "UPDATE users SET password_salt = ?, password_hash = ?, updated_at = ? WHERE id = ?",
                    (salt, digest, _iso(), user_id),
                )
                connection.execute("DELETE FROM auth_sessions WHERE user_id = ?", (user_id,))
            self._audit(
                connection, actor_user_id, "update", "user", user_id, None,
                f"Изменён пользователь {display_name}.",
                {"role": role, "active": bool(active)},
            )
            updated = connection.execute(
                """
                SELECT id, username, display_name, role, active,
                       created_at, updated_at, last_login_at
                FROM users WHERE id = ?
                """,
                (user_id,),
            ).fetchone()
            return dict(updated)

    def authenticate(self, username: str, password: str) -> Dict[str, Any]:
        normalized = text(username, 80).casefold()
        with self.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM users WHERE username = ? COLLATE NOCASE",
                (normalized,),
            ).fetchone()
            if not row or not row["active"] or not _verify_password(
                password, row["password_salt"], row["password_hash"]
            ):
                raise InvalidCredentials("Неверный логин или пароль.")
            stamp = _iso()
            connection.execute(
                "UPDATE users SET last_login_at = ?, updated_at = ? WHERE id = ?",
                (stamp, stamp, row["id"]),
            )
            return {
                "id": row["id"],
                "username": row["username"],
                "display_name": row["display_name"],
                "role": row["role"],
                "active": True,
            }

    def create_session(self, user_id: str) -> Dict[str, Any]:
        with self.transaction() as connection:
            row = connection.execute(
                "SELECT id, username, display_name, role, active FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
            if not row or not row["active"]:
                raise InvalidCredentials("Пользователь отключён или удалён.")
            session_id = secrets.token_urlsafe(48)
            csrf_token = secrets.token_urlsafe(32)
            created = _utc_now()
            expires = created + timedelta(hours=SESSION_HOURS)
            connection.execute(
                """
                INSERT INTO auth_sessions(
                    id, user_id, csrf_token, created_at, expires_at, last_seen_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (session_id, user_id, csrf_token, _iso(created), _iso(expires), _iso(created)),
            )
            return {
                "session_id": session_id,
                "csrf_token": csrf_token,
                "expires_at": _iso(expires),
                "user": dict(row),
            }

    def session_user(self, session_id: str | None) -> Optional[AuthenticatedUser]:
        if not session_id:
            return None
        now_value = _iso()
        with self.transaction() as connection:
            connection.execute("DELETE FROM auth_sessions WHERE expires_at <= ?", (now_value,))
            row = connection.execute(
                """
                SELECT s.id AS session_id, s.csrf_token, s.expires_at,
                       u.id, u.username, u.display_name, u.role, u.active
                FROM auth_sessions s JOIN users u ON u.id = s.user_id
                WHERE s.id = ?
                """,
                (session_id,),
            ).fetchone()
            if not row or not row["active"]:
                return None
            connection.execute(
                "UPDATE auth_sessions SET last_seen_at = ? WHERE id = ?",
                (now_value, session_id),
            )
            return AuthenticatedUser(
                id=str(row["id"]),
                username=str(row["username"]),
                display_name=str(row["display_name"]),
                role=str(row["role"]),
                csrf_token=str(row["csrf_token"]),
            )

    def revoke_session(self, session_id: str | None) -> None:
        if not session_id:
            return
        with self.transaction() as connection:
            connection.execute("DELETE FROM auth_sessions WHERE id = ?", (session_id,))

    # --------------------------------------------------------------- auditing

    def _audit(
        self,
        connection: sqlite3.Connection,
        user_id: str | None,
        action: str,
        entity_type: str,
        entity_id: str | None,
        workspace_id: str | None,
        summary: str,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        connection.execute(
            """
            INSERT INTO audit_log(
                workspace_id, user_id, action, entity_type, entity_id,
                summary, details_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                workspace_id, user_id, action, entity_type, entity_id,
                text(summary, 500), _json(dict(details or {})), _iso(),
            ),
        )

    def record_audit(
        self,
        *,
        user_id: str | None,
        action: str,
        entity_type: str,
        entity_id: str | None,
        workspace_id: str | None,
        summary: str,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        with self.transaction() as connection:
            self._audit(
                connection, user_id, action, entity_type, entity_id,
                workspace_id, summary, details,
            )

    def list_audit(
        self,
        *,
        workspace_id: str | None = None,
        user_id: str | None = None,
        action: str | None = None,
        query: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        where: List[str] = []
        params: List[Any] = []
        if workspace_id:
            where.append("a.workspace_id = ?")
            params.append(workspace_id)
        if user_id:
            where.append("a.user_id = ?")
            params.append(user_id)
        if action:
            where.append("a.action = ?")
            params.append(action)
        if query:
            where.append("(a.summary LIKE ? OR a.entity_type LIKE ? OR a.entity_id LIKE ?)")
            token = f"%{query}%"
            params.extend([token, token, token])
        condition = f"WHERE {' AND '.join(where)}" if where else ""
        params.extend([max(1, min(int(limit), 500)), max(0, int(offset))])
        connection = self._connect()
        try:
            rows = connection.execute(
                f"""
                SELECT a.*, u.display_name AS user_display_name, u.username,
                       w.name AS workspace_name
                FROM audit_log a
                LEFT JOIN users u ON u.id = a.user_id
                LEFT JOIN workspaces w ON w.id = a.workspace_id
                {condition}
                ORDER BY a.id DESC LIMIT ? OFFSET ?
                """,
                params,
            ).fetchall()
            result = []
            for row in rows:
                item = dict(row)
                item["details"] = _loads(item.pop("details_json"), {})
                result.append(item)
            return result
        finally:
            connection.close()

    # --------------------------------------------------------------- imports

    def create_import_job(
        self,
        *,
        workspace_id: str | None,
        user_id: str,
        kind: str,
        filename: str,
        source_path: str | None,
        source: Any,
        metadata: Mapping[str, Any],
    ) -> Dict[str, Any]:
        job_id = str(uuid.uuid4())
        created = _utc_now()
        expires = created + timedelta(hours=24)
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO import_jobs(
                    id, workspace_id, user_id, kind, filename, source_path,
                    source_json, metadata_json, mapping_json, evaluation_json,
                    status, created_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, '{}', '{}', 'preview', ?, ?)
                """,
                (
                    job_id, workspace_id, user_id, kind, text(filename, 260), source_path,
                    _json(source), _json(dict(metadata)), _iso(created), _iso(expires),
                ),
            )
            self._audit(
                connection, user_id, "preview", "import", job_id, workspace_id,
                f"Подготовлен предварительный просмотр импорта «{filename}».",
                {"kind": kind},
            )
        return self.get_import_job(job_id)

    def get_import_job(self, job_id: str) -> Dict[str, Any]:
        connection = self._connect()
        try:
            row = connection.execute("SELECT * FROM import_jobs WHERE id = ?", (job_id,)).fetchone()
            if not row or str(row["expires_at"]) <= _iso():
                raise ImportJobNotFound("Предварительный импорт не найден или истёк.")
            item = dict(row)
            for source_key, target_key, fallback in (
                ("source_json", "source", []),
                ("metadata_json", "metadata", {}),
                ("mapping_json", "mapping", {}),
                ("evaluation_json", "evaluation", {}),
            ):
                item[target_key] = _loads(item.pop(source_key), fallback)
            return item
        finally:
            connection.close()

    def update_import_evaluation(
        self,
        job_id: str,
        *,
        mapping: Mapping[str, Any],
        evaluation: Mapping[str, Any],
        user_id: str,
    ) -> Dict[str, Any]:
        with self.transaction() as connection:
            row = connection.execute("SELECT * FROM import_jobs WHERE id = ?", (job_id,)).fetchone()
            if not row:
                raise ImportJobNotFound("Предварительный импорт не найден.")
            if row["user_id"] != user_id:
                raise OperationsError("Этот импорт создан другим пользователем.")
            connection.execute(
                """
                UPDATE import_jobs
                SET mapping_json = ?, evaluation_json = ?, status = 'review'
                WHERE id = ?
                """,
                (_json(dict(mapping)), _json(dict(evaluation)), job_id),
            )
        return self.get_import_job(job_id)

    def mark_import_committed(
        self,
        job_id: str,
        *,
        user_id: str,
        workspace_id: str | None,
        result: Mapping[str, Any],
    ) -> None:
        with self.transaction() as connection:
            connection.execute(
                """
                UPDATE import_jobs SET status = 'committed', committed_at = ?,
                    evaluation_json = ? WHERE id = ?
                """,
                (_iso(), _json(dict(result)), job_id),
            )
            self._audit(
                connection, user_id, "commit", "import", job_id, workspace_id,
                "Подтверждён массовый импорт.", dict(result),
            )

    # ----------------------------------------------------- mirrors and imports

    def _workspace_document(self, connection: sqlite3.Connection) -> Dict[str, Any]:
        default_row = connection.execute(
            "SELECT value FROM metadata WHERE key = 'default_workspace_id'"
        ).fetchone()
        default_id = str(default_row["value"]) if default_row else ""
        workspaces: List[Dict[str, Any]] = []
        for workspace_row in connection.execute(
            "SELECT * FROM workspaces ORDER BY created_at, id"
        ).fetchall():
            workspace_id = str(workspace_row["id"])
            teachers = [dict(row) for row in connection.execute(
                """
                SELECT id, short_name, full_name, position, rank, academic_degree
                FROM teachers WHERE workspace_id = ? ORDER BY id
                """,
                (workspace_id,),
            ).fetchall()]
            templates = []
            for row in connection.execute(
                """
                SELECT id, name, description, layout_json, created_at, updated_at
                FROM templates WHERE workspace_id = ? ORDER BY name COLLATE NOCASE
                """,
                (workspace_id,),
            ).fetchall():
                item = dict(row)
                item["layout"] = _loads(item.pop("layout_json"), {})
                templates.append(item)
            workspaces.append({
                "id": workspace_id,
                "name": workspace_row["name"],
                "color": workspace_row["color"],
                "description": workspace_row["description"] or "",
                "created_at": workspace_row["created_at"],
                "updated_at": workspace_row["updated_at"],
                "teachers": teachers,
                "templates": templates,
                "settings": {
                    "schedule_start_date": workspace_row["schedule_start_date"],
                    "schedule_end_date": workspace_row["schedule_end_date"],
                },
            })
        return {
            "version": 1,
            "default_workspace_id": default_id,
            "workspaces": workspaces,
        }

    def _write_mirrors(self, connection: sqlite3.Connection) -> None:
        document = self._workspace_document(connection)
        if self.legacy_json:
            _atomic_write(self.legacy_json, document)
        if self.legacy_teachers and document["workspaces"]:
            default = next(
                (
                    item for item in document["workspaces"]
                    if item["id"] == document["default_workspace_id"]
                ),
                document["workspaces"][0],
            )
            _atomic_write(self.legacy_teachers, default["teachers"])

    def commit_teacher_import(
        self,
        *,
        job_id: str,
        workspace_id: str,
        rows: Sequence[Mapping[str, Any]],
        decisions: Mapping[int, str],
        mode: str,
        user_id: str,
    ) -> Dict[str, Any]:
        if mode not in {"append", "replace"}:
            raise OperationsError("Неизвестный режим импорта.")
        with self.transaction() as connection:
            workspace = connection.execute(
                "SELECT id FROM workspaces WHERE id = ?", (workspace_id,)
            ).fetchone()
            if not workspace:
                raise WorkspaceError("Пространство не найдено.")
            if mode == "replace":
                connection.execute("DELETE FROM teachers WHERE workspace_id = ?", (workspace_id,))
            existing_rows = connection.execute(
                "SELECT * FROM teachers WHERE workspace_id = ?", (workspace_id,)
            ).fetchall()
            existing = {str(row["normalized_name"]): dict(row) for row in existing_rows}
            next_id = int(connection.execute(
                "SELECT COALESCE(MAX(id), 0) + 1 FROM teachers WHERE workspace_id = ?",
                (workspace_id,),
            ).fetchone()[0])
            counts = {"added": 0, "updated": 0, "merged": 0, "skipped": 0, "errors": 0}
            results: List[Dict[str, Any]] = []
            for index, raw in enumerate(rows):
                action = decisions.get(index, str(raw.get("suggested_action") or "add"))
                try:
                    normalized = normalize_teacher(dict(raw.get("record") or raw), next_id)
                except WorkspaceError as exc:
                    counts["errors"] += 1
                    results.append({"row_index": index, "action": "error", "message": str(exc)})
                    continue
                key = teacher_key(normalized)
                current = existing.get(key)
                if action == "skip":
                    counts["skipped"] += 1
                    results.append({"row_index": index, "action": "skip"})
                    continue
                if action in {"update", "merge"} and current:
                    updated = normalized
                    if action == "merge":
                        updated = normalize_teacher({
                            "short_name": normalized["short_name"] or current["short_name"],
                            "full_name": normalized["full_name"] or current["full_name"],
                            "position": normalized["position"] or current["position"],
                            "rank": normalized["rank"] or current["rank"],
                            "academic_degree": normalized["academic_degree"] or current["academic_degree"],
                        }, int(current["id"]))
                    connection.execute(
                        """
                        UPDATE teachers SET short_name = ?, full_name = ?, position = ?,
                            rank = ?, academic_degree = ?, normalized_name = ?
                        WHERE workspace_id = ? AND id = ?
                        """,
                        (
                            updated["short_name"], updated["full_name"], updated["position"],
                            updated["rank"], updated["academic_degree"], teacher_key(updated),
                            workspace_id, current["id"],
                        ),
                    )
                    counts["merged" if action == "merge" else "updated"] += 1
                    results.append({"row_index": index, "action": action, "teacher_id": current["id"]})
                    existing[key] = {**current, **updated}
                    continue
                if current:
                    counts["skipped"] += 1
                    results.append({
                        "row_index": index,
                        "action": "skip",
                        "message": "Преподаватель уже существует.",
                    })
                    continue
                normalized["id"] = next_id
                connection.execute(
                    """
                    INSERT INTO teachers(
                        workspace_id, id, short_name, full_name, position, rank,
                        academic_degree, normalized_name
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        workspace_id, next_id, normalized["short_name"], normalized["full_name"],
                        normalized["position"], normalized["rank"],
                        normalized["academic_degree"], key,
                    ),
                )
                existing[key] = {**normalized, "workspace_id": workspace_id}
                counts["added"] += 1
                results.append({"row_index": index, "action": "add", "teacher_id": next_id})
                next_id += 1
            connection.execute(
                "UPDATE workspaces SET updated_at = ? WHERE id = ?",
                (_iso(), workspace_id),
            )
            total = int(connection.execute(
                "SELECT COUNT(*) FROM teachers WHERE workspace_id = ?", (workspace_id,)
            ).fetchone()[0])
            result = {**counts, "total": total, "rows": results}
            connection.execute(
                "UPDATE import_jobs SET status = 'committed', committed_at = ?, "
                "evaluation_json = ? WHERE id = ?",
                (_iso(), _json(result), job_id),
            )
            self._audit(
                connection, user_id, "commit", "teacher_import", job_id, workspace_id,
                "Импортирован список преподавателей.", result,
            )
            self._write_mirrors(connection)
            return result

    # ------------------------------------------------------- template history

    def _current_template_row(
        self,
        connection: sqlite3.Connection,
        workspace_id: str,
        template_id: str,
    ) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM templates WHERE workspace_id = ? AND id = ?",
            (workspace_id, template_id),
        ).fetchone()
        if not row:
            raise WorkspaceError("Шаблон не найден.")
        return row

    def _insert_revision(
        self,
        connection: sqlite3.Connection,
        *,
        workspace_id: str,
        template_id: str,
        name: str,
        description: str,
        definition: Mapping[str, Any],
        comment: str,
        source: str,
        author_user_id: str | None,
    ) -> Dict[str, Any]:
        normalized = normalize_definition(definition)
        number = int(connection.execute(
            "SELECT COALESCE(MAX(revision_number), 0) + 1 "
            "FROM template_revisions WHERE template_id = ?",
            (template_id,),
        ).fetchone()[0])
        revision_id = str(uuid.uuid4())
        stamp = _iso()
        connection.execute(
            """
            INSERT INTO template_revisions(
                id, workspace_id, template_id, revision_number, name, description,
                definition_json, definition_hash, summary_json, comment, source,
                author_user_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                revision_id, workspace_id, template_id, number, name, description,
                _json(normalized), stable_hash(normalized),
                _json(definition_summary(normalized)), text(comment, 1000), source,
                author_user_id, stamp,
            ),
        )
        connection.execute(
            """
            UPDATE templates SET name = ?, description = ?, layout_json = ?,
                current_revision_id = ?, updated_at = ?
            WHERE workspace_id = ? AND id = ?
            """,
            (
                name, description, _json(normalized), revision_id, stamp,
                workspace_id, template_id,
            ),
        )
        return {
            "id": revision_id,
            "workspace_id": workspace_id,
            "template_id": template_id,
            "revision_number": number,
            "name": name,
            "description": description,
            "definition": normalized,
            "summary": definition_summary(normalized),
            "comment": text(comment, 1000),
            "source": source,
            "author_user_id": author_user_id,
            "created_at": stamp,
        }

    def create_template_with_revision(
        self,
        *,
        workspace_id: str,
        name: str,
        description: str,
        definition: Mapping[str, Any],
        comment: str,
        source: str,
        user_id: str,
    ) -> Dict[str, Any]:
        normalized_template = normalize_template({
            "name": name,
            "description": description,
            "layout": normalize_definition(definition),
        })
        with self.transaction() as connection:
            try:
                connection.execute(
                    """
                    INSERT INTO templates(
                        workspace_id, id, name, description, layout_json,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        workspace_id, normalized_template["id"], normalized_template["name"],
                        normalized_template["description"], _json(normalized_template["layout"]),
                        normalized_template["created_at"], normalized_template["updated_at"],
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise WorkspaceError("Шаблон с таким названием уже существует.") from exc
            revision = self._insert_revision(
                connection,
                workspace_id=workspace_id,
                template_id=normalized_template["id"],
                name=normalized_template["name"],
                description=normalized_template["description"],
                definition=normalized_template["layout"],
                comment=comment or "Создан шаблон.",
                source=source,
                author_user_id=user_id,
            )
            connection.execute("UPDATE workspaces SET updated_at = ? WHERE id = ?", (_iso(), workspace_id))
            self._audit(
                connection, user_id, "create", "template", normalized_template["id"], workspace_id,
                f"Создан шаблон «{normalized_template['name']}».",
                {"revision": revision["revision_number"]},
            )
            self._write_mirrors(connection)
            return {
                **normalized_template,
                "layout": revision["definition"],
                "current_revision_id": revision["id"],
                "revision_number": revision["revision_number"],
            }

    def update_template_with_revision(
        self,
        *,
        workspace_id: str,
        template_id: str,
        payload: Mapping[str, Any],
        comment: str,
        source: str,
        user_id: str,
    ) -> Dict[str, Any]:
        with self.transaction() as connection:
            current = self._current_template_row(connection, workspace_id, template_id)
            name = text(payload.get("name"), 160) if "name" in payload else str(current["name"])
            description = text(payload.get("description"), 1000) if "description" in payload else str(current["description"] or "")
            definition = (
                normalize_definition(payload["layout"])
                if isinstance(payload.get("layout"), Mapping)
                else normalize_definition(_loads(current["layout_json"], {}))
            )
            try:
                revision = self._insert_revision(
                    connection,
                    workspace_id=workspace_id,
                    template_id=template_id,
                    name=name,
                    description=description,
                    definition=definition,
                    comment=comment or "Изменён шаблон.",
                    source=source,
                    author_user_id=user_id,
                )
            except sqlite3.IntegrityError as exc:
                raise WorkspaceError("Шаблон с таким названием уже существует.") from exc
            connection.execute("UPDATE workspaces SET updated_at = ? WHERE id = ?", (_iso(), workspace_id))
            self._audit(
                connection, user_id, "update", "template", template_id, workspace_id,
                f"Создана ревизия {revision['revision_number']} шаблона «{name}».",
                {"revision_id": revision["id"], "source": source},
            )
            self._write_mirrors(connection)
            return {
                "id": template_id,
                "name": name,
                "description": description,
                "layout": definition,
                "current_revision_id": revision["id"],
                "revision_number": revision["revision_number"],
                "updated_at": revision["created_at"],
            }

    def list_template_revisions(
        self,
        workspace_id: str,
        template_id: str,
    ) -> List[Dict[str, Any]]:
        connection = self._connect()
        try:
            self._current_template_row(connection, workspace_id, template_id)
            rows = connection.execute(
                """
                SELECT r.*, u.display_name AS author_name
                FROM template_revisions r
                LEFT JOIN users u ON u.id = r.author_user_id
                WHERE r.workspace_id = ? AND r.template_id = ?
                ORDER BY r.revision_number DESC
                """,
                (workspace_id, template_id),
            ).fetchall()
            result = []
            for row in rows:
                item = dict(row)
                item["definition"] = _loads(item.pop("definition_json"), {})
                item["summary"] = _loads(item.pop("summary_json"), {})
                result.append(item)
            return result
        finally:
            connection.close()

    def get_template_revision(self, revision_id: str) -> Dict[str, Any]:
        connection = self._connect()
        try:
            row = connection.execute(
                """
                SELECT r.*, u.display_name AS author_name
                FROM template_revisions r
                LEFT JOIN users u ON u.id = r.author_user_id
                WHERE r.id = ?
                """,
                (revision_id,),
            ).fetchone()
            if not row:
                raise RevisionNotFound("Ревизия шаблона не найдена.")
            item = dict(row)
            item["definition"] = _loads(item.pop("definition_json"), {})
            item["summary"] = _loads(item.pop("summary_json"), {})
            return item
        finally:
            connection.close()

    def compare_template_revisions(self, from_id: str, to_id: str) -> Dict[str, Any]:
        before = self.get_template_revision(from_id)
        after = self.get_template_revision(to_id)
        if before["template_id"] != after["template_id"]:
            raise OperationsError("Можно сравнивать только ревизии одного шаблона.")
        return {
            "from": before,
            "to": after,
            "changes": diff_values(before["definition"], after["definition"]),
        }

    def rollback_template(
        self,
        *,
        workspace_id: str,
        template_id: str,
        revision_id: str,
        comment: str,
        user_id: str,
    ) -> Dict[str, Any]:
        target = self.get_template_revision(revision_id)
        if target["workspace_id"] != workspace_id or target["template_id"] != template_id:
            raise RevisionNotFound("Ревизия не относится к выбранному шаблону.")
        return self.update_template_with_revision(
            workspace_id=workspace_id,
            template_id=template_id,
            payload={
                "name": target["name"],
                "description": target["description"],
                "layout": target["definition"],
            },
            comment=comment or f"Откат к ревизии {target['revision_number']}.",
            source="rollback",
            user_id=user_id,
        )

    # --------------------------------------------------------- template learn

    def record_template_learning(
        self,
        *,
        workspace_id: str,
        template_id: str,
        revision_id: str | None,
        workbook_signature: str | None,
        sheet_signature: str | None,
        fingerprint: Mapping[str, Any],
        outcome: str,
        score: float,
        quality_percent: int,
        metrics: Mapping[str, Any],
    ) -> None:
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO template_learning(
                    workspace_id, template_id, revision_id, workbook_signature,
                    sheet_signature, fingerprint_json, outcome, score,
                    quality_percent, metrics_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    workspace_id, template_id, revision_id, workbook_signature,
                    sheet_signature, _json(dict(fingerprint)), outcome, float(score),
                    int(quality_percent), _json(dict(metrics)), _iso(),
                ),
            )
            if outcome == "success":
                connection.execute(
                    "UPDATE templates SET success_count = success_count + 1, last_used_at = ? "
                    "WHERE workspace_id = ? AND id = ?",
                    (_iso(), workspace_id, template_id),
                )
            elif outcome == "failure":
                connection.execute(
                    "UPDATE templates SET failure_count = failure_count + 1, last_used_at = ? "
                    "WHERE workspace_id = ? AND id = ?",
                    (_iso(), workspace_id, template_id),
                )

    def template_learning_summary(
        self,
        template_id: str,
        workbook_signature: str | None = None,
    ) -> Dict[str, Any]:
        connection = self._connect()
        try:
            total = connection.execute(
                """
                SELECT COUNT(*) AS total,
                       SUM(CASE WHEN outcome = 'success' THEN 1 ELSE 0 END) AS successes,
                       SUM(CASE WHEN outcome = 'failure' THEN 1 ELSE 0 END) AS failures,
                       AVG(quality_percent) AS average_quality
                FROM template_learning WHERE template_id = ?
                """,
                (template_id,),
            ).fetchone()
            exact = 0
            if workbook_signature:
                exact = int(connection.execute(
                    """
                    SELECT COUNT(*) FROM template_learning
                    WHERE template_id = ? AND workbook_signature = ? AND outcome = 'success'
                    """,
                    (template_id, workbook_signature),
                ).fetchone()[0])
            total_count = int(total["total"] or 0)
            successes = int(total["successes"] or 0)
            failures = int(total["failures"] or 0)
            return {
                "total": total_count,
                "successes": successes,
                "failures": failures,
                "success_rate": round(successes / total_count, 3) if total_count else 0.0,
                "average_quality": round(float(total["average_quality"] or 0), 2),
                "exact_successes": exact,
            }
        finally:
            connection.close()

    def create_format_rule(
        self,
        *,
        workspace_id: str,
        template_id: str,
        revision_id: str | None,
        component_id: str | None,
        fingerprint: Mapping[str, Any],
        priority: int,
        user_id: str,
    ) -> Dict[str, Any]:
        rule_id = str(uuid.uuid4())
        stamp = _iso()
        workbook_signature = str(fingerprint.get("workbook_signature") or fingerprint.get("signature") or "")
        sheet_signature = str(fingerprint.get("sheet_signature") or "")
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO format_rules(
                    id, workspace_id, template_id, revision_id, component_id,
                    workbook_signature, sheet_signature, fingerprint_json,
                    enabled, priority, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
                """,
                (
                    rule_id, workspace_id, template_id, revision_id, component_id,
                    workbook_signature, sheet_signature, _json(dict(fingerprint)),
                    int(priority), stamp, stamp,
                ),
            )
            self._audit(
                connection, user_id, "create", "format_rule", rule_id, workspace_id,
                "Создано правило распознавания формата.",
                {"template_id": template_id, "component_id": component_id},
            )
        return {
            "id": rule_id,
            "workspace_id": workspace_id,
            "template_id": template_id,
            "revision_id": revision_id,
            "component_id": component_id,
            "fingerprint": dict(fingerprint),
            "enabled": True,
            "priority": int(priority),
            "created_at": stamp,
        }

    def list_format_rules(self, workspace_id: str) -> List[Dict[str, Any]]:
        connection = self._connect()
        try:
            rows = connection.execute(
                """
                SELECT r.*, t.name AS template_name
                FROM format_rules r
                JOIN templates t ON t.workspace_id = r.workspace_id AND t.id = r.template_id
                WHERE r.workspace_id = ?
                ORDER BY r.enabled DESC, r.priority DESC, r.updated_at DESC
                """,
                (workspace_id,),
            ).fetchall()
            result = []
            for row in rows:
                item = dict(row)
                item["fingerprint"] = _loads(item.pop("fingerprint_json"), {})
                result.append(item)
            return result
        finally:
            connection.close()

    # -------------------------------------------------------- run history

    def create_processing_run(
        self,
        *,
        workspace_id: str,
        user_id: str | None,
        source_session_id: str | None,
        settings: Mapping[str, Any],
        total_files: int,
    ) -> str:
        run_id = str(uuid.uuid4())
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO processing_runs(
                    id, workspace_id, user_id, source_session_id, status,
                    settings_json, total_files, started_at
                ) VALUES (?, ?, ?, ?, 'running', ?, ?, ?)
                """,
                (
                    run_id, workspace_id, user_id, source_session_id,
                    _json(dict(settings)), int(total_files), _iso(),
                ),
            )
        return run_id

    def add_processing_file(
        self,
        *,
        run_id: str,
        original_name: str,
        group_name: str,
        source_sha256: str,
        source_path: str,
        template_id: str | None,
        template_revision_id: str | None,
        component_id: str | None,
        layout: Mapping[str, Any],
        analysis: Mapping[str, Any],
        validation: Mapping[str, Any],
        lesson_count: int,
        status: str,
        message: str,
    ) -> str:
        file_id = str(uuid.uuid4())
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO processing_files(
                    id, run_id, original_name, group_name, source_sha256,
                    source_path, template_id, template_revision_id, component_id,
                    layout_json, analysis_json, validation_json, lesson_count,
                    status, message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    file_id, run_id, original_name, group_name, source_sha256,
                    source_path, template_id, template_revision_id, component_id,
                    _json(dict(layout)), _json(dict(analysis)), _json(dict(validation)),
                    int(lesson_count), status, text(message, 1000),
                ),
            )
        return file_id

    def add_processing_artifact(
        self,
        *,
        run_id: str,
        kind: str,
        filename: str,
        stored_path: str,
        sha256: str,
        size: int,
    ) -> str:
        artifact_id = str(uuid.uuid4())
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO processing_artifacts(
                    id, run_id, kind, filename, stored_path, sha256, size, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact_id, run_id, kind, filename, stored_path,
                    sha256, int(size), _iso(),
                ),
            )
        return artifact_id

    def finish_processing_run(
        self,
        *,
        run_id: str,
        status: str,
        message: str,
        success_files: int,
        warning_files: int,
        error_files: int,
        user_id: str | None,
    ) -> None:
        with self.transaction() as connection:
            row = connection.execute(
                "SELECT workspace_id FROM processing_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
            if not row:
                raise ProcessingRunNotFound("История обработки не найдена.")
            connection.execute(
                """
                UPDATE processing_runs SET status = ?, message = ?,
                    success_files = ?, warning_files = ?, error_files = ?,
                    finished_at = ? WHERE id = ?
                """,
                (
                    status, text(message, 1000), int(success_files),
                    int(warning_files), int(error_files), _iso(), run_id,
                ),
            )
            self._audit(
                connection, user_id, "finish", "processing_run", run_id,
                row["workspace_id"], "Завершена обработка расписаний.",
                {
                    "status": status,
                    "success_files": success_files,
                    "warning_files": warning_files,
                    "error_files": error_files,
                },
            )

    def list_processing_runs(
        self,
        *,
        workspace_id: str,
        status: str | None = None,
        query: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        where = ["r.workspace_id = ?"]
        params: List[Any] = [workspace_id]
        if status:
            where.append("r.status = ?")
            params.append(status)
        if query:
            where.append(
                "(r.message LIKE ? OR EXISTS (SELECT 1 FROM processing_files f "
                "WHERE f.run_id = r.id AND (f.original_name LIKE ? OR f.group_name LIKE ?)))"
            )
            token = f"%{query}%"
            params.extend([token, token, token])
        params.extend([max(1, min(int(limit), 300)), max(0, int(offset))])
        connection = self._connect()
        try:
            rows = connection.execute(
                f"""
                SELECT r.*, u.display_name AS user_name,
                       (SELECT COUNT(*) FROM processing_artifacts a WHERE a.run_id = r.id)
                           AS artifact_count
                FROM processing_runs r
                LEFT JOIN users u ON u.id = r.user_id
                WHERE {' AND '.join(where)}
                ORDER BY r.started_at DESC LIMIT ? OFFSET ?
                """,
                params,
            ).fetchall()
            result = []
            for row in rows:
                item = dict(row)
                item["settings"] = _loads(item.pop("settings_json"), {})
                result.append(item)
            return result
        finally:
            connection.close()

    def get_processing_run(self, run_id: str) -> Dict[str, Any]:
        connection = self._connect()
        try:
            row = connection.execute(
                """
                SELECT r.*, u.display_name AS user_name, w.name AS workspace_name
                FROM processing_runs r
                LEFT JOIN users u ON u.id = r.user_id
                JOIN workspaces w ON w.id = r.workspace_id
                WHERE r.id = ?
                """,
                (run_id,),
            ).fetchone()
            if not row:
                raise ProcessingRunNotFound("История обработки не найдена.")
            run = dict(row)
            run["settings"] = _loads(run.pop("settings_json"), {})
            files = []
            for file_row in connection.execute(
                "SELECT * FROM processing_files WHERE run_id = ? ORDER BY original_name",
                (run_id,),
            ).fetchall():
                item = dict(file_row)
                item["layout"] = _loads(item.pop("layout_json"), {})
                item["analysis"] = _loads(item.pop("analysis_json"), {})
                item["validation"] = _loads(item.pop("validation_json"), {})
                files.append(item)
            artifacts = [dict(item) for item in connection.execute(
                "SELECT * FROM processing_artifacts WHERE run_id = ? ORDER BY created_at",
                (run_id,),
            ).fetchall()]
            run["files"] = files
            run["artifacts"] = artifacts
            return run
        finally:
            connection.close()

    def get_processing_artifact(self, artifact_id: str) -> Dict[str, Any]:
        connection = self._connect()
        try:
            row = connection.execute(
                """
                SELECT a.*, r.workspace_id FROM processing_artifacts a
                JOIN processing_runs r ON r.id = a.run_id WHERE a.id = ?
                """,
                (artifact_id,),
            ).fetchone()
            if not row:
                raise ProcessingRunNotFound("Файл истории не найден.")
            return dict(row)
        finally:
            connection.close()
