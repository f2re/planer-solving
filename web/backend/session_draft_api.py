"""Persistent operator drafts for recoverable analysis sessions."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from web.backend.app_context import ApplicationContext
from web.backend.errors import ApplicationError

logger = logging.getLogger(__name__)
DRAFT_SCHEMA_VERSION = 1
DRAFT_FILENAME = "operator-draft.json"
MAX_DRAFT_BYTES = 8 * 1024 * 1024


class SessionDraftSaveRequest(BaseModel):
    version: int = Field(default=DRAFT_SCHEMA_VERSION, ge=1, le=DRAFT_SCHEMA_VERSION)
    base_revision: Optional[int] = Field(default=None, ge=0)
    workspace_id: Optional[str] = None
    step: int = Field(default=1, ge=1, le=3)
    selected_file_id: Optional[str] = None
    file_states: List[Dict[str, Any]] = Field(default_factory=list)
    layouts: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    validations: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    period_overrides: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    calendar_overrides: Dict[str, Any] = Field(default_factory=dict)
    result: Optional[Dict[str, Any]] = None
    editor: Dict[str, Any] = Field(default_factory=dict)


def _model_dict(model: BaseModel) -> Dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model.dict()


def _draft_path(context: ApplicationContext, session_id: str) -> Path:
    return context.sessions.path(session_id) / DRAFT_FILENAME


def _load_draft(context: ApplicationContext, session_id: str) -> Optional[Dict[str, Any]]:
    path = _draft_path(context, session_id)
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("draft root is not an object")
        return value
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        logger.warning("Ignoring damaged operator draft %s: %s", path, exc)
        try:
            quarantine = path.with_name(f"{path.name}.corrupt")
            os.replace(path, quarantine)
        except OSError:
            pass
        return None


def _public_file(item: Mapping[str, Any]) -> Dict[str, Any]:
    result = {
        key: item.get(key)
        for key in ("file_id", "filename", "group_name", "status", "message", "analysis")
    }
    template_match = item.get("template_match")
    if isinstance(template_match, Mapping):
        selected = template_match.get("selected")
        result["template_match"] = dict(selected) if isinstance(selected, Mapping) else None
    else:
        result["template_match"] = None
    return result


def _mapping_for_files(
    values: Mapping[str, Any],
    allowed_ids: set[str],
) -> Dict[str, Dict[str, Any]]:
    return {
        str(file_id): dict(value)
        for file_id, value in values.items()
        if str(file_id) in allowed_ids and isinstance(value, Mapping)
    }


def _sanitize_state(
    payload: SessionDraftSaveRequest,
    manifest: Mapping[str, Any],
) -> Dict[str, Any]:
    values = _model_dict(payload)
    manifest_files = [item for item in manifest.get("files", []) if isinstance(item, Mapping)]
    allowed_ids = {
        str(item.get("file_id"))
        for item in manifest_files
        if item.get("file_id")
    }
    file_states: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for raw in values.get("file_states") or []:
        if not isinstance(raw, Mapping):
            continue
        file_id = str(raw.get("file_id") or "")
        if not file_id or file_id not in allowed_ids or file_id in seen:
            continue
        seen.add(file_id)
        file_states.append({
            "file_id": file_id,
            "group_name": str(raw.get("group_name") or "").strip()[:240],
            "enabled": bool(raw.get("enabled", True)),
        })

    selected_file_id = str(values.get("selected_file_id") or "") or None
    if selected_file_id not in allowed_ids:
        selected_file_id = None

    calendar = values.get("calendar_overrides")
    if not isinstance(calendar, Mapping):
        calendar = {}
    editor = values.get("editor")
    if not isinstance(editor, Mapping):
        editor = {}
    result = values.get("result")
    if result is not None and not isinstance(result, Mapping):
        result = None

    return {
        "version": DRAFT_SCHEMA_VERSION,
        "workspace_id": str(values.get("workspace_id") or "") or None,
        "step": max(1, min(3, int(values.get("step") or 1))),
        "selected_file_id": selected_file_id,
        "file_states": file_states,
        "layouts": _mapping_for_files(values.get("layouts") or {}, allowed_ids),
        "validations": _mapping_for_files(values.get("validations") or {}, allowed_ids),
        "period_overrides": _mapping_for_files(
            values.get("period_overrides") or {},
            allowed_ids,
        ),
        "calendar_overrides": dict(calendar),
        "result": dict(result) if isinstance(result, Mapping) else None,
        "editor": dict(editor),
    }


def _encoded_size(value: Mapping[str, Any]) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def build_session_draft_router(context: ApplicationContext) -> APIRouter:
    router = APIRouter(tags=["analysis-session-draft"])

    @router.get("/api/analysis/{session_id}/draft")
    def get_session_draft(session_id: str) -> Dict[str, Any]:
        manifest = context.sessions.load_manifest(session_id)
        draft = _load_draft(context, session_id)
        return {
            "session_id": session_id,
            "revision": int((draft or {}).get("revision") or 0),
            "saved_at": (draft or {}).get("saved_at"),
            "files": [
                _public_file(item)
                for item in manifest.get("files", [])
                if isinstance(item, Mapping)
            ],
            "draft": (draft or {}).get("state"),
        }

    @router.put("/api/analysis/{session_id}/draft")
    def save_session_draft(
        session_id: str,
        payload: SessionDraftSaveRequest,
    ) -> Dict[str, Any]:
        manifest = context.sessions.load_manifest(session_id)
        current = _load_draft(context, session_id)
        current_revision = int((current or {}).get("revision") or 0)
        if payload.base_revision is not None and payload.base_revision != current_revision:
            raise ApplicationError(
                "Черновик изменён в другой вкладке. Восстановите серверную версию или повторите сохранение после её загрузки.",
                status_code=409,
                code="draft_revision_conflict",
            )

        state = _sanitize_state(payload, manifest)
        document = {
            "schema_version": DRAFT_SCHEMA_VERSION,
            "revision": current_revision + 1,
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "state": state,
        }
        if _encoded_size(document) > MAX_DRAFT_BYTES:
            raise ApplicationError(
                "Черновик слишком велик для автосохранения. Уменьшите число одновременно открытых файлов или сформируйте результат.",
                status_code=413,
                code="draft_too_large",
            )

        context.sessions.atomic_json_write(_draft_path(context, session_id), document)
        try:
            context.sessions.path(session_id).touch()
        except OSError:
            pass
        return {
            "status": "saved",
            "session_id": session_id,
            "revision": document["revision"],
            "saved_at": document["saved_at"],
            "file_count": len(state["file_states"]),
        }

    @router.delete("/api/analysis/{session_id}/draft")
    def delete_session_draft(session_id: str) -> Dict[str, Any]:
        context.sessions.load_manifest(session_id)
        path = _draft_path(context, session_id)
        path.unlink(missing_ok=True)
        return {
            "status": "deleted",
            "session_id": session_id,
        }

    return router
