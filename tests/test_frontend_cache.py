from pathlib import Path

from fastapi.testclient import TestClient

from web.backend.app_factory import create_app


def test_frontend_entrypoint_and_modules_are_revalidated_after_update(tmp_path: Path):
    frontend = tmp_path / "web" / "frontend"
    assets = frontend / "assets"
    assets.mkdir(parents=True)
    (frontend / "index.html").write_text("<!doctype html><title>planner</title>", encoding="utf-8")
    (assets / "app.js").write_text("console.log('planner')", encoding="utf-8")
    (tmp_path / "VERSION").write_text("test\n", encoding="utf-8")

    client = TestClient(create_app(tmp_path))
    html = client.get("/")
    script = client.get("/assets/app.js")

    assert html.status_code == 200
    assert "no-store" in html.headers["cache-control"]
    assert html.headers["pragma"] == "no-cache"
    assert script.status_code == 200
    assert script.headers["cache-control"] == "no-cache, must-revalidate"
