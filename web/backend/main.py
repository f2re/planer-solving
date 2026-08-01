"""Application entrypoint with workspace extensions over the stable schedule core."""
import json
from pathlib import Path
import sys

from fastapi import HTTPException

from src.data_migrations import (
    CURRENT_SCHEMA_VERSION,
    MigrationError,
    detect_schema_version,
)
from src.workspace_store import WorkspaceError, WorkspaceStore


def _install_workspace_schema_guard() -> None:
    """Prevent direct Uvicorn startup from rewriting data created by a newer app."""
    original_load = WorkspaceStore.load
    if getattr(original_load, "_planner_schema_guard", False):
        return

    def guarded_load(store: WorkspaceStore):
        if store.path.exists():
            try:
                payload = json.loads(store.path.read_text(encoding="utf-8"))
                version = detect_schema_version(payload)
            except (OSError, json.JSONDecodeError, MigrationError) as exc:
                raise WorkspaceError(f"Не удалось проверить версию данных: {exc}") from exc
            if version > CURRENT_SCHEMA_VERSION:
                raise WorkspaceError(
                    f"Данные имеют версию {version}, а приложение поддерживает только "
                    f"версию {CURRENT_SCHEMA_VERSION}. Установите более новую версию приложения."
                )
        return original_load(store)

    guarded_load._planner_schema_guard = True  # type: ignore[attr-defined]
    WorkspaceStore.load = guarded_load  # type: ignore[method-assign]


_install_workspace_schema_guard()

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
