from pathlib import Path

from fastapi.testclient import TestClient

from src.security import hash_password, verify_password
from src.transactional_platform_store import TransactionalPlatformStore
from tools.user_admin import main as user_admin_main
from web.backend.app_factory import create_app


def test_password_hash_accepts_short_and_empty_values():
    empty = hash_password("")
    short = hash_password("1")
    assert verify_password("", empty)
    assert verify_password("1", short)
    assert not verify_password("2", short)


def test_bootstrap_login_and_admin_reset_allow_empty_password(tmp_path: Path):
    (tmp_path / "web" / "frontend").mkdir(parents=True)
    (tmp_path / "web" / "frontend" / "index.html").write_text("ok", encoding="utf-8")
    app = create_app(tmp_path)
    client = TestClient(app)

    bootstrap = client.post(
        "/api/auth/bootstrap",
        json={"username": "admin", "display_name": "Администратор"},
    )
    assert bootstrap.status_code == 200
    user_id = bootstrap.json()["user"]["id"]
    assert client.post("/api/auth/logout").status_code == 200
    assert client.post(
        "/api/auth/login",
        json={"username": "admin", "password": ""},
    ).status_code == 200

    reset = client.post(
        f"/api/admin/users/{user_id}/reset-password",
        json={"password": "x"},
    )
    assert reset.status_code == 200
    # All previous sessions are revoked, but resetting oneself receives a fresh session.
    assert client.get("/api/admin/users").status_code == 200

    outsider = TestClient(app)
    assert outsider.post(
        "/api/auth/login",
        json={"username": "admin", "password": ""},
    ).status_code == 401
    assert outsider.post(
        "/api/auth/login",
        json={"username": "admin", "password": "x"},
    ).status_code == 200


def test_command_line_password_reset(tmp_path: Path):
    data_dir = tmp_path / "data"
    teachers = tmp_path / "teachers.json"
    teachers.write_text("[]\n", encoding="utf-8")
    store = TransactionalPlatformStore(
        data_dir / "planner-solving.sqlite3",
        data_dir / "workspaces.json",
        teachers,
    )
    store.bootstrap_admin("admin", "Администратор", "old")

    assert user_admin_main([
        "--data-dir", str(data_dir),
        "--legacy-teachers", str(teachers),
        "reset-password", "admin", "--empty",
    ]) == 0

    reopened = TransactionalPlatformStore(
        data_dir / "planner-solving.sqlite3",
        data_dir / "workspaces.json",
        teachers,
    )
    assert reopened.authenticate("admin", "") is not None
