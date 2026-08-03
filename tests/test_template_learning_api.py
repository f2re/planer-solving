import json
from pathlib import Path

from fastapi.testclient import TestClient

from tests.auth_helpers import bootstrap_admin
from tests.test_schedule_analyzer import build_layered_schedule
from web.backend.app_factory import create_app


def test_learning_creates_composite_template_revisions_and_rules(tmp_path: Path) -> None:
    (tmp_path / "teachers.json").write_text(json.dumps([{
        "id": 1,
        "short_name": "Иванов И.И.",
        "full_name": "Иванов Иван Иванович",
    }], ensure_ascii=False), encoding="utf-8")
    workbook = tmp_path / "schedule.xlsx"
    build_layered_schedule(workbook)

    client = TestClient(create_app(tmp_path))
    bootstrap_admin(client)
    workspace_id = client.get("/api/workspaces").json()[0]["id"]
    with workbook.open("rb") as stream:
        analyzed = client.post(
            "/api/analyze",
            files={"files": (workbook.name, stream, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
    assert analyzed.status_code == 200, analyzed.text
    payload = analyzed.json()
    file_item = payload["files"][0]
    layout = file_item["analysis"]["layout"]

    learned = client.post(
        f"/api/workspaces/{workspace_id}/templates/learn",
        json={
            "session_id": payload["session_id"],
            "file_id": file_item["file_id"],
            "layout": layout,
            "template_name": "Формат кафедры",
            "component_label": "Основной лист",
            "comment": "Подтверждено оператором",
            "priority": 10,
        },
    )
    assert learned.status_code == 200, learned.text
    template = learned.json()["template"]
    assert len(template["layout"]["components"]) == 1
    assert template["layout"]["components"][0]["fingerprint"]["signature"]

    second_layout = {**layout, "weeks_row": layout["weeks_row"] + 1}
    second = client.post(
        f"/api/workspaces/{workspace_id}/templates/learn",
        json={
            "session_id": payload["session_id"],
            "file_id": file_item["file_id"],
            "layout": second_layout,
            "template_id": template["id"],
            "component_label": "Смещённая форма",
            "comment": "Добавлен второй вариант",
        },
    )
    assert second.status_code == 200, second.text
    updated = second.json()["template"]
    assert len(updated["layout"]["components"]) == 2
    assert updated["revision_number"] == 2

    revisions = client.get(
        f"/api/workspaces/{workspace_id}/templates/{template['id']}/revisions"
    ).json()
    assert [item["revision_number"] for item in revisions] == [2, 1]
    rules = client.get(f"/api/workspaces/{workspace_id}/format-rules").json()
    assert len(rules) == 2

    matched = client.post(
        f"/api/analysis/{payload['session_id']}/files/{file_item['file_id']}/match-templates",
        json={"workspace_id": workspace_id},
    )
    assert matched.status_code == 200, matched.text
    candidates = matched.json()["candidates"]
    template_candidate = next(item for item in candidates if item.get("template_id") == template["id"])
    assert template_candidate["component_id"]
    selected = client.post(
        f"/api/analysis/{payload['session_id']}/files/{file_item['file_id']}/select-template",
        json={"candidate_key": template_candidate["candidate_key"]},
    )
    assert selected.status_code == 200, selected.text
    assert selected.json()["template_id"] == template["id"]
