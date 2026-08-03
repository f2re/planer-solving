from pathlib import Path

from fastapi.testclient import TestClient

from tests.auth_helpers import bootstrap_admin, create_user, login
from web.backend.app_factory import create_app


def test_bootstrap_csrf_roles_and_audit(tmp_path: Path) -> None:
    app = create_app(tmp_path)
    admin_client = TestClient(app)

    assert admin_client.get("/api/auth/status").json()["setup_required"] is True
    bootstrap_admin(admin_client)
    assert admin_client.get("/api/auth/status").json()["user"]["role"] == "admin"

    without_csrf = admin_client.post(
        "/api/workspaces",
        json={"name": "Без токена"},
        headers={"X-CSRF-Token": ""},
    )
    assert without_csrf.status_code == 403
    assert without_csrf.json()["code"] == "permission_denied"

    create_user(
        admin_client,
        username="operator",
        display_name="Оператор",
        password="Operator-pass-123",
        role="operator",
    )
    viewer = create_user(
        admin_client,
        username="viewer",
        display_name="Наблюдатель",
        password="Viewer-pass-123",
        role="viewer",
    )

    operator_client = TestClient(app)
    login(operator_client, username="operator", password="Operator-pass-123")
    assert operator_client.get("/api/workspaces").status_code == 200
    assert operator_client.post("/api/workspaces", json={"name": "Нельзя"}).status_code == 403

    workspace_id = admin_client.get("/api/workspaces").json()[0]["id"]
    template = operator_client.post(
        f"/api/workspaces/{workspace_id}/templates",
        json={
            "name": "Операторский шаблон",
            "layout": {"sheet_name": "Лист1", "weeks_row": 7},
            "comment": "Создан оператором",
        },
    )
    assert template.status_code == 200, template.text

    viewer_client = TestClient(app)
    login(viewer_client, username="viewer", password="Viewer-pass-123")
    assert viewer_client.get(f"/api/workspaces/{workspace_id}/templates").status_code == 200
    assert viewer_client.post(
        f"/api/workspaces/{workspace_id}/templates",
        json={"name": "Запрещено", "layout": {"weeks_row": 1}},
    ).status_code == 403
    assert viewer_client.get("/api/audit").status_code == 403

    users = admin_client.get("/api/auth/users").json()
    admin = next(item for item in users if item["username"] == "admin")
    cannot_disable = admin_client.put(
        f"/api/auth/users/{admin['id']}",
        json={"active": False},
    )
    assert cannot_disable.status_code == 400

    audit = admin_client.get("/api/audit").json()
    assert any(entry["entity_type"] == "template" for entry in audit)
    assert any(entry["entity_id"] == viewer["id"] for entry in audit)
