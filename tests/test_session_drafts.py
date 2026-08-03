from pathlib import Path

from fastapi.testclient import TestClient

from tests.test_schedule_analyzer import build_layered_schedule
from web.backend.app_factory import create_app


MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def analyze(client: TestClient, path: Path) -> dict:
    with path.open("rb") as source:
        response = client.post(
            "/api/analyze",
            files={"files": (path.name, source, MIME_XLSX)},
        )
    assert response.status_code == 200
    return response.json()


def test_operator_draft_survives_reload_and_detects_conflicts(tmp_path: Path) -> None:
    schedule = tmp_path / "group-101.xlsx"
    build_layered_schedule(schedule)

    first_app = create_app(tmp_path)
    first_client = TestClient(first_app)
    workspace_id = first_client.get("/api/workspaces").json()[0]["id"]
    analyzed = analyze(first_client, schedule)
    session_id = analyzed["session_id"]
    file = analyzed["files"][0]

    payload = {
        "version": 1,
        "base_revision": 0,
        "workspace_id": workspace_id,
        "step": 2,
        "selected_file_id": file["file_id"],
        "file_states": [
            {
                "file_id": file["file_id"],
                "group_name": "101-А",
                "enabled": True,
            },
            {
                "file_id": "missing-file",
                "group_name": "Не должна сохраниться",
                "enabled": True,
            },
        ],
        "layouts": {
            file["file_id"]: file["analysis"]["layout"],
            "missing-file": {"sheet_name": "ghost"},
        },
        "validations": {
            file["file_id"]: {
                "status": "warning",
                "report": {
                    "lesson_count": 72,
                    "generation_allowed": True,
                    "issues": [],
                },
            }
        },
        "period_overrides": {
            file["file_id"]: {
                "week_day_dates": {"1:Пн": "2027-02-01"},
                "week_months": {},
                "teacher_overrides": {"Математика": "Иванов И.И."},
            }
        },
        "calendar_overrides": {
            "policy": "source",
            "week_day_dates": {},
            "week_months": {},
        },
        "editor": {
            "preview_region": "schedule",
            "period_editor_open": True,
        },
    }

    saved = first_client.put(
        f"/api/analysis/{session_id}/draft",
        json=payload,
    )
    assert saved.status_code == 200
    assert saved.json()["revision"] == 1
    assert saved.json()["file_count"] == 1

    second_app = create_app(tmp_path)
    second_client = TestClient(second_app)
    restored = second_client.get(f"/api/analysis/{session_id}/draft")
    assert restored.status_code == 200
    restored_payload = restored.json()
    assert restored_payload["revision"] == 1
    assert restored_payload["draft"]["workspace_id"] == workspace_id
    assert restored_payload["draft"]["selected_file_id"] == file["file_id"]
    assert restored_payload["draft"]["file_states"] == [{
        "file_id": file["file_id"],
        "group_name": "101-А",
        "enabled": True,
    }]
    assert "missing-file" not in restored_payload["draft"]["layouts"]
    assert restored_payload["draft"]["period_overrides"][file["file_id"]]["teacher_overrides"] == {
        "Математика": "Иванов И.И."
    }
    assert restored_payload["files"][0]["analysis"]
    assert "stored_name" not in restored_payload["files"][0]

    conflict = second_client.put(
        f"/api/analysis/{session_id}/draft",
        json={**payload, "base_revision": 0},
    )
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "draft_revision_conflict"

    updated = second_client.put(
        f"/api/analysis/{session_id}/draft",
        json={**payload, "base_revision": 1, "step": 3},
    )
    assert updated.status_code == 200
    assert updated.json()["revision"] == 2
    assert second_client.get(f"/api/analysis/{session_id}/draft").json()["draft"]["step"] == 3

    deleted = second_client.delete(f"/api/analysis/{session_id}/draft")
    assert deleted.status_code == 200
    empty = second_client.get(f"/api/analysis/{session_id}/draft")
    assert empty.status_code == 200
    assert empty.json()["revision"] == 0
    assert empty.json()["draft"] is None
