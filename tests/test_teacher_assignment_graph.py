import json
from types import SimpleNamespace

from src.teacher_assignment import UNASSIGNED_TEACHER, resolve_teacher_collisions
from src.teacher_resolver import TeacherResolver


TEACHERS = [
    {"id": 1, "short_name": "Иванов И.И.", "full_name": "Иванов Иван Иванович"},
    {"id": 2, "short_name": "Иванов П.П.", "full_name": "Иванов Пётр Петрович"},
    {"id": 3, "short_name": "Петров П.П.", "full_name": "Петров Пётр Петрович"},
    {"id": 4, "short_name": "Сидоров С.С.", "full_name": "Сидоров Сергей Сергеевич"},
]


def lesson(
    subject: str,
    *,
    teacher: str = "",
    week: int = 1,
    day: str = "Понедельник",
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


def test_namesakes_are_resolved_by_surname_and_initials(tmp_path) -> None:
    path = tmp_path / "teachers.json"
    path.write_text(json.dumps(TEACHERS, ensure_ascii=False), encoding="utf-8")
    resolver = TeacherResolver(str(path))

    assert resolver._extract_teachers("Иванов И.И.") == ["Иванов И.И."]
    assert resolver._extract_teachers("И.И. Иванов") == ["Иванов И.И."]
    assert resolver._extract_teachers("Иванов П.П.") == ["Иванов П.П."]
    assert resolver._extract_teachers("Иванов") == []
    assert any("неоднозначен" in warning for warning in resolver.warnings)


def test_conflicting_discipline_moves_to_free_subject_teacher() -> None:
    lessons = [
        lesson("Дисциплина А", teacher="Иванов И.И.", room="101", group="А-1"),
        lesson("Дисциплина Б", teacher="Иванов И.И.", room="202", group="Б-1"),
    ]
    catalog = {
        "дисциплинаа": {
            "lecturer": [],
            "other": ["Иванов И.И."],
            "all": ["Иванов И.И."],
        },
        "дисциплинаб": {
            "lecturer": [],
            "other": ["Иванов И.И.", "Петров П.П."],
            "all": ["Иванов И.И.", "Петров П.П."],
        },
    }

    report = resolve_teacher_collisions(lessons, TEACHERS, candidate_catalog=catalog)

    assert lessons[0].teacher == "Иванов И.И."
    assert lessons[1].teacher == "Петров П.П."
    assert report["resolved_conflict_count"] == 1
    assert report["unresolved_conflict_count"] == 0


def test_lecturer_keeps_lecture_and_practice_moves_to_practice_teacher() -> None:
    lessons = [
        lesson(
            "Математика",
            teacher="Иванов И.И.",
            lesson_type="Л",
            room="Актовый зал",
            group="М-1",
        ),
        lesson(
            "Математика",
            teacher="Иванов И.И.",
            lesson_type="П",
            room="204",
            group="М-2",
        ),
    ]
    catalog = {
        "математика": {
            "lecturer": ["Иванов И.И."],
            "other": ["Петров П.П.", "Сидоров С.С."],
            "all": ["Иванов И.И.", "Петров П.П.", "Сидоров С.С."],
        }
    }

    report = resolve_teacher_collisions(lessons, TEACHERS, candidate_catalog=catalog)

    assert lessons[0].teacher == "Иванов И.И."
    assert lessons[1].teacher in {"Петров П.П.", "Сидоров С.С."}
    assert lessons[1].teacher != lessons[0].teacher
    assert report["unresolved_conflict_count"] == 0


def test_load_is_balanced_between_equivalent_teachers() -> None:
    lessons = [
        lesson(
            "Физика",
            week=index + 1,
            teacher="",
            room=str(100 + index),
            group=f"Ф-{index + 1}",
        )
        for index in range(8)
    ]
    catalog = {
        "физика": {
            "lecturer": [],
            "other": ["Петров П.П.", "Сидоров С.С."],
            "all": ["Петров П.П.", "Сидоров С.С."],
        }
    }

    report = resolve_teacher_collisions(lessons, TEACHERS, candidate_catalog=catalog)

    assert set(report["load_by_teacher"]) == {"Петров П.П.", "Сидоров С.С."}
    assert report["load_spread"] <= 1


def test_impossible_collision_is_not_hidden_as_double_booking() -> None:
    lessons = [
        lesson("Химия", teacher="Иванов И.И.", room="301", group="Х-1"),
        lesson("Биология", teacher="Иванов И.И.", room="302", group="Б-1"),
    ]
    catalog = {
        "химия": {
            "lecturer": [],
            "other": ["Иванов И.И."],
            "all": ["Иванов И.И."],
        },
        "биология": {
            "lecturer": [],
            "other": ["Иванов И.И."],
            "all": ["Иванов И.И."],
        },
    }

    report = resolve_teacher_collisions(lessons, TEACHERS, candidate_catalog=catalog)

    assert sorted(item.teacher for item in lessons) == sorted(
        ["Иванов И.И.", UNASSIGNED_TEACHER]
    )
    assert report["unresolved_conflict_count"] == 1
    assert any(issue["code"] == "teacher_conflicts_unresolved" for issue in report["issues"])
