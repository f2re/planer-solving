"""Application-level exceptions and safe FastAPI error responses."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from src.operations_domain import (
    AuthenticationRequired,
    ImportJobNotFound,
    InvalidCredentials,
    OperationsError,
    PermissionDenied,
    ProcessingRunNotFound,
    RevisionNotFound,
    SetupRequired,
)
from src.workspace_domain import WorkspaceError, WorkspaceNotFound

logger = logging.getLogger(__name__)


class ApplicationError(Exception):
    status_code = 400
    code = "application_error"

    def __init__(self, message: str, *, status_code: int | None = None, code: str | None = None):
        super().__init__(message)
        self.message = message
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


def _payload(message: str, code: str) -> dict[str, Any]:
    return {"detail": message, "code": code}


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApplicationError)
    async def application_error_handler(_: Request, exc: ApplicationError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_payload(exc.message, exc.code),
        )

    @app.exception_handler(WorkspaceNotFound)
    async def workspace_not_found_handler(_: Request, exc: WorkspaceNotFound) -> JSONResponse:
        return JSONResponse(status_code=404, content=_payload(str(exc), "workspace_not_found"))

    @app.exception_handler(WorkspaceError)
    async def workspace_error_handler(_: Request, exc: WorkspaceError) -> JSONResponse:
        return JSONResponse(status_code=400, content=_payload(str(exc), "workspace_error"))

    @app.exception_handler(SetupRequired)
    async def setup_required_handler(_: Request, exc: SetupRequired) -> JSONResponse:
        return JSONResponse(status_code=428, content=_payload(str(exc), "setup_required"))

    @app.exception_handler(AuthenticationRequired)
    async def authentication_required_handler(_: Request, exc: AuthenticationRequired) -> JSONResponse:
        return JSONResponse(status_code=401, content=_payload(str(exc), "authentication_required"))

    @app.exception_handler(InvalidCredentials)
    async def invalid_credentials_handler(_: Request, exc: InvalidCredentials) -> JSONResponse:
        return JSONResponse(status_code=401, content=_payload(str(exc), "invalid_credentials"))

    @app.exception_handler(PermissionDenied)
    async def permission_denied_handler(_: Request, exc: PermissionDenied) -> JSONResponse:
        return JSONResponse(status_code=403, content=_payload(str(exc), "permission_denied"))

    @app.exception_handler(ImportJobNotFound)
    async def import_not_found_handler(_: Request, exc: ImportJobNotFound) -> JSONResponse:
        return JSONResponse(status_code=404, content=_payload(str(exc), "import_not_found"))

    @app.exception_handler(ProcessingRunNotFound)
    async def run_not_found_handler(_: Request, exc: ProcessingRunNotFound) -> JSONResponse:
        return JSONResponse(status_code=404, content=_payload(str(exc), "processing_run_not_found"))

    @app.exception_handler(RevisionNotFound)
    async def revision_not_found_handler(_: Request, exc: RevisionNotFound) -> JSONResponse:
        return JSONResponse(status_code=404, content=_payload(str(exc), "revision_not_found"))

    @app.exception_handler(OperationsError)
    async def operations_error_handler(_: Request, exc: OperationsError) -> JSONResponse:
        return JSONResponse(status_code=400, content=_payload(str(exc), "operations_error"))

    @app.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error(
            "Unhandled error for %s %s",
            request.method,
            request.url.path,
            exc_info=(type(exc), exc, exc.__traceback__),
        )
        return JSONResponse(
            status_code=500,
            content=_payload(
                "Внутренняя ошибка приложения. Подробности записаны в журнал сервера.",
                "internal_error",
            ),
        )
