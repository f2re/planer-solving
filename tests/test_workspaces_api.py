import json
from pathlib import Path

from fastapi.testclient import TestClient

from tests.auth_helpers import bootstrap_admin
from web.backend.app_factory import create_app


def configure_storage(tmp_path: Path) -> TestClient:
    teachers = tmp_path / "teachers.json"
    teachers.write_text(json.dumps([{
        "id": 1,
        "short_name": "Иванов И.И.",
        "full_name": "Иванов Иван Иванович",
        "position": "Доцент",
        "rank": "",
        "academic_degree": "к.т.н.",
    }], ensure_ascii=False), encoding="utf-8")
    client = TestClient(create_app(tmp_path))
    bootstrap_admin(client)
    return client


def test_workspace_teacher_and_revisioned_template_api(tmp_path: Path) -> None:
    client = configure_storage(tmp_path)
    spaces = client.get("/api/workspaces")
    assert spaces.status_code == 200
    default_space = spaces.json()[0]
    assert default_space["teacher_count"] == 1

    created = client.post("/api/workspaces", json={
        "name": "Метеорология",
        "color": "#16A085",
        "description": "Отдельная кафедра",
        "settings": {
            "schedule_start_date": "2026-09-01",
            "schedule_end_date": "2027-01-31",
        },
    })
    assert created.status_code == 200, created.text
    workspace_id = created.json()["id"]

    teacher = client.post(f"/api/workspaces/{workspace_id}/teachers", json={
        "short_name": "Петров П.П.",
        "full_name": "Петров Петр Петрович",
        "position": "Профессор",
    })
    assert teacher.status_code == 200, teacher.text
    assert client.get(f"/api/workspaces/{workspace_id}/teachers").json()[0]["short_name"] == "Петров П.П."

    template = client.post(f"/api/workspaces/{workspace_id}/templates", json={
        "name": "Осенний формат",
        "description": "Основная форма",
        "layout": {"weeks_row": 7, "first_week_col": 5},
        "comment": "Первая версия",
    })
    assert template.status_code == 200, template.text
    template_id = template.json()["id"]
    assert template.json()["revision_number"] == 1

    updated = client.put(
        f"/api/workspaces/{workspace_id}/templates/{template_id}",
        json={"description": "Исправленная форма", "comment": "Уточнено описание"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["description"] == "Исправленная форма"
    assert updated.json()["revision_number"] == 2

    revisions = client.get(
        f"/api/workspaces/{workspace_id}/templates/{template_id}/revisions"
    ).json()
    assert [item["revision_number"] for item in revisions] == [2, 1]
    comparison = client.get(
        "/api/template-revisions/compare",
        params={"from": revisions[1]["id"], "to": revisions[0]["id"]},
    )
    assert comparison.status_code == 200
    assert any(item["path"] == "value" or "description" in item["path"] for item in comparison.json()["changes"]) is False

    rollback = client.post(
        f"/api/workspaces/{workspace_id}/templates/{template_id}/rollback",
        json={"revision_id": revisions[1]["id"], "comment": "Возврат для проверки"},
    )
    assert rollback.status_code == 200, rollback.text
    assert rollback.json()["revision_number"] == 3

    exported = client.get(f"/api/workspaces/{workspace_id}/export")
    assert exported.status_code == 200
    assert exported.json()["workspace"]["name"] == "Метеорология"


def test_teacher_csv_import_wizard_does_not_write_before_confirmation(tmp_path: Path) -> None:
    client = configure_storage(tmp_path)
    workspace_id = client.get("/api/workspaces").json()[0]["id"]
    before = client.get(f"/api/workspaces/{workspace_id}/teachers").json()
    csv_payload = (
        "Служебный отчёт;;;;\n"
        "Краткое имя;Полное ФИО;Должность;Звание;Степень\n"
        "Сидоров С.С.;Сидоров Сидор Сидорович;Доцент;;к.г.н.\n"
        "Иванов И.И.;Иванов Иван Иванович;Профессор;;к.т.н.\n"
    ).encode("utf-8")

    preview = client.post(
        f"/api/workspaces/{workspace_id}/imports/preview?kind=teachers",
        files={"file": ("teachers.csv", csv_payload, "text/csv")},
    )
    assert preview.status_code == 200, preview.text
    job = preview.json()
    assert job["metadata"]["header_row"] == 2
    assert job["evaluation"]["summary"]["add"] == 1
    assert len(client.get(f"/api/workspaces/{workspace_id}/teachers").json()) == len(before)

    evaluated = client.post(
        f"/api/imports/{job['id']}/evaluate",
        json={"mapping": job["mapping"], "mode": "append"},
    )
    assert evaluated.status_code == 200, evaluated.text
    decisions = [
        {
            "row_index": row["row_index"],
            "action": "update" if row["suggested_action"] == "update" else row["suggested_action"],
        }
        for row in evaluated.json()["evaluation"]["rows"]
        if row["suggested_action"] != "error"
    ]
    committed = client.post(
        f"/api/imports/{job['id']}/commit",
        json={"mode": "append", "decisions": decisions},
    )
    assert committed.status_code == 200, committed.text
    assert committed.json()["added"] == 1
    assert committed.json()["updated"] == 1
    teachers = client.get(f"/api/workspaces/{workspace_id}/teachers").json()
    assert {item["short_name"] for item in teachers} == {"Иванов И.И.", "Сидоров С.С."}

    report = client.get(f"/api/imports/{job['id']}/report.csv")
    assert report.status_code == 200
    assert "Сидоров" in report.content.decode("utf-8-sig")
