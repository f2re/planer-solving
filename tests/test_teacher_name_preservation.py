"""Tests for teacher name preservation and resilient 'е' vs 'ё' matching."""
import json
from pathlib import Path
from types import SimpleNamespace
import openpyxl
import pytest

from src.data_loader import Lesson
from src.exporter import export_to_excel, _get_grid_item, _teacher_sheet_title
from src.teacher_assignment import resolve_teacher_collisions
from src.teacher_resolver import (
    TeacherLookup,
    TeacherResolver,
    format_teacher_initials,
)
from src.transformer import transform_to_teacher_grid
from src.weekly_exporter import _get_grid_lessons


def test_format_teacher_initials_preserves_yo():
    # Capitalized / lowercase with 'ё'
    assert format_teacher_initials("Королёв Иван Иванович") == "Королёв И.И."
    assert format_teacher_initials("королёв иван иванович") == "Королёв И.И."
    assert format_teacher_initials("Королёв И.И.") == "Королёв И.И."
    assert format_teacher_initials("королёв и.и.") == "Королёв И.И."
    assert format_teacher_initials("И.И. Королёв") == "Королёв И.И."
    assert format_teacher_initials("Королёв") == "Королёв"
    assert format_teacher_initials("Фёдоров Фёдор Фёдорович") == "Фёдоров Ф.Ф."
    assert format_teacher_initials("Селезнёва А.Б.") == "Селезнёва А.Б."
    # Hyphenated names
    assert format_teacher_initials("Мамин-Сибиряк Д.Н.") == "Мамин-Сибиряк Д.Н."
    assert format_teacher_initials("мамин-сибиряк д.н.") == "Мамин-Сибиряк Д.Н."
    # Plain names without 'ё' still work
    assert format_teacher_initials("Иванов Иван Иванович") == "Иванов И.И."


def test_teacher_lookup_preserves_database_spelling():
    teachers = [
        {"id": 1, "short_name": "Королёв И.И.", "full_name": "Королёв Иван Иванович"},
        {"id": 2, "short_name": "Фёдоров Ф.Ф.", "full_name": "Фёдоров Фёдор Фёдорович"},
    ]
    lookup = TeacherLookup(teachers)

    # Exact spelling with 'ё'
    assert lookup.get("Королёв И.И.") == "Королёв И.И."
    assert lookup.get("королёв и.и.") == "Королёв И.И."
    assert lookup.get("Королёв Иван Иванович") == "Королёв И.И."

    # Normalized / 'е' variant resolves to canonical DB spelling with 'ё'
    assert lookup.get("Королев И.И.") == "Королёв И.И."
    assert lookup.get("королев и.и.") == "Королёв И.И."
    assert lookup.get("Королев Иван Иванович") == "Королёв И.И."
    assert lookup.get("Королев") == "Королёв И.И."
    assert lookup.get("Королёв") == "Королёв И.И."
    assert lookup.get("И.И. Королев") == "Королёв И.И."
    assert lookup.get("И.И. Королёв") == "Королёв И.И."

    # Multiple teachers resolution
    assert lookup.resolve_all("Королев И.И., Федоров Ф.Ф.") == ["Королёв И.И.", "Фёдоров Ф.Ф."]
    assert lookup.resolve_all(["Королев И.И.", "Фёдоров Ф.Ф."]) == ["Королёв И.И.", "Фёдоров Ф.Ф."]


def test_teacher_resolver_preserves_database_spelling(tmp_path: Path):
    teachers_file = tmp_path / "teachers.json"
    teachers_file.write_text(
        json.dumps([
            {"short_name": "Королёв И.И.", "full_name": "Королёв Иван Иванович"},
            {"short_name": "Фёдоров Ф.Ф.", "full_name": "Фёдоров Фёдор Фёдорович"},
        ], ensure_ascii=False),
        encoding="utf-8",
    )
    resolver = TeacherResolver(str(teachers_file))

    assert resolver._resolve_teacher_alias("Королев И.И.") == "Королёв И.И."
    assert resolver._resolve_teacher_alias("Королёв И.И.") == "Королёв И.И."
    assert resolver._resolve_teacher_alias("Королев") == "Королёв И.И."
    assert resolver._resolve_teacher_alias("Королёв") == "Королёв И.И."
    assert resolver._resolve_teacher_alias("И.И. Королев") == "Королёв И.И."
    assert resolver._resolve_teacher_alias("И.И. Королёв") == "Королёв И.И."

    extracted = resolver._extract_teachers("Лекция Королев И.И. и Федоров Ф.Ф.")
    assert extracted == ["Королёв И.И.", "Фёдоров Ф.Ф."]


def test_teacher_assignment_preserves_database_spelling():
    teachers = [
        {"id": 1, "short_name": "Королёв И.И.", "full_name": "Королёв Иван Иванович"},
    ]
    # Lesson entered with 'е'
    lesson = SimpleNamespace(
        subject="Физика",
        teacher="Королев И.И.",
        week=1,
        day_of_week="Пн",
        pair_num=1,
        lesson_type_code="Л",
        room="101",
        group="Г-1",
    )
    result = resolve_teacher_collisions(
        [lesson],
        teachers,
        candidate_catalog={"Физика": {"lecturer": ["Королев И.И."]}},
    )
    # The assigned teacher in unit and lesson should be the canonical "Королёв И.И."
    assert lesson.teacher == "Королёв И.И."


def test_transformer_and_exporter_resilient_yo_matching(tmp_path: Path):
    teachers = [
        {"id": 1, "short_name": "Королёв И.И.", "full_name": "Королёв Иван Иванович"},
    ]
    lesson = Lesson(
        group="101",
        subject="Математика",
        lesson_type_code="Л",
        room="202",
        week=1,
        day_of_week="Пн",
        pair_num=1,
        teacher="Королев И.И.",  # written with 'е'
        date_day=9,
        month="Февраль",
    )
    grid_data = transform_to_teacher_grid(
        [lesson],
        teachers,
        start_date_str="2026-02-09",
        end_date_str="2026-02-15",
    )
    # Grid should be keyed with canonical DB spelling
    assert any(key[0] == "Королёв И.И." for key in grid_data["grid"])

    # Sheet title helper
    assert _teacher_sheet_title(teachers[0]) == "Королёв И.И."

    # Export to excel
    out_file = tmp_path / "schedule.xlsx"
    export_result = export_to_excel(grid_data, teachers, str(out_file))
    assert export_result["mode"] == "normal"

    wb = openpyxl.load_workbook(out_file)
    assert "Королёв И.И." in wb.sheetnames
    sheet = wb["Королёв И.И."]
    # Lesson was placed in grid
    found_subject = False
    for row in sheet.iter_rows(values_only=True):
        for cell_val in row:
            if cell_val and "Математика" in str(cell_val):
                found_subject = True
                break
    assert found_subject, "Lesson should be present in exported teacher sheet"


def test_weekly_exporter_resilient_yo_matching(tmp_path: Path):
    teachers = [
        {"id": 1, "short_name": "Королёв И.И.", "full_name": "Королёв Иван Иванович"},
    ]
    lesson = Lesson(
        group="101",
        subject="Математика",
        lesson_type_code="Л",
        room="202",
        week=1,
        day_of_week="Пн",
        pair_num=1,
        teacher="Королев И.И.",  # written with 'е'
        date_day=9,
        month="Февраль",
    )
    # Test _get_grid_lessons directly
    grid = {(1, "Королев И.И.", 0, 1): [lesson]}
    res = _get_grid_lessons(grid, 1, "Королёв И.И.", 0, 1)
    assert res == [lesson]

    grid_yo = {(1, "Королёв И.И.", 0, 1): [lesson]}
    res2 = _get_grid_lessons(grid_yo, 1, "Королев И.И.", 0, 1)
    assert res2 == [lesson]
