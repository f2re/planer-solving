"""Atomic template-revision and account operations for the platform."""
from __future__ import annotations

from copy import deepcopy
import json
from typing import Any, Dict

from .platform_store import PlatformStore
from .security import hash_password, iso_now
from .template_learning import layout_diff
from .workspace_domain import WorkspaceError, WorkspaceNotFound, normalize_template, now


class TransactionalPlatformStore(PlatformStore):
    """Platform store with related changes written atomically."""

    def create_template(self, workspace_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        with self._transaction() as connection:
            self.base._workspace(connection, workspace_id)
            template = normalize_template(payload)
            try:
                self.base._insert_template(connection, workspace_id, template)
            except Exception as exc:
                if "UNIQUE" in str(exc).upper():
                    raise WorkspaceError("Шаблон с таким названием уже существует.") from exc
                raise
            connection.execute(
                """
                INSERT INTO template_profiles(workspace_id, template_id, current_revision)
                VALUES (?, ?, 0)
                """,
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
            connection.execute(
                "UPDATE workspaces SET updated_at = ? WHERE id = ?",
                (now(), workspace_id),
            )
            self.base._write_compatibility_mirrors(connection)
            result = deepcopy(template)
            result.update(self._profile(connection, workspace_id, template["id"]))
            return result

    def update_template(
        self,
        workspace_id: str,
        template_id: str,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM templates WHERE workspace_id = ? AND id = ?",
                (workspace_id, template_id),
            ).fetchone()
            if not row:
                raise WorkspaceNotFound("Шаблон не найден.")
            current = {
                "id": row["id"],
                "name": row["name"],
                "description": row["description"],
                "layout": json.loads(row["layout_json"]),
                "created_at": row["created_at"],
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
                        template["name"],
                        template["description"],
                        json.dumps(
                            template["layout"],
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                        template["updated_at"],
                        workspace_id,
                        template_id,
                    ),
                )
            except Exception as exc:
                if "UNIQUE" in str(exc).upper():
                    raise WorkspaceError("Шаблон с таким названием уже существует.") from exc
                raise
            self._record_revision(
                connection,
                workspace_id,
                template,
                composite=payload.get("composite") if "composite" in payload else None,
                fingerprint=payload.get("fingerprint") if "fingerprint" in payload else None,
                comment=payload.get("comment", "Изменена разметка"),
                actor_user_id=payload.get("actor_user_id"),
            )
            connection.execute(
                "UPDATE workspaces SET updated_at = ? WHERE id = ?",
                (now(), workspace_id),
            )
            self.base._write_compatibility_mirrors(connection)
            self._audit_connection(
                connection,
                actor=None,
                action="template.update",
                entity_type="template",
                entity_id=template_id,
                workspace_id=workspace_id,
                summary=f"Обновлён шаблон «{template['name']}»",
                details={
                    "layout_changes": layout_diff(
                        current.get("layout", {}),
                        template["layout"],
                    )
                },
            )
            result = deepcopy(template)
            result.update(self._profile(connection, workspace_id, template_id))
            return result

    def reset_user_password(self, user_id: str, password: str = "") -> Dict[str, Any]:
        """Set any password, including empty, and revoke all active sessions."""

        with self._transaction() as connection:
            row = connection.execute(
                "SELECT id, username, display_name, role, is_active, created_at FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
            if not row:
                raise WorkspaceNotFound("Пользователь не найден.")
            stamp = iso_now()
            connection.execute(
                "UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?",
                (hash_password(password), stamp, user_id),
            )
            connection.execute("DELETE FROM auth_sessions WHERE user_id = ?", (user_id,))
            result = dict(row)
            result["is_active"] = bool(result["is_active"])
            result["updated_at"] = stamp
            return result
