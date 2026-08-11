from pathlib import Path

import pytest
from pydantic import ValidationError

from src.data_migrations import migrate_document
from src.sqlite_workspace_store import SQLiteWorkspaceStore
from web.backend.schemas import GenerateScheduleRequest, ValidateLayoutRequest


ROOT = Path(__file__).parents[1]


def _settings() -> dict:
    return {
        "schedule_start_date": "2026-09-01",
        "schedule_end_date": "2027-01-31",
    }


def test_legacy_global_records_are_owned_only_by_main_workspace():
    payload = {
        "version": 1,
        "workspaces": [
            {
                "id": "other",
                "name": "Новая кафедра",
                "teachers": [],
                "templates": [],
                "settings": _settings(),
            },
            {
                "id": "main",
                "name": "Основное пространство",
                "teachers": [],
                "templates": [],
                "settings": _settings(),
            },
        ],
        "teachers": [
            {"short_name": "Иванов И.И.", "full_name": "Иванов Иван Иванович"}
        ],
        "templates": [
            {"name": "Старый шаблон", "layout": {"sheet_name": "Лист1", "weeks_row": 3}}
        ],
    }

    migrated, applied = migrate_document(payload)

    spaces = {item["id"]: item for item in migrated["workspaces"]}
    assert migrated["default_workspace_id"] == "main"
    assert [item["short_name"] for item in spaces["main"]["teachers"]] == ["Иванов И.И."]
    assert [item["name"] for item in spaces["main"]["templates"]] == ["Старый шаблон"]
    assert spaces["other"]["teachers"] == []
    assert spaces["other"]["templates"] == []
    assert "teachers" not in migrated
    assert "templates" not in migrated
    assert "legacy->main-workspace" in applied

    repeated, second_applied = migrate_document(migrated)
    assert repeated == migrated
    assert "legacy->main-workspace" not in second_applied


def test_schema_one_compatibility_teacher_mirror_is_not_reimported_into_main():
    payload = {
        "version": 1,
        "default_workspace_id": "other",
        "workspaces": [
            {
                "id": "main",
                "name": "Основное пространство",
                "teachers": [],
                "templates": [],
                "settings": _settings(),
            },
            {
                "id": "other",
                "name": "Другое пространство",
                "teachers": [{
                    "id": 1,
                    "short_name": "Петров П.П.",
                    "full_name": "Петров Пётр Петрович",
                }],
                "templates": [],
                "settings": _settings(),
            },
        ],
    }
    compatibility_mirror = [{
        "id": 1,
        "short_name": "Петров П.П.",
        "full_name": "Петров Пётр Петрович",
    }]

    migrated, _ = migrate_document(payload, legacy_teachers=compatibility_mirror)
    spaces = {item["id"]: item for item in migrated["workspaces"]}

    assert migrated["default_workspace_id"] == "other"
    assert spaces["main"]["teachers"] == []
    assert [item["short_name"] for item in spaces["other"]["teachers"]] == ["Петров П.П."]


def test_sqlite_workspace_reads_never_fall_back_to_other_workspace(tmp_path: Path):
    store = SQLiteWorkspaceStore(
        tmp_path / "data" / "planner-solving.sqlite3",
        tmp_path / "data" / "workspaces.json",
        tmp_path / "teachers.json",
    )
    main_id = store.default_workspace_id()
    other = store.create_workspace({"name": "Изолированное пространство"})

    store.create_teacher(
        main_id,
        {"short_name": "Петров П.П.", "full_name": "Петров Пётр Петрович"},
    )
    store.create_template(
        main_id,
        {"name": "Только основное", "layout": {"sheet_name": "Лист1", "weeks_row": 4}},
    )

    assert len(store.list_teachers(main_id)) == 1
    assert len(store.list_templates(main_id)) == 1
    assert store.list_teachers(other["id"]) == []
    assert store.list_templates(other["id"]) == []


def test_schedule_requests_require_explicit_workspace_id():
    with pytest.raises(ValidationError):
        ValidateLayoutRequest(file_id="f", group_name="g", layout={})
    with pytest.raises(ValidationError):
        GenerateScheduleRequest(files=[])


def test_browser_legacy_templates_target_and_repair_main_workspace_only():
    source = (ROOT / "web" / "frontend" / "assets" / "planner-app.js").read_text(encoding="utf-8")
    start = source.index("const migrateLocalTemplates")
    end = source.index("const submitAuth", start)
    migration = source[start:end]

    assert "основное пространство" in migration
    assert "main-workspace-v2" in migration
    assert "legacyWorkspace.id}/templates" in migration
    assert "workspace.activeWorkspaceId.value}/templates" not in migration
    assert "oldDescription" in migration
    assert "axios.delete(`/api/workspaces/${space.id}/templates/${item.id}`)" in migration
    assert "из других пространств удалено автоматических копий" in migration


def test_start_hero_is_reapplied_after_vue_mount_and_future_rerenders():
    source = (ROOT / "web" / "frontend" / "assets" / "brand-refresh.js").read_text(encoding="utf-8")
    assert "decorateStartCard" in source
    assert "decorateVisibleScreens" in source
    assert "queueMicrotask(() => decorateVisibleScreens(root))" in source
    assert "observeBrandScreens" in source
    assert "MutationObserver" in source
    assert "hero-schedule.png" in source
    assert ".webp" not in source
