import json
from pathlib import Path

import pytest

from src.sqlite_workspace_store import SQLiteWorkspaceStore
from src.workspace_domain import WorkspaceError


def store(tmp_path: Path) -> SQLiteWorkspaceStore:
    legacy = tmp_path / "teachers.json"
    legacy.write_text(json.dumps([{
        "id": 1,
        "short_name": "Иванов И.И.",
        "full_name": "Иванов Иван Иванович",
        "position": "Доцент",
        "rank": "",
        "academic_degree": "к.т.н.",
    }], ensure_ascii=False), encoding="utf-8")
    return SQLiteWorkspaceStore(
        tmp_path / "data" / "planner-solving.sqlite3",
        tmp_path / "data" / "workspaces.json",
        legacy,
    )


def test_migrates_legacy_teachers_and_scopes_data(tmp_path: Path) -> None:
    storage = store(tmp_path)
    spaces = storage.list_workspaces()
    assert len(spaces) == 1
    default_id = spaces[0]["id"]
    assert storage.list_teachers(default_id)[0]["short_name"] == "Иванов И.И."

    second = storage.create_workspace({"name": "Вторая кафедра", "color": "#16A085"})
    storage.create_teacher(second["id"], {
        "short_name": "Петров П.П.",
        "full_name": "Петров Петр Петрович",
    })
    assert [item["short_name"] for item in storage.list_teachers(default_id)] == ["Иванов И.И."]
    assert [item["short_name"] for item in storage.list_teachers(second["id"])] == ["Петров П.П."]


def test_workspace_export_import_and_templates(tmp_path: Path) -> None:
    storage = store(tmp_path)
    original = storage.list_workspaces()[0]
    template = storage.create_template(original["id"], {
        "name": "Форма 2026",
        "description": "Основной формат",
        "layout": {"weeks_row": 7, "first_week_col": 5},
    })
    storage.update_template(original["id"], template["id"], {"description": "Исправлено"})
    package = storage.export_workspace(original["id"])
    imported = storage.import_workspace(package)
    assert imported["name"].startswith("Основное пространство")
    imported_templates = storage.list_templates(imported["id"])
    assert imported_templates[0]["description"] == "Исправлено"
    assert imported_templates[0]["id"] != template["id"]


def test_teacher_import_deduplicates_and_replace_mode(tmp_path: Path) -> None:
    storage = store(tmp_path)
    workspace_id = storage.list_workspaces()[0]["id"]
    result = storage.import_teachers(workspace_id, [
        {"short_name": "Иванов И.И.", "full_name": "Иванов Иван Иванович"},
        {"short_name": "Сидоров С.С.", "full_name": "Сидоров Сидор Сидорович"},
    ])
    assert result == {"added": 1, "skipped": 1, "total": 2}

    replaced = storage.import_teachers(workspace_id, [
        {"short_name": "Новый Н.Н.", "full_name": "Новый Николай Николаевич"},
    ], mode="replace")
    assert replaced == {"added": 1, "skipped": 0, "total": 1}


def test_cannot_delete_last_workspace(tmp_path: Path) -> None:
    storage = store(tmp_path)
    workspace_id = storage.list_workspaces()[0]["id"]
    with pytest.raises(WorkspaceError):
        storage.delete_workspace(workspace_id)
