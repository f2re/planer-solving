"""Application exceptions and actionable, safe FastAPI error responses."""
from __future__ import annotations

import logging
from typing import Any, Mapping, Sequence
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from src.workspace_domain import WorkspaceError, WorkspaceNotFound
from web.backend.recovery_catalog import recovery_for

logger = logging.getLogger(__name__)


class ApplicationError(Exception):
    status_code = 400
    code = "application_error"

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        code: str | None = None,
        recovery: Mapping[str, Any] | None = None,
        actions: Sequence[Mapping[str, Any]] = (),
    ):
        super().__init__(message)
        self.message = message
        self.recovery = dict(recovery or {})
        self.actions = [dict(item) for item in actions if item]
        if status_code is not None:
            self.status_code = status_code
        if code is not None:
            self.code = code


class SessionNotFound(ApplicationError):
    status_code = 404
    code = "session_not_found"


class SessionCorrupted(ApplicationError):
    status_code = 503
    code = "session_corrupted"


class UploadedFileNotFound(ApplicationError):
    status_code = 404
    code = "uploaded_file_not_found"


class StorageUnavailable(ApplicationError):
    status_code = 503
    code = "storage_unavailable"


def _incident_id() -> str:
    return uuid.uuid4().hex[:12]


def _recovery(
    *,
    code: str,
    detail: str,
    request: Request,
    incident_id: str,
    status_code: int,
    overrides: Mapping[str, Any] | None = None,
    actions: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    values = dict(overrides or {})
    lookup_code = code
    if code not in {
        "session_not_found",
        "session_corrupted",
        "uploaded_file_not_found",
        "storage_unavailable",
        "workspace_not_found",
        "workspace_error",
        "draft_revision_conflict",
        "draft_too_large",
        "replacement_rejected",
        "append_commit_failed",
        "replacement_commit_failed",
        "remove_commit_failed",
        "restore_commit_failed",
        "source_archive_missing",
        "output_write_failed",
        "processing_history_unavailable",
        "internal_error",
    }:
        lookup_code = "internal_error"
        values.setdefault("code", code)
        values.setdefault("title", "Операция не выполнена")
        values.setdefault("severity", "critical" if status_code >= 500 else "technical")
        values.setdefault("retryable", status_code not in {401, 403, 404})
        values.setdefault("state_preserved", True)
        values.setdefault(
            "guidance",
            (
                "Исправьте указанное значение и повторите действие. Текущий сеанс не удалён."
                if status_code < 500
                else "Повторите действие один раз; при повторном отказе откройте диагностику и передайте код инцидента администратору."
            ),
        )
    return recovery_for(
        lookup_code,
        detail=detail,
        incident_id=incident_id,
        request_path=request.url.path,
        overrides=values,
        extra_actions=actions,
    )


def _payload(
    *,
    message: str,
    code: str,
    request: Request,
    incident_id: str,
    status_code: int,
    recovery: Mapping[str, Any] | None = None,
    actions: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    descriptor = _recovery(
        code=code,
        detail=message,
        request=request,
        incident_id=incident_id,
        status_code=status_code,
        overrides=recovery,
        actions=actions,
    )
    return {
        "detail": message,
        "code": code,
        "incident_id": incident_id,
        "recovery": descriptor,
    }


def _response(
    *,
    request: Request,
    message: str,
    code: str,
    status_code: int,
    recovery: Mapping[str, Any] | None = None,
    actions: Sequence[Mapping[str, Any]] = (),
) -> JSONResponse:
    incident_id = _incident_id()
    return JSONResponse(
        status_code=status_code,
        content=_payload(
            message=message,
            code=code,
            request=request,
            incident_id=incident_id,
            status_code=status_code,
            recovery=recovery,
            actions=actions,
        ),
        headers={"X-Planner-Incident": incident_id},
    )


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApplicationError)
    async def application_error_handler(request: Request, exc: ApplicationError) -> JSONResponse:
        return _response(
            request=request,
            message=exc.message,
            code=exc.code,
            status_code=exc.status_code,
            recovery=exc.recovery,
            actions=exc.actions,
        )

    @app.exception_handler(WorkspaceNotFound)
    async def workspace_not_found_handler(request: Request, exc: WorkspaceNotFound) -> JSONResponse:
        return _response(
            request=request,
            message=str(exc),
            code="workspace_not_found",
            status_code=404,
        )

    @app.exception_handler(WorkspaceError)
    async def workspace_error_handler(request: Request, exc: WorkspaceError) -> JSONResponse:
        return _response(
            request=request,
            message=str(exc),
            code="workspace_error",
            status_code=503,
        )

    @app.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
        incident_id = _incident_id()
        logger.error(
            "Unhandled error %s for %s %s",
            incident_id,
            request.method,
            request.url.path,
            exc_info=(type(exc), exc, exc.__traceback__),
        )
        return JSONResponse(
            status_code=500,
            content=_payload(
                message=(
                    "Внутренняя ошибка приложения. Текущий сеанс не удалён; "
                    "повторите действие один раз или откройте диагностику."
                ),
                code="internal_error",
                request=request,
                incident_id=incident_id,
                status_code=500,
            ),
            headers={"X-Planner-Incident": incident_id},
        )
