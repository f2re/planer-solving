"""Transactional commit helpers for reviewed import jobs."""
from __future__ import annotations

import sqlite3
from typing import Any, Dict, Mapping, Sequence
import uuid

from .operations_store import OperationsStore, _iso, _json
from .template_definition import normalize_definition
from .workspace_domain import WorkspaceError, normalize_template


def commit_template_import(
    operations: OperationsStore,
    *,
    job_id: str,
    workspace_id: str,
    rows: Sequence[Mapping[str, Any]],
    decisions: Mapping[int, str],
    mode: str,
    user_id: str,
) -> Dict[str, Any]:
    if mode not in {"append", "replace"}:
        raise WorkspaceError("Неизвестный режим импорта.")
    with operations.transaction() as connection:
        if not connection.execute(
            "SELECT 1 FROM workspaces WHERE id = ?", (workspace_id,)
        ).fetchone():
            raise WorkspaceError("Пространство не найдено.")
        if mode == "replace":
            connection.execute("DELETE FROM templates WHERE workspace_id = ?", (workspace_id,))
        existing = {
            str(row["name"]).casefold(): dict(row)
            for row in connection.execute(
                "SELECT * FROM templates WHERE workspace_id = ?", (workspace_id,)
            ).fetchall()
        }
        counts = {"added": 0, "updated": 0, "skipped": 0, "errors": 0}
        results = []
        for index, raw in enumerate(rows):
            action = decisions.get(index, str(raw.get("suggested_action") or "add"))
            record = dict(raw.get("record") or raw)
            try:
                template = normalize_template({
                    "name": record.get("name"),
                    "description": record.get("description", ""),
                    "layout": normalize_definition(record.get("layout") or {}),
                })
            except (WorkspaceError, ValueError) as exc:
                counts["errors"] += 1
                results.append({"row_index": index, "action": "error", "message": str(exc)})
                continue
            key = template["name"].casefold()
            current = existing.get(key)
            if action == "skip":
                counts["skipped"] += 1
                results.append({"row_index": index, "action": "skip"})
                continue
            if action == "update" and current:
                revision = operations._insert_revision(
                    connection,
                    workspace_id=workspace_id,
                    template_id=current["id"],
                    name=template["name"],
                    description=template["description"],
                    definition=template["layout"],
                    comment="Обновлено через мастер импорта.",
                    source="import",
                    author_user_id=user_id,
                )
                counts["updated"] += 1
                results.append({
                    "row_index": index,
                    "action": "update",
                    "template_id": current["id"],
                    "revision_id": revision["id"],
                })
                continue
            if current:
                counts["skipped"] += 1
                results.append({
                    "row_index": index,
                    "action": "skip",
                    "message": "Шаблон с таким названием уже существует.",
                })
                continue
            template_id = str(uuid.uuid4())
            stamp = _iso()
            try:
                connection.execute(
                    """
                    INSERT INTO templates(
                        workspace_id, id, name, description, layout_json,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        workspace_id, template_id, template["name"],
                        template["description"], _json(template["layout"]), stamp, stamp,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                counts["errors"] += 1
                results.append({"row_index": index, "action": "error", "message": str(exc)})
                continue
            revision = operations._insert_revision(
                connection,
                workspace_id=workspace_id,
                template_id=template_id,
                name=template["name"],
                description=template["description"],
                definition=template["layout"],
                comment="Создано через мастер импорта.",
                source="import",
                author_user_id=user_id,
            )
            existing[key] = {"id": template_id, "name": template["name"]}
            counts["added"] += 1
            results.append({
                "row_index": index,
                "action": "add",
                "template_id": template_id,
                "revision_id": revision["id"],
            })
        connection.execute(
            "UPDATE workspaces SET updated_at = ? WHERE id = ?",
            (_iso(), workspace_id),
        )
        total = int(connection.execute(
            "SELECT COUNT(*) FROM templates WHERE workspace_id = ?", (workspace_id,)
        ).fetchone()[0])
        result = {**counts, "total": total, "rows": results}
        connection.execute(
            "UPDATE import_jobs SET status = 'committed', committed_at = ?, "
            "evaluation_json = ? WHERE id = ?",
            (_iso(), _json(result), job_id),
        )
        operations._audit(
            connection, user_id, "commit", "template_import", job_id, workspace_id,
            "Импортированы шаблоны разметки.", result,
        )
        operations._write_mirrors(connection)
        return result
