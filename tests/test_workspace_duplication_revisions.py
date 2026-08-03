from pathlib import Path

from fastapi.testclient import TestClient

from tests.auth_helpers import bootstrap_admin
from web.backend.app_factory import create_app


def test_duplicated_workspace_templates_receive_initial_revisions_immediately(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path))
    bootstrap_admin(client)
    workspace_id = client.get("/api/workspaces").json()[0]["id"]
    created = client.post(
        f"/api/workspaces/{workspace_id}/templates",
        json={
            "name": "Исходный формат",
            "layout": {"sheet_name": "Лист1", "weeks_row": 7},
            "comment": "До копирования пространства",
        },
    )
    assert created.status_code == 200, created.text

    duplicated = client.post(
        f"/api/workspaces/{workspace_id}/duplicate",
        json={"name": "Копия для нового семестра"},
    )
    assert duplicated.status_code == 200, duplicated.text
    duplicate_id = duplicated.json()["id"]
    templates = client.get(f"/api/workspaces/{duplicate_id}/templates")
    assert templates.status_code == 200, templates.text
    copied = templates.json()[0]
    assert copied["revision_number"] == 1
    revisions = client.get(
        f"/api/workspaces/{duplicate_id}/templates/{copied['id']}/revisions"
    )
    assert revisions.status_code == 200, revisions.text
    assert revisions.json()[0]["revision_number"] == 1
