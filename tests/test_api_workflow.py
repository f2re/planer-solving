import json
from pathlib import Path

from fastapi.testclient import TestClient

from tests.test_schedule_analyzer import build_layered_schedule
from web.backend.app_factory import create_app
from web.backend import workspace_schedule


def test_operator_api_workflow_and_repeat_from_history(tmp_path: Path, monkeypatch) -> None:
    teachers = tmp_path / "teachers.json"
    teachers.write_text(
        json.dumps([{
            "id": 1,
            "short_name": "Иванов И.И.",
            "full_name": "Иванов Иван Иванович",
            "position": "",
            "rank": "",
            "academic_degree": "",
        }], ensure_ascii=False),
        encoding="utf-8",
    )

    def fake_export(data, teachers_config, output_path):
        from openpyxl import Workbook
        workbook = Workbook()
        workbook.active["A1"] = len(data.get("grid", {}))
        workbook.save(output_path)

    monkeypatch.setattr(workspace_schedule, "export_to_excel", fake_export)
    schedule = tmp_path / "522.xlsx"
    build_layered_schedule(schedule)
    client = TestClient(create_app(tmp_path))
    workspace_id = client.get("/api/workspaces").json()[0]["id"]

    with schedule.open("rb") as file:
        response = client.post(
            "/api/analyze",
            files={"files": (
                schedule.name,
                file,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )},
        )
    assert response.status_code == 200
    analyzed = response.json()
    item = analyzed["files"][0]
    assert item["analysis"]["layout"]["weeks_row"] == 7

    validation = client.post(
        f"/api/analysis/{analyzed['session_id']}/validate",
        json={
            "file_id": item["file_id"],
            "group_name": "522",
            "layout": item["analysis"]["layout"],
            "workspace_id": workspace_id,
        },
    )
    assert validation.status_code == 200
    report = validation.json()["report"]
    assert report["lesson_count"] == 72
    assert report["unknown_teacher_lessons"] == 0

    generated = client.post(
        f"/api/analysis/{analyzed['session_id']}/generate",
        json={
            "workspace_id": workspace_id,
            "files": [{
                "file_id": item["file_id"],
                "group_name": "522",
                "layout": item["analysis"]["layout"],
                "enabled": True,
            }],
        },
    )
    assert generated.status_code == 200
    payload = generated.json()
    assert payload["filename"]
    assert payload["run_id"]
    assert (tmp_path / "output" / payload["filename"]).exists()

    repeated = client.post(
        f"/api/workspaces/{workspace_id}/runs/{payload['run_id']}/repeat"
    )
    assert repeated.status_code == 200
    repeated_payload = repeated.json()
    assert repeated_payload["run_id"] != payload["run_id"]
    assert (tmp_path / "output" / repeated_payload["filename"]).exists()

    runs = client.get(f"/api/workspaces/{workspace_id}/runs").json()["items"]
    assert len(runs) == 2
    assert all(run["lesson_count"] == 72 for run in runs)
