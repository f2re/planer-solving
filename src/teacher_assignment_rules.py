"""Persistent, workspace-scoped teacher assignment preferences.

Rules are deliberately small and independent from the timetable parser. They
store operator preferences for lectures, practice lessons and one reserve
teacher. The global collision graph remains authoritative and may still move an
assignment when the preferred teacher is busy.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import re
from typing import Any, Dict, Iterable, List, Mapping, Sequence


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def subject_key(value: Any) -> str:
    text = str(value or "").strip().lower().replace("ё", "е")
    return re.sub(r"[^0-9a-zа-я]+", "", text)


def _teacher_key(value: Any) -> str:
    text = str(value or "").strip().lower().replace("ё", "е")
    text = re.sub(r"[.,;:()]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _ensure_schema(connection: Any) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS teacher_assignment_rules (
            workspace_id TEXT NOT NULL,
            subject_key TEXT NOT NULL,
            subject_name TEXT NOT NULL,
            lecturer_name TEXT NOT NULL DEFAULT '',
            practice_name TEXT NOT NULL DEFAULT '',
            reserve_name TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL,
            PRIMARY KEY(workspace_id, subject_key),
            FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_teacher_assignment_rules_workspace
            ON teacher_assignment_rules(workspace_id, subject_name COLLATE NOCASE);
        """
    )


def ensure_teacher_assignment_schema(repository: Any) -> None:
    with repository._transaction() as connection:
        _ensure_schema(connection)


def _teacher_aliases(teachers: Sequence[Mapping[str, Any]]) -> Dict[str, str]:
    result: Dict[str, str] = {}
    ambiguous: set[str] = set()
    for teacher in teachers:
        short = str(teacher.get("short_name") or teacher.get("full_name") or "").strip()
        full = str(teacher.get("full_name") or short).strip()
        if not short:
            continue
        for alias in (short, full):
            key = _teacher_key(alias)
            if not key:
                continue
            previous = result.get(key)
            if previous and previous != short:
                ambiguous.add(key)
            else:
                result[key] = short
    for key in ambiguous:
        result.pop(key, None)
    return result


def _canonical_teacher(value: Any, aliases: Mapping[str, str]) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    return aliases.get(_teacher_key(raw), "")


def normalize_rule(
    raw: Mapping[str, Any],
    *,
    aliases: Mapping[str, str],
) -> Dict[str, str]:
    subject = str(raw.get("subject") or raw.get("subject_name") or "").strip()[:300]
    key = subject_key(subject)
    if not key:
        return {}
    return {
        "subject_key": key,
        "subject": subject,
        "lecturer": _canonical_teacher(raw.get("lecturer"), aliases),
        "practice": _canonical_teacher(raw.get("practice"), aliases),
        "reserve": _canonical_teacher(raw.get("reserve"), aliases),
    }


def list_teacher_assignment_rules(repository: Any, workspace_id: str) -> List[Dict[str, str]]:
    repository.get_workspace(workspace_id)
    connection = repository._connect()
    try:
        _ensure_schema(connection)
        connection.commit()
        rows = connection.execute(
            """
            SELECT subject_key, subject_name, lecturer_name, practice_name,
                   reserve_name, updated_at
            FROM teacher_assignment_rules
            WHERE workspace_id = ?
            ORDER BY subject_name COLLATE NOCASE, subject_key
            """,
            (workspace_id,),
        ).fetchall()
        return [{
            "subject_key": str(row["subject_key"]),
            "subject": str(row["subject_name"]),
            "lecturer": str(row["lecturer_name"] or ""),
            "practice": str(row["practice_name"] or ""),
            "reserve": str(row["reserve_name"] or ""),
            "updated_at": str(row["updated_at"]),
        } for row in rows]
    finally:
        connection.close()


def replace_teacher_assignment_rules(
    repository: Any,
    workspace_id: str,
    rules: Iterable[Mapping[str, Any]],
) -> List[Dict[str, str]]:
    repository.get_workspace(workspace_id)
    teachers = repository.list_teachers(workspace_id)
    aliases = _teacher_aliases(teachers)
    normalized: Dict[str, Dict[str, str]] = {}
    for raw in rules:
        if not isinstance(raw, Mapping):
            continue
        item = normalize_rule(raw, aliases=aliases)
        if not item:
            continue
        if not any(item[field] for field in ("lecturer", "practice", "reserve")):
            continue
        normalized[item["subject_key"]] = item

    stamp = _now()
    with repository._transaction() as connection:
        _ensure_schema(connection)
        connection.execute(
            "DELETE FROM teacher_assignment_rules WHERE workspace_id = ?",
            (workspace_id,),
        )
        for item in normalized.values():
            connection.execute(
                """
                INSERT INTO teacher_assignment_rules(
                    workspace_id, subject_key, subject_name, lecturer_name,
                    practice_name, reserve_name, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    workspace_id,
                    item["subject_key"],
                    item["subject"],
                    item["lecturer"],
                    item["practice"],
                    item["reserve"],
                    stamp,
                ),
            )
    return list_teacher_assignment_rules(repository, workspace_id)


def encoded_preference_overrides(
    rules: Iterable[Mapping[str, Any]],
) -> Dict[str, str]:
    """Encode preferences into the existing per-file override envelope.

    This keeps old analysis sessions and API clients compatible: current
    schedule requests already transport ``teacher_overrides`` inside
    ``period_overrides``. The resolver recognizes keys beginning with ``@`` as
    preferences rather than hard manual assignments.
    """

    result: Dict[str, str] = {}
    for raw in rules:
        subject = str(raw.get("subject") or "").strip()
        if not subject:
            continue
        for role, field in (("lecturer", "lecturer"), ("other", "practice"), ("reserve", "reserve")):
            teacher = str(raw.get(field) or "").strip()
            if teacher:
                result[f"@{role}|{subject}"] = teacher
    return result
