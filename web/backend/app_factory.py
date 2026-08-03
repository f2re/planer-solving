"""FastAPI application factory with explicit dependencies and route order."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from web.backend.analysis_api import build_analysis_router
from web.backend.app_context import ApplicationContext, WorkspaceRepository
from web.backend.auth import build_auth_router, install_auth
from web.backend.errors import install_exception_handlers
from web.backend.password_reset_session import install_password_reset_session
from web.backend.platform_api import build_platform_router
from web.backend.session_api import build_session_router
from web.backend.system_api import build_system_router
from web.backend.workspace_api import build_workspace_router
from web.backend.workspace_schedule import build_schedule_router


def create_app(
    base_dir: Optional[Path] = None,
    workspace_repository: Optional[WorkspaceRepository] = None,
) -> FastAPI:
    context = ApplicationContext(
        base_dir=base_dir,
        workspace_repository=workspace_repository,
    )
    app = FastAPI(
        title="Planner Solving",
        description="Операторский разбор разнородных расписаний Excel",
        version=context.application_version(),
    )
    app.state.context = context
    install_exception_handlers(app)
    install_auth(app, context)
    install_password_reset_session(app, context)

    app.include_router(build_auth_router(context))
    app.include_router(build_analysis_router(context))
    app.include_router(build_session_router(context))
    app.include_router(build_workspace_router(context))
    app.include_router(build_schedule_router(context))
    app.include_router(build_platform_router(context))
    app.include_router(build_system_router(context))
    app.mount(
        "/",
        StaticFiles(
            directory=str(context.paths.frontend_dir),
            html=True,
            check_dir=False,
        ),
        name="frontend",
    )
    return app
