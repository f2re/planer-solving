"""Health, application-version and operator recovery endpoints."""
from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter

from web.backend.app_context import ApplicationContext
from web.backend.errors import StorageUnavailable
from web.backend.processing_recovery import install_processing_recovery
from web.backend.recovery_status import build_recovery_status

logger = logging.getLogger(__name__)


def build_system_router(context: ApplicationContext) -> APIRouter:
    # Router construction happens after the schedule router but before the app
    # starts serving requests. Method lookup on the repository remains dynamic,
    # so the guard also covers schedule closures created earlier.
    install_processing_recovery(context.workspace_repository)
    router = APIRouter(tags=["system"])

    def status() -> Dict[str, Any]:
        try:
            return context.system_status()
        except Exception as exc:
            logger.exception("Workspace storage health check failed")
            raise StorageUnavailable(
                "Хранилище данных недоступно. Откройте диагностику, устраните первый критический пункт и повторите запрос."
            ) from exc

    def recovery_status() -> Dict[str, Any]:
        try:
            return build_recovery_status(context)
        except Exception as exc:
            logger.exception("Recovery diagnostics failed")
            raise StorageUnavailable(
                "Диагностика не завершена. Выполните planner-solving-doctor на сервере и приложите отчёт."
            ) from exc

    router.add_api_route("/api/health", status, methods=["GET"])
    router.add_api_route("/api/system/version", status, methods=["GET"])
    router.add_api_route("/api/system/recovery", recovery_status, methods=["GET"])
    return router
