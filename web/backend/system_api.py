"""Health and application-version endpoints."""
from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter

from web.backend.app_context import ApplicationContext
from web.backend.errors import StorageUnavailable

logger = logging.getLogger(__name__)


def build_system_router(context: ApplicationContext) -> APIRouter:
    router = APIRouter(tags=["system"])

    def status() -> Dict[str, Any]:
        try:
            return context.system_status()
        except Exception as exc:
            logger.exception("Workspace storage health check failed")
            raise StorageUnavailable("Хранилище данных недоступно.") from exc

    router.add_api_route("/api/health", status, methods=["GET"])
    router.add_api_route("/api/system/version", status, methods=["GET"])
    return router
