import json
from pathlib import Path
import sqlite3

from fastapi.testclient import TestClient
import pytest

from src.data_migrations import CURRENT_SCHEMA_VERSION
from src.sqlite_workspace_store import SQLITE_SCHEMA_VERSION
from src.workspace_store import WorkspaceError
from web.backend.app_factory import create_app


def test_health_reports_application_and_schema_versions(tmp_path: Path) -> None:
    teachers = tmp_path / "teachers.json"
    teachers.write_text(json.dumps([
        {"id": 1, "short_name": "Иванов", "full_name": "Иванов Иван Иванович"}
    ], ensure_ascii=False), encoding="utf-8")
    (tmp_path / "VERSION").write_text("test-version\n", encoding="utf-8")

    response = TestClient(create_app(tmp_path)).get("/api/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["app_version"] == "test-version"
    assert payload["data_schema_version"] == CURRENT_SCHEMA_VERSION
    assert payload["supported_data_schema_version"] == CURRENT_SCHEMA_VERSION
    assert payload["storage_schema_version"] == SQLITE_SCHEMA_VERSION
    assert payload["storage"] == "sqlite"
    assert (tmp_path / "data" / "workspaces.json").exists()
    assert (tmp_path / "data" / "planner-solving.sqlite3").exists()


def test_future_schema_is_blocked_without_rewriting(tmp_path: Path) -> None:
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

    with pytest.raises(WorkspaceError, match="более новую версию"):
        create_app(tmp_path)

    assert workspace_path.read_text(encoding="utf-8") == original
    assert not (data_dir / "planner-solving.sqlite3").exists()


def test_future_sqlite_schema_is_blocked_without_downgrade(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    database = data_dir / "planner-solving.sqlite3"
    future_version = SQLITE_SCHEMA_VERSION + 1
    connection = sqlite3.connect(database)
    try:
        connection.execute(f"PRAGMA user_version = {future_version}")
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(WorkspaceError, match="База SQLite имеет версию"):
        create_app(tmp_path)

    connection = sqlite3.connect(database)
    try:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == future_version
    finally:
        connection.close()
