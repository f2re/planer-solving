import json
from pathlib import Path

from fastapi.testclient import TestClient

from src.data_migrations import CURRENT_SCHEMA_VERSION
from web.backend import main as backend


def test_health_reports_application_and_schema_versions(tmp_path: Path, monkeypatch) -> None:
    teachers = tmp_path / "teachers.json"
    teachers.write_text(json.dumps([
        {"id": 1, "short_name": "Иванов", "full_name": "Иванов Иван Иванович"}
    ], ensure_ascii=False), encoding="utf-8")
    (tmp_path / "VERSION").write_text("test-version\n", encoding="utf-8")
    monkeypatch.setattr(backend, "BASE_DIR", tmp_path)
    monkeypatch.setattr(backend, "TEACHERS_JSON", teachers)

    response = TestClient(backend.app).get("/api/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["app_version"] == "test-version"
    assert payload["data_schema_version"] == CURRENT_SCHEMA_VERSION
    assert payload["supported_data_schema_version"] == CURRENT_SCHEMA_VERSION
    assert (tmp_path / "data" / "workspaces.json").exists()


def test_future_schema_is_blocked_without_rewriting(tmp_path: Path, monkeypatch) -> None:
    teachers = tmp_path / "teachers.json"
    teachers.write_text("[]\n", encoding="utf-8")
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    future = {
        "version": CURRENT_SCHEMA_VERSION + 1,
        "default_workspace_id": "future",
        "workspaces": [{"id": "future", "new_field": "must-survive"}],
    }
    workspace_path = data_dir / "workspaces.json"
    original = json.dumps(future, ensure_ascii=False, indent=2)
    workspace_path.write_text(original, encoding="utf-8")
    (tmp_path / "VERSION").write_text("old-app\n", encoding="utf-8")
    monkeypatch.setattr(backend, "BASE_DIR", tmp_path)
    monkeypatch.setattr(backend, "TEACHERS_JSON", teachers)

    response = TestClient(backend.app).get("/api/health")
    assert response.status_code == 503
    assert "более новую версию" in response.json()["detail"]
    assert workspace_path.read_text(encoding="utf-8") == original
