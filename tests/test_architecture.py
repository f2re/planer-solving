from pathlib import Path

from fastapi.testclient import TestClient

from web.backend.app_factory import create_app


def test_app_factory_registers_each_api_once_and_mounts_frontend_last(tmp_path: Path):
    (tmp_path / "web" / "frontend").mkdir(parents=True)
    (tmp_path / "web" / "frontend" / "index.html").write_text("ok", encoding="utf-8")
    (tmp_path / "VERSION").write_text("test\n", encoding="utf-8")

    app = create_app(tmp_path)
    api_paths = [getattr(route, "path", "") for route in app.router.routes]

    assert api_paths.count("/api/analyze") == 1
    assert api_paths.count("/api/teachers") == 2  # GET and POST are separate routes.
    assert api_paths.count("/api/health") == 1
    assert app.router.routes[-1].__class__.__name__ == "Mount"
    assert app.router.routes[-1].path == ""

    client = TestClient(app)
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["storage"] == "sqlite"


def test_workspace_validation_is_reported_by_central_error_handler(tmp_path: Path):
    (tmp_path / "web" / "frontend").mkdir(parents=True)
    app = create_app(tmp_path)
    client = TestClient(app)

    response = client.post(
        "/api/workspaces",
        json={
            "name": "Неверный семестр",
            "settings": {
                "schedule_start_date": "2026-09-01",
                "schedule_end_date": "2026-06-30",
            },
        },
    )

    assert response.status_code == 400
    assert response.json()["code"] == "workspace_error"
    assert "начала" in response.json()["detail"]


def test_main_entrypoint_contains_no_dynamic_exec():
    source = (Path(__file__).parents[1] / "web" / "backend" / "main.py").read_text(
        encoding="utf-8"
    )
    assert "exec(" not in source
    assert "legacy_main.py" not in source
    assert "create_app()" in source
