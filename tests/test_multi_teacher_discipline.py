import json
from pathlib import Path
from types import SimpleNamespace
import pytest

from src.data_loader import Lesson
from src.teacher_assignment import UNASSIGNED_TEACHER, resolve_teacher_collisions
from src.teacher_assignment_rules import normalize_rule
from src.teacher_resolver import (
    TeacherLookup,
    TeacherResolver,
    format_teacher_initials,
)
from src.transformer import transform_to_teacher_grid


TEACHERS = [
    {"id": 1, "short_name": "Иванов И.И.", "full_name": "Иванов Иван Иванович"},
    {"id": 2, "short_name": "Петров П.П.", "full_name": "Петров Пётр Петрович"},
    {"id": 3, "short_name": "Сидоров С.С.", "full_name": "Сидоров Сергей Сергеевич"},
    {"id": 4, "short_name": "Иванов А.А.", "full_name": "Иванов Алексей Алексеевич"},
    {"id": 5, "short_name": "Иванов Б.Б.", "full_name": "Иванов Борис Борисович"},
]


def make_lesson(
    subject: str,
    *,
    teacher: str = "",
    week: int = 1,
    day: str = "Пн",
    pair: int = 1,
    lesson_type: str = "П",
    room: str = "101",
    group: str = "Г-1",
):
    return SimpleNamespace(
        subject=subject,
        teacher=teacher,
        week=week,
        day_of_week=day,
        pair_num=pair,
        lesson_type_code=lesson_type,
        room=room,
        group=group,
    )


def test_format_teacher_initials_multiple_teachers():
    assert (
        format_teacher_initials("Иванов Иван Иванович, Петров Петр Петрович")
        == "Иванов И.И., Петров П.П."
    )
    assert (
        format_teacher_initials("Иванов И.И., Петров П.П.")
        == "Иванов И.И., Петров П.П."
    )
    assert (
        format_teacher_initials("Иванов И.И. / Петров П.П.")
        == "Иванов И.И., Петров П.П."
    )
    assert (
        format_teacher_initials("Иванов И.И. и Петров П.П.")
        == "Иванов И.И., Петров П.П."
    )


def test_teacher_lookup_multiple_teachers():
    lookup = TeacherLookup(TEACHERS)
    assert lookup.get("Иванов И.И., Петров П.П.") == "Иванов И.И., Петров П.П."
    assert lookup.get("И.И. Иванов / П.П. Петров") == "Иванов И.И., Петров П.П."
    assert lookup.resolve_all("Иванов И.И., Петров П.П.") == ["Иванов И.И.", "Петров П.П."]
    assert lookup.resolve_all(["Иванов И.И.", "Петров П.П."]) == ["Иванов И.И.", "Петров П.П."]

    # When surnames are unique across teachers
    unique_lookup = TeacherLookup([
        {"id": 1, "short_name": "Иванов И.И.", "full_name": "Иванов Иван Иванович"},
        {"id": 2, "short_name": "Петров П.П.", "full_name": "Петров Пётр Петрович"},
    ])
    assert unique_lookup.get("Иванов, Петров") == "Иванов И.И., Петров П.П."


def test_namesakes_single_initials_are_not_falsely_ambiguous(tmp_path: Path):
    teachers_file = tmp_path / "teachers.json"
    teachers_file.write_text(json.dumps(TEACHERS, ensure_ascii=False), encoding="utf-8")
    resolver = TeacherResolver(str(teachers_file))

    extracted = resolver._extract_teachers("Иванов А., Иванов Б.")
    assert extracted == ["Иванов А.А.", "Иванов Б.Б."]

    # Order preserved
    extracted_rev = resolver._extract_teachers("Иванов Б., Иванов А.")
    assert extracted_rev == ["Иванов Б.Б.", "Иванов А.А."]


def test_normalize_rule_with_multiple_teachers():
    lookup = TeacherLookup(TEACHERS)
    rule = normalize_rule(
        {
            "subject": "Физика",
            "lecturer": "Иванов И.И., Петров П.П.",
            "practice": "Петров П.П., Сидоров С.С.",
            "reserve": "Иванов А.А.",
        },
        aliases=lookup,
    )
    assert rule["subject"] == "Физика"
    assert rule["lecturer"] == "Иванов И.И., Петров П.П."
    assert rule["practice"] == "Петров П.П., Сидоров С.С."
    assert rule["reserve"] == "Иванов А.А."


def test_set_teacher_overrides_multiple_teachers(tmp_path: Path):
    teachers_file = tmp_path / "teachers.json"
    teachers_file.write_text(json.dumps(TEACHERS, ensure_ascii=False), encoding="utf-8")
    resolver = TeacherResolver(str(teachers_file))

    applied = resolver.set_teacher_overrides({
        "@lecturer|Математика": "Иванов И.И., Петров П.П.",
        "@other|Математика": "Сидоров С.С., Иванов А.А.",
        "Физика": "Иванов И.И., Петров П.П.",
    })
    assert "математика" not in applied  # role preferences are in preferences, not direct subject map
    assert applied["физика"] == "Иванов И.И., Петров П.П."

    cat_math = resolver.teacher_candidate_catalog.get("математика", {})
    assert cat_math.get("lecturer") == ["Иванов И.И.", "Петров П.П."]
    assert cat_math.get("other") == ["Сидоров С.С.", "Иванов А.А."]

    cat_phys = resolver.teacher_candidate_catalog.get("физика", {})
    assert "Иванов И.И." in cat_phys.get("lecturer", [])
    assert "Петров П.П." in cat_phys.get("lecturer", [])


def test_even_distribution_between_multiple_assigned_teachers():
    # 10 lessons of Mathematics for group G-1 across 10 weeks
    lessons = [
        make_lesson(
            "Математика",
            teacher="Иванов И.И.",  # even if pre-assigned to one teacher by loader
            week=w,
            day="Пн",
            pair=1,
            lesson_type="П",
            room="101",
            group="G-1",
        )
        for w in range(1, 11)
    ]
    catalog = {
        "математика": {
            "lecturer": [],
            "other": ["Иванов И.И.", "Петров П.П."],
            "all": ["Иванов И.И.", "Петров П.П."],
        }
    }

    report = resolve_teacher_collisions(lessons, TEACHERS, candidate_catalog=catalog)

    assigned = [l.teacher for l in lessons]
    count_ivanov = assigned.count("Иванов И.И.")
    count_petrov = assigned.count("Петров П.П.")

    assert count_ivanov == 5
    assert count_petrov == 5
    assert report["load_spread"] == 0
    assert report["unresolved_conflict_count"] == 0


def test_even_distribution_with_three_teachers():
    lessons = [
        make_lesson(
            "Химия",
            week=w,
            day="Вт",
            pair=2,
            lesson_type="П",
            room="201",
            group="G-1",
        )
        for w in range(1, 11)
    ]
    catalog = {
        "химия": {
            "lecturer": [],
            "other": ["Иванов И.И.", "Петров П.П.", "Сидоров С.С."],
            "all": ["Иванов И.И.", "Петров П.П.", "Сидоров С.С."],
        }
    }

    report = resolve_teacher_collisions(lessons, TEACHERS, candidate_catalog=catalog)
    loads = report["load_by_teacher"]

    assert set(loads.keys()) == {"Иванов И.И.", "Петров П.П.", "Сидоров С.С."}
    assert report["load_spread"] <= 1
    assert sum(loads.values()) == 10


def test_collision_resolution_parallel_groups_same_slot():
    # Two groups have practice at the exact same slot in different rooms
    lessons = [
        make_lesson(
            "Информатика",
            week=1,
            day="Ср",
            pair=1,
            lesson_type="П",
            room="101",
            group="G-1",
        ),
        make_lesson(
            "Информатика",
            week=1,
            day="Ср",
            pair=1,
            lesson_type="П",
            room="102",
            group="G-2",
        ),
    ]
    catalog = {
        "информатика": {
            "lecturer": [],
            "other": ["Иванов И.И.", "Петров П.П."],
            "all": ["Иванов И.И.", "Петров П.П."],
        }
    }

    report = resolve_teacher_collisions(lessons, TEACHERS, candidate_catalog=catalog)

    assert lessons[0].teacher != UNASSIGNED_TEACHER
    assert lessons[1].teacher != UNASSIGNED_TEACHER
    assert lessons[0].teacher != lessons[1].teacher
    assert set([lessons[0].teacher, lessons[1].teacher]) == {"Иванов И.И.", "Петров П.П."}
    assert report["unresolved_conflict_count"] == 0


def test_collision_resolution_when_one_teacher_busy():
    # Ivanov is already busy teaching Physics in pair 1
    lessons = [
        make_lesson(
            "Физика",
            teacher="Иванов И.И.",
            week=1,
            day="Чт",
            pair=1,
            lesson_type="Л",
            room="Актовый зал",
            group="G-1",
        ),
        make_lesson(
            "Математика",
            week=1,
            day="Чт",
            pair=1,
            lesson_type="П",
            room="205",
            group="G-2",
        ),
    ]
    catalog = {
        "физика": {
            "lecturer": ["Иванов И.И."],
            "other": [],
            "all": ["Иванов И.И."],
        },
        "математика": {
            "lecturer": [],
            "other": ["Иванов И.И.", "Петров П.П."],
            "all": ["Иванов И.И.", "Петров П.П."],
        },
    }

    report = resolve_teacher_collisions(lessons, TEACHERS, candidate_catalog=catalog)

    assert lessons[0].teacher == "Иванов И.И."
    assert lessons[1].teacher == "Петров П.П."
    assert report["unresolved_conflict_count"] == 0


def test_export_grid_with_multi_teacher_discipline():
    lessons = [
        Lesson(
            group="G-1",
            subject="Алгебра",
            lesson_type_code="П",
            room="101",
            week=1,
            day_of_week="Пн",
            pair_num=1,
            teacher="Иванов И.И.",
            date_day=1,
            month="Февраль",
        ),
        Lesson(
            group="G-1",
            subject="Алгебра",
            lesson_type_code="П",
            room="101",
            week=2,
            day_of_week="Пн",
            pair_num=1,
            teacher="Петров П.П.",
            date_day=8,
            month="Февраль",
        ),
    ]
    grid_data = transform_to_teacher_grid(
        lessons,
        TEACHERS,
        start_date_str="2026-02-01",
        end_date_str="2026-06-30",
    )
    # Both teachers are represented
    assert "Иванов И.И." in grid_data["teachers"]
    assert "Петров П.П." in grid_data["teachers"]

    # Each teacher has their lesson in the grid
    ivanov_lessons = [k for k in grid_data["grid"] if k[0] == "Иванов И.И."]
    petrov_lessons = [k for k in grid_data["grid"] if k[0] == "Петров П.П."]
    assert len(ivanov_lessons) == 1
    assert len(petrov_lessons) == 1
