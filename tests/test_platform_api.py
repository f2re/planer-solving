from pathlib import Path

from fastapi.testclient import TestClient

from web.backend.app_factory import create_app

ADMIN_PASSWORD = "administrator-123"
VIEWER_PASSWORD = "viewer-password-123"
OPERATOR_PASSWORD = "operator-password-123"


def bootstrap_client(tmp_path: Path) -> tuple[TestClient, str]:
    (tmp_path / "web" / "frontend").mkdir(parents=True)
    (tmp_path / "web" / "frontend" / "index.html").write_text("ok", encoding="utf-8")
    client = TestClient(create_app(tmp_path))
    status = client.get("/api/auth/status").json()
    assert status["bootstrap_required"] is True
    response = client.post(
        "/api/auth/bootstrap",
        json={
            "username": "admin",
            "display_name": "Главный администратор",
            "password": ADMIN_PASSWORD,
        },
    )
    assert response.status_code == 200
    workspace_id = client.get("/api/workspaces").json()[0]["id"]
    return client, workspace_id


def login(client: TestClient, username: str, password: str) -> None:
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200


def test_roles_and_bootstrap_protect_mutations(tmp_path: Path):
    client, workspace_id = bootstrap_client(tmp_path)
    assert client.get("/api/auth/status").json()["authenticated"] is True

    viewer = client.post(
        "/api/admin/users",
        json={
            "username": "viewer",
            "display_name": "Наблюдатель",
            "password": VIEWER_PASSWORD,
            "role": "viewer",
        },
    )
    operator = client.post(
        "/api/admin/users",
        json={
            "username": "operator",
            "display_name": "Оператор",
            "password": OPERATOR_PASSWORD,
            "role": "operator",
        },
    )
    assert viewer.status_code == operator.status_code == 200

    assert client.post("/api/auth/logout").status_code == 200
    login(client, "viewer", VIEWER_PASSWORD)
    assert client.get("/api/workspaces").status_code == 200
    denied = client.post(
        f"/api/workspaces/{workspace_id}/teachers",
        json={"short_name": "Иванов И.И.", "full_name": "Иванов Иван Иванович"},
    )
    assert denied.status_code == 403
    assert denied.json()["code"] == "permission_denied"

    assert client.post("/api/auth/logout").status_code == 200
    login(client, "operator", OPERATOR_PASSWORD)
    preview = client.post(
        f"/api/workspaces/{workspace_id}/imports/preview?kind=teachers",
        files={
            "file": (
                "teachers.csv",
                "Полное ФИО;Краткое имя\nПетров Петр Петрович;Петров П.П.\n".encode("utf-8"),
                "text/csv",
            )
        },
    )
    assert preview.status_code == 200
    commit = client.post(
        f"/api/workspaces/{workspace_id}/imports/{preview.json()['id']}/commit",
        json={"decisions": {"1": "add"}},
    )
    assert commit.status_code == 403


def test_import_preview_is_read_only_until_admin_commit(tmp_path: Path):
    client, workspace_id = bootstrap_client(tmp_path)
    csv_payload = (
        "Полное ФИО;Краткое имя;Должность\n"
        "Иванов Иван Иванович;Иванов И.И.;Доцент\n"
        "Петров Петр Петрович;Петров П.П.;Профессор\n"
    ).encode("utf-8")
    response = client.post(
        f"/api/workspaces/{workspace_id}/imports/preview?kind=teachers",
        files={"file": ("teachers.csv", csv_payload, "text/csv")},
    )
    assert response.status_code == 200
    job = response.json()
    assert job["preview"]["counts"]["add"] == 2
    assert client.get(f"/api/workspaces/{workspace_id}/teachers").json() == []

    committed = client.post(
        f"/api/workspaces/{workspace_id}/imports/{job['id']}/commit",
        json={"decisions": {"1": "add", "2": "add"}},
    )
    assert committed.status_code == 200
    assert committed.json()["added"] == 2
    assert len(client.get(f"/api/workspaces/{workspace_id}/teachers").json()) == 2

    second_commit = client.post(
        f"/api/workspaces/{workspace_id}/imports/{job['id']}/commit",
        json={"decisions": {}},
    )
    assert second_commit.status_code == 400

    audit = client.get(f"/api/workspaces/{workspace_id}/audit").json()["items"]
    assert any(item["action"] == "import.commit" for item in audit)
