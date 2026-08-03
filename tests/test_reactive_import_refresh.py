from pathlib import Path

from fastapi.testclient import TestClient

from web.backend.app_factory import create_app


def test_committed_import_is_visible_immediately_from_workspace_endpoints(tmp_path: Path):
    (tmp_path / "web" / "frontend").mkdir(parents=True)
    client = TestClient(create_app(tmp_path))
    workspace_id = client.get("/api/workspaces").json()[0]["id"]
    payload = (
        "Полное ФИО;Краткое имя;Должность\n"
        "Иванов Иван Иванович;Иванов И.И.;Доцент\n"
    ).encode("utf-8")
    preview = client.post(
        f"/api/workspaces/{workspace_id}/imports/preview?kind=teachers",
        files={"file": ("teachers.csv", payload, "text/csv")},
    )
    assert preview.status_code == 200
    job = preview.json()
    commit = client.post(
        f"/api/workspaces/{workspace_id}/imports/{job['id']}/commit",
        json={"decisions": {"1": "add"}},
    )
    assert commit.status_code == 200

    teachers = client.get(f"/api/workspaces/{workspace_id}/teachers").json()
    spaces = client.get("/api/workspaces").json()
    assert [item["full_name"] for item in teachers] == ["Иванов Иван Иванович"]
    assert next(item for item in spaces if item["id"] == workspace_id)["teacher_count"] == 1
