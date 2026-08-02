import json
from pathlib import Path

from fastapi.testclient import TestClient

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
    return TestClient(create_app(tmp_path))


def test_workspace_teacher_and_template_api(tmp_path: Path) -> None:
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
    assert created.status_code == 200
    workspace_id = created.json()["id"]

    teacher = client.post(f"/api/workspaces/{workspace_id}/teachers", json={
        "short_name": "Петров П.П.",
        "full_name": "Петров Петр Петрович",
        "position": "Профессор",
    })
    assert teacher.status_code == 200
    assert client.get(f"/api/workspaces/{workspace_id}/teachers").json()[0]["short_name"] == "Петров П.П."

    template = client.post(f"/api/workspaces/{workspace_id}/templates", json={
        "name": "Осенний формат",
        "description": "Основная форма",
        "layout": {"weeks_row": 7, "first_week_col": 5},
    })
    assert template.status_code == 200
    template_id = template.json()["id"]
    updated = client.put(
        f"/api/workspaces/{workspace_id}/templates/{template_id}",
        json={"description": "Исправленная форма"},
    )
    assert updated.status_code == 200
    assert updated.json()["description"] == "Исправленная форма"

    exported = client.get(f"/api/workspaces/{workspace_id}/export")
    assert exported.status_code == 200
    assert exported.json()["workspace"]["name"] == "Метеорология"


def test_teacher_csv_import(tmp_path: Path) -> None:
    client = configure_storage(tmp_path)
    workspace_id = client.get("/api/workspaces").json()[0]["id"]
    csv_payload = (
        "Краткое имя;Полное ФИО;Должность;Звание;Степень\n"
        "Сидоров С.С.;Сидоров Сидор Сидорович;Доцент;;к.г.н.\n"
    ).encode("utf-8")
    response = client.post(
        f"/api/workspaces/{workspace_id}/teachers/import?mode=append",
        files={"file": ("teachers.csv", csv_payload, "text/csv")},
    )
    assert response.status_code == 200
    assert response.json()["added"] == 1
    exported = client.get(f"/api/workspaces/{workspace_id}/teachers/export?format=csv")
    assert exported.status_code == 200
    assert "Сидоров" in exported.content.decode("utf-8-sig")
