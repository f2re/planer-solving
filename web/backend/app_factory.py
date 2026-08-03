"""FastAPI application factory with explicit dependencies and route order."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from web.backend.analysis_api import build_analysis_router
from web.backend.analysis_selection_api import build_analysis_selection_router
from web.backend.app_context import ApplicationContext, WorkspaceRepository
from web.backend.audit_api import build_audit_router
from web.backend.auth_api import build_auth_router
from web.backend.errors import install_exception_handlers
from web.backend.history_api import build_history_router
from web.backend.import_api import build_import_router
from web.backend.session_api import build_session_router
from web.backend.system_api import build_system_router
from web.backend.template_revision_api import build_template_revision_router
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

    app.include_router(build_auth_router(context))
    app.include_router(build_analysis_router(context))
    app.include_router(build_analysis_selection_router(context))
    app.include_router(build_session_router(context))
    app.include_router(build_workspace_router(context))
    app.include_router(build_template_revision_router(context))
    app.include_router(build_import_router(context))
    app.include_router(build_schedule_router(context))
    app.include_router(build_history_router(context))
    app.include_router(build_audit_router(context))
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
