"""Application entrypoint with workspace extensions over the stable schedule core."""
from pathlib import Path
import sys

from fastapi import HTTPException

from src.data_migrations import CURRENT_SCHEMA_VERSION
from src.workspace_store import WorkspaceStore

# Execute the proven schedule core in this module so existing deployments and
# tests can still override BASE_DIR, INPUT_DIR and related settings.
_core = Path(__file__).with_name("legacy_main.py")
exec(compile(_core.read_text(encoding="utf-8"), str(_core), "exec"), globals())

from web.backend.workspace_api import install_workspace_api  # noqa: E402

app = install_workspace_api(app, sys.modules[__name__])


def _application_version() -> str:
    try:
        return (BASE_DIR / "VERSION").read_text(encoding="utf-8").strip() or "unknown"
    except OSError:
        return "unknown"


def _system_status() -> dict:
    try:
        document = WorkspaceStore(
            BASE_DIR / "data" / "workspaces.json",
            TEACHERS_JSON,
        ).load()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Хранилище данных недоступно: {exc}") from exc
    return {
        "status": "ok",
        "app_version": _application_version(),
        "data_schema_version": document.get("version", 0),
        "supported_data_schema_version": CURRENT_SCHEMA_VERSION,
    }


app.add_api_route("/api/health", _system_status, methods=["GET"], tags=["system"])
app.add_api_route("/api/system/version", _system_status, methods=["GET"], tags=["system"])

# A mount at "/" must always remain after all API routes, otherwise StaticFiles
# intercepts newly added endpoints.
app.router.routes[:] = [
    route for route in app.router.routes if route.__class__.__name__ != "Mount"
] + [
    route for route in app.router.routes if route.__class__.__name__ == "Mount"
]
