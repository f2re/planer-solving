from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sqlite3

import pytest

from src.sqlite_workspace_store import SQLITE_SCHEMA_VERSION, SQLiteWorkspaceStore
from src.workspace_store import WorkspaceError


def legacy_document() -> dict:
    return {
        "version": 1,
        "default_workspace_id": "space-1",
        "workspaces": [
            {
                "id": "space-1",
                "name": "Кафедра",
                "color": "#315EFB",
                "description": "Проверка переноса",
                "created_at": "2026-08-01T00:00:00+00:00",
                "updated_at": "2026-08-01T00:00:00+00:00",
                "settings": {
                    "schedule_start_date": "2026-09-01",
                    "schedule_end_date": "2027-01-31",
                },
                "teachers": [
                    {
                        "id": 1,
                        "short_name": "Иванов И.И.",
                        "full_name": "Иванов Иван Иванович",
                        "position": "доцент",
                        "rank": "",
                        "academic_degree": "",
                    }
                ],
                "templates": [
                    {
                        "id": "template-1",
                        "name": "Форма 2026",
                        "description": "",
                        "layout": {"sheet_name": "Лист1", "weeks_row": 4},
                        "created_at": "2026-08-01T00:00:00+00:00",
                        "updated_at": "2026-08-01T00:00:00+00:00",
                    }
                ],
            }
        ],
    }


def test_sqlite_store_imports_json_once_and_keeps_compatibility_mirror(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    workspaces_json = data / "workspaces.json"
    teachers_json = tmp_path / "teachers.json"
    workspaces_json.write_text(json.dumps(legacy_document(), ensure_ascii=False), encoding="utf-8")
    teachers_json.write_text("[]", encoding="utf-8")

    store = SQLiteWorkspaceStore(
        data / "planner-solving.sqlite3",
        workspaces_json,
        teachers_json,
    )
    workspace = store.get_workspace("space-1")

    assert workspace["name"] == "Кафедра"
    assert workspace["teachers"][0]["short_name"] == "Иванов И.И."
    assert workspace["templates"][0]["name"] == "Форма 2026"
    assert store.schema_version() == SQLITE_SCHEMA_VERSION

    store.create_teacher(
        "space-1",
        {"short_name": "Петров П.П.", "full_name": "Петров Пётр Петрович"},
    )
    mirrored = json.loads(workspaces_json.read_text(encoding="utf-8"))
    assert len(mirrored["workspaces"][0]["teachers"]) == 2
    assert len(json.loads(teachers_json.read_text(encoding="utf-8"))) == 2

    reopened = SQLiteWorkspaceStore(
        data / "planner-solving.sqlite3",
        workspaces_json,
        teachers_json,
    )
    assert len(reopened.list_teachers("space-1")) == 2


def test_sqlite_store_serializes_parallel_writes_without_lost_updates(tmp_path: Path):
    store = SQLiteWorkspaceStore(
        tmp_path / "data" / "planner-solving.sqlite3",
        tmp_path / "data" / "workspaces.json",
        tmp_path / "teachers.json",
    )
    workspace_id = store.default_workspace_id()

    def create(index: int) -> None:
        store.create_teacher(
            workspace_id,
            {
                "short_name": f"Преподаватель {index}",
                "full_name": f"Преподаватель Тестовый {index}",
            },
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(create, range(24)))

    teachers = store.list_teachers(workspace_id)
    assert len(teachers) == 24
    assert len({teacher["id"] for teacher in teachers}) == 24

    connection = sqlite3.connect(store.path)
    try:
        assert connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    finally:
        connection.close()


def test_sqlite_store_enforces_unique_entities_and_semester_dates(tmp_path: Path):
    store = SQLiteWorkspaceStore(
        tmp_path / "data" / "planner-solving.sqlite3",
        tmp_path / "data" / "workspaces.json",
        tmp_path / "teachers.json",
    )
    workspace_id = store.default_workspace_id()
    teacher = {"short_name": "Иванов И.И.", "full_name": "Иванов Иван Иванович"}
    store.create_teacher(workspace_id, teacher)

    with pytest.raises(WorkspaceError):
        store.create_teacher(workspace_id, teacher)

    with pytest.raises(WorkspaceError):
        store.update_workspace(
            workspace_id,
            {
                "settings": {
                    "schedule_start_date": "2027-02-01",
                    "schedule_end_date": "2026-09-01",
                }
            },
        )
