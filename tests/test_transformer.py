from src.data_loader import Lesson
from src.transformer import transform_to_teacher_grid


def test_transform_to_teacher_grid_uses_configured_calendar() -> None:
    teachers = [{"short_name": "Иванов И.И.", "full_name": "Иванов Иван Иванович"}]
    lessons = [
        Lesson("522", "MET", "Л/Т.01", "101", 1, "Пн", 1, "Иванов И.И.", 0, "Unknown"),
        Lesson("523", "MET", "Л/Т.01", "101", 1, "Пн", 1, "Иванов И.И.", 0, "Unknown"),
        Lesson("522", "PHYS", "П/Т.02", "102", 1, "Вт", 2, "Unknown", 0, "Unknown"),
    ]

    result = transform_to_teacher_grid(
        lessons,
        teachers,
        start_date_str="2026-02-10",
        end_date_str="2026-02-14",
    )

    assert result["dates"] == [
        ("Февраль", 9, 1),
        ("Февраль", 10, 1),
        ("Февраль", 11, 1),
        ("Февраль", 12, 1),
        ("Февраль", 13, 1),
        ("Февраль", 14, 1),
    ]
    key = ("Иванов И.И.", 1, "Февраль", 9)
    assert result["grid"][key]["groups"] == ["522", "523"]
    assert result["grid"][key]["subject"] == "MET"
    assert not any(key[0] == "Unknown" for key in result["grid"])


def test_lesson_outside_configured_week_range_is_ignored() -> None:
    lesson = Lesson("522", "MET", "Л", "101", 5, "Пн", 1, "Иванов", 0, "Unknown")
    result = transform_to_teacher_grid(
        [lesson],
        [{"short_name": "Иванов"}],
        start_date_str="2026-02-10",
        end_date_str="2026-02-14",
    )
    assert result["grid"] == {}
