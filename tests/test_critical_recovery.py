import errno
import sqlite3

from fastapi import FastAPI
from fastapi.testclient import TestClient

from web.backend.app_factory import create_app
from web.backend.errors import SessionNotFound, install_exception_handlers
from web.backend.recovery_catalog import CATALOG, recovery_for


def test_every_critical_catalog_entry_has_guidance_and_tool():
    critical = {code: item for code, item in CATALOG.items() if item.get("severity") == "critical"}
    assert critical
    for code, item in critical.items():
        assert item.get("guidance"), code
        assert item.get("actions"), code
        assert any(action.get("label") and action.get("description") for action in item["actions"]), code
        assert item.get("state_preserved") is not None, code
        for action in item["actions"]:
            target = str(action.get("target") or "")
            assert not target.startswith(("http://", "https://")), (code, target)


def test_recovery_descriptor_contains_incident_and_request_context():
    result = recovery_for(
        "output_write_failed",
        detail="disk full",
        incident_id="abc123",
        request_path="/api/analysis/1/generate",
    )
    assert result["code"] == "output_write_failed"
    assert result["incident_id"] == "abc123"
    assert result["request_path"].endswith("/generate")
    assert result["state_preserved"] is True
    assert any(action["type"] == "open_diagnostics" for action in result["actions"])
    assert any(action["type"] == "generate_now" for action in result["actions"])


def _error_app() -> TestClient:
    app = FastAPI()
    install_exception_handlers(app)

    @app.get("/api/test/session")
    def session_error():
        raise SessionNotFound("Сеанс анализа не найден или истёк.")

    @app.post("/api/test/generate")
    def output_error():
        raise OSError(errno.ENOSPC, "No space left on device")

    @app.get("/api/test/sqlite")
    def sqlite_error():
        raise sqlite3.OperationalError("database is locked")

    return TestClient(app, raise_server_exceptions=False)


def test_session_error_explains_history_and_new_session():
    response = _error_app().get("/api/test/session")
    assert response.status_code == 404
    payload = response.json()
    assert payload["code"] == "session_not_found"
    assert payload["incident_id"]
    assert response.headers["x-planner-incident"] == payload["incident_id"]
    recovery = payload["recovery"]
    assert recovery["state_preserved"] is False
    action_types = {item["type"] for item in recovery["actions"]}
    assert {"open_history", "start_new_session"} <= action_types


def test_disk_full_is_classified_as_retryable_output_failure():
    response = _error_app().post("/api/test/generate")
    assert response.status_code == 507
    payload = response.json()
    assert payload["code"] == "output_write_failed"
    recovery = payload["recovery"]
    assert recovery["retryable"] is True
    assert recovery["state_preserved"] is True
    assert any(item["type"] == "open_diagnostics" for item in recovery["actions"])


def test_sqlite_failure_points_to_storage_recovery():
    response = _error_app().get("/api/test/sqlite")
    assert response.status_code == 503
    payload = response.json()
    assert payload["code"] == "workspace_error"
    assert payload["recovery"]["severity"] == "critical"
    assert any(item.get("requires_admin") for item in payload["recovery"]["actions"])


def test_recovery_endpoint_reports_tools_and_writable_directories(tmp_path):
    client = TestClient(create_app(tmp_path))
    response = client.get("/api/system/recovery")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] in {"ok", "warning", "critical"}
    assert payload["checks"]
    assert any(item["title"] == "Результаты" for item in payload["checks"])
    assert any("planner-solving-doctor" in command for command in payload["admin_commands"])
    assert "safe_to_retry" in payload
