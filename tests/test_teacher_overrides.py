import json
from pathlib import Path

from src.teacher_resolver import TeacherResolver


def resolver(tmp_path: Path) -> TeacherResolver:
    teachers = [
        {
            "id": 1,
            "short_name": "Иванов И.И.",
            "full_name": "Иванов Иван Иванович",
            "position": "доцент",
        },
        {
            "id": 2,
            "short_name": "Петров П.П.",
            "full_name": "Петров Пётр Петрович",
            "position": "профессор",
        },
    ]
    path = tmp_path / "teachers.json"
    path.write_text(json.dumps(teachers, ensure_ascii=False), encoding="utf-8")
    return TeacherResolver(str(path))


def test_manual_subject_assignment_has_priority(tmp_path: Path) -> None:
    service = resolver(tmp_path)

    applied = service.set_teacher_overrides({
        "Высшая математика": "Иванов Иван Иванович",
    })

    assert applied == {service._subject_key("Высшая математика"): "Иванов И.И."}
    assert service._assign_teacher(
        week=1,
        day="Понедельник",
        pair=1,
        subject="Высшая математика",
        lesson_type="Л",
        candidates=[],
    ) == "Иванов И.И."


def test_unknown_teacher_override_is_ignored_safely(tmp_path: Path) -> None:
    service = resolver(tmp_path)

    applied = service.set_teacher_overrides({
        "Физика": "Несуществующий Н.Н.",
    })

    assert applied == {}
    assert service._assign_teacher(
        week=1,
        day="Понедельник",
        pair=2,
        subject="Физика",
        lesson_type="Л",
        candidates=[],
    ) == "Unknown"
    assert any("не найден в пространстве" in message for message in service.warnings)


def test_manual_assignment_keeps_conflict_visible_without_rejection(tmp_path: Path) -> None:
    service = resolver(tmp_path)
    service.set_teacher_overrides({
        "Математика": "Иванов И.И.",
        "Физика": "Иванов И.И.",
    })

    first = service._assign_teacher(1, "Понедельник", 1, "Математика", "Л", [])
    second = service._assign_teacher(1, "Понедельник", 1, "Физика", "Л", [])

    assert first == "Иванов И.И."
    assert second == "Иванов И.И."
    assert any("Ручное назначение" in message and "уже занят" in message for message in service.warnings)
