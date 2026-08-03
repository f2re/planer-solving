from pathlib import Path

from src.platform_store import PLATFORM_SCHEMA_VERSION, PlatformStore


def make_store(tmp_path: Path) -> PlatformStore:
    return PlatformStore(
        tmp_path / "data" / "planner-solving.sqlite3",
        tmp_path / "data" / "workspaces.json",
        tmp_path / "teachers.json",
    )


def test_template_revisions_composite_rules_and_restore(tmp_path: Path):
    store = make_store(tmp_path)
    workspace_id = store.default_workspace_id()
    template = store.create_template(
        workspace_id,
        {
            "name": "Составной формат",
            "description": "Два вида листов",
            "layout": {"sheet_name": "Основной", "weeks_row": 7},
            "composite": [{
                "name": "Заочное",
                "sheet_pattern": "заоч",
                "layout": {"sheet_name": "Заочное", "weeks_row": 11},
            }],
            "fingerprint": {"features": {"sheet_count": 2, "week_step": 1}},
            "comment": "Первая версия",
        },
    )
    assert template["current_revision"] == 1
    assert template["composite"][0]["sheet_pattern"] == "заоч"

    updated = store.update_template(
        workspace_id,
        template["id"],
        {
            "layout": {"sheet_name": "Основной", "weeks_row": 9},
            "composite": template["composite"],
            "comment": "Смещена строка недель",
        },
    )
    assert updated["current_revision"] == 2
    revisions = store.list_template_revisions(workspace_id, template["id"])
    assert [item["revision_no"] for item in revisions] == [2, 1]
    assert revisions[0]["changes"][0]["field"] == "weeks_row"

    restored = store.restore_template_revision(workspace_id, template["id"], 1)
    assert restored["layout"]["weeks_row"] == 7
    assert restored["current_revision"] == 3
    assert store.schema_version() == PLATFORM_SCHEMA_VERSION


def test_processing_history_keeps_checksums_reports_and_artifacts(tmp_path: Path):
    store = make_store(tmp_path)
    workspace_id = store.default_workspace_id()
    source = tmp_path / "source.xlsx"
    source.write_bytes(b"source-workbook")
    artifact = tmp_path / "schedule.xlsx"
    artifact.write_bytes(b"generated-workbook")

    run_id = store.start_processing_run(
        workspace_id=workspace_id,
        session_id="session-1",
        actor=None,
        source_count=1,
    )
    store.record_processing_file(
        run_id,
        file_id="file-1",
        filename="source.xlsx",
        file_path=source,
        group_name="101",
        layout={"weeks_row": 7},
        report={"lesson_count": 12, "warnings": [], "errors": []},
        template_match={
            "template_id": "template-1",
            "revision_no": 2,
            "score": 98.5,
        },
    )
    result = store.finish_processing_run(
        run_id,
        status="success",
        lesson_count=12,
        warning_count=0,
        error_count=0,
        selected_templates=[{"template_id": "template-1", "revision_no": 2}],
        report={"status": "ok"},
        artifacts=[{"kind": "schedule", "path": artifact}],
        actor=None,
    )

    assert result["status"] == "success"
    assert result["files"][0]["checksum"]
    assert result["files"][0]["template_revision"] == 2
    assert result["artifacts"][0]["checksum"]
    assert store.list_processing_runs(workspace_id)[0]["artifact_count"] == 1
