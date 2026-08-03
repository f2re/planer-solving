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


def test_files_can_change_inside_active_session(tmp_path: Path) -> None:
    first_path = tmp_path / "group-101.xlsx"
    second_path = tmp_path / "group-202.xlsx"
    replacement_path = tmp_path / "replacement.xlsx"
    build_layered_schedule(first_path)
    build_layered_schedule(second_path)
    build_layered_schedule(replacement_path)

    app = create_app(tmp_path)
    client = TestClient(app)
    workspace_id = client.get("/api/workspaces").json()[0]["id"]

    analyzed = analyze(client, first_path)
    session_id = analyzed["session_id"]
    original = analyzed["files"][0]

    with second_path.open("rb") as source:
        appended_response = client.post(
            f"/api/analysis/{session_id}/files",
            files={"files": (second_path.name, source, MIME_XLSX)},
        )
    assert appended_response.status_code == 200
    appended = appended_response.json()["files"][0]
    assert appended_response.json()["session_id"] == session_id
    assert appended["analysis"]
    assert appended["file_id"] != original["file_id"]

    with replacement_path.open("rb") as source:
        replaced_response = client.put(
            f"/api/analysis/{session_id}/files/{original['file_id']}",
            files={"file": (replacement_path.name, source, MIME_XLSX)},
        )
    assert replaced_response.status_code == 200
    replaced = replaced_response.json()
    assert replaced["file_id"] == original["file_id"]
    assert replaced["group_name"] == original["group_name"]
    assert replaced["filename"] == replacement_path.name
    assert replaced["analysis"]

    damaged_path = tmp_path / "damaged.xlsx"
    damaged_path.write_bytes(b"not-an-excel-workbook")
    with damaged_path.open("rb") as source:
        rejected_response = client.put(
            f"/api/analysis/{session_id}/files/{original['file_id']}",
            files={"file": (damaged_path.name, source, MIME_XLSX)},
        )
    assert rejected_response.status_code == 422
    assert "Прежний исходник" in rejected_response.json()["detail"]

    validation = client.post(
        f"/api/analysis/{session_id}/validate",
        json={
            "file_id": original["file_id"],
            "group_name": original["group_name"],
            "layout": replaced["analysis"]["layout"],
            "workspace_id": workspace_id,
        },
    )
    assert validation.status_code == 200
    assert validation.json()["report"]["lesson_count"] > 0

    removed_response = client.delete(
        f"/api/analysis/{session_id}/files/{appended['file_id']}"
    )
    assert removed_response.status_code == 200
    assert removed_response.json()["can_restore"] is True
    manifest = app.state.context.sessions.load_manifest(session_id)
    assert all(item["file_id"] != appended["file_id"] for item in manifest["files"])

    restored_response = client.post(
        f"/api/analysis/{session_id}/files/{appended['file_id']}/restore"
    )
    assert restored_response.status_code == 200
    assert restored_response.json()["file_id"] == appended["file_id"]
    manifest = app.state.context.sessions.load_manifest(session_id)
    assert any(item["file_id"] == appended["file_id"] for item in manifest["files"])


def test_removing_placeholder_file_is_reversible(tmp_path: Path) -> None:
    schedule = tmp_path / "group-101.xlsx"
    build_layered_schedule(schedule)
    app = create_app(tmp_path)
    client = TestClient(app)
    analyzed = analyze(client, schedule)
    session_id = analyzed["session_id"]

    unsupported = tmp_path / "legacy.xls"
    unsupported.write_bytes(b"legacy-placeholder")
    with unsupported.open("rb") as source:
        appended_response = client.post(
            f"/api/analysis/{session_id}/files",
            files={"files": (unsupported.name, source, "application/vnd.ms-excel")},
        )
    assert appended_response.status_code == 200
    placeholder = appended_response.json()["files"][0]
    assert placeholder["analysis"] is None

    assert client.delete(
        f"/api/analysis/{session_id}/files/{placeholder['file_id']}"
    ).status_code == 200
    restored = client.post(
        f"/api/analysis/{session_id}/files/{placeholder['file_id']}/restore"
    )
    assert restored.status_code == 200
    assert restored.json()["analysis"] is None
    assert restored.json()["status"] == "error"
