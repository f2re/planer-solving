import json
from pathlib import Path

from fastapi.testclient import TestClient

from tests.test_schedule_analyzer import build_layered_schedule
from web.backend import main as backend


def test_operator_api_workflow(tmp_path: Path, monkeypatch) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    session_root = input_dir / "analysis_sessions"
    for directory in (input_dir, output_dir, session_root):
        directory.mkdir(parents=True, exist_ok=True)
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
    monkeypatch.setattr(backend, "BASE_DIR", tmp_path)
    monkeypatch.setattr(backend, "INPUT_DIR", input_dir)
    monkeypatch.setattr(backend, "OUTPUT_DIR", output_dir)
    monkeypatch.setattr(backend, "SESSION_ROOT", session_root)
    monkeypatch.setattr(backend, "TEACHERS_JSON", teachers)

    def fake_export(data, teachers_config, output_path):
        from openpyxl import Workbook
        workbook = Workbook()
        workbook.active["A1"] = len(data.get("grid", {}))
        workbook.save(output_path)

    monkeypatch.setattr(backend, "export_to_excel", fake_export)
    schedule = tmp_path / "522.xlsx"
    build_layered_schedule(schedule)
    client = TestClient(backend.app)

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
        },
    )
    assert validation.status_code == 200
    report = validation.json()["report"]
    assert report["lesson_count"] == 72
    assert report["unknown_teacher_lessons"] == 0

    generated = client.post(
        f"/api/analysis/{analyzed['session_id']}/generate",
        json={"files": [{
            "file_id": item["file_id"],
            "group_name": "522",
            "layout": item["analysis"]["layout"],
            "enabled": True,
        }]},
    )
    assert generated.status_code == 200
    payload = generated.json()
    assert payload["filename"]
    assert (output_dir / payload["filename"]).exists()
