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


def test_multiple_teacher_overrides_registers_candidates_and_splits(tmp_path: Path) -> None:
    service = resolver(tmp_path)
    applied = service.set_teacher_overrides({
        "Математика": "Иванов И.И., Петров П.П.",
    })
    key = service._subject_key("Математика")
    assert applied[key] == "Иванов И.И., Петров П.П."
    catalog_entry = service.teacher_candidate_catalog[key]
    assert "Иванов И.И." in catalog_entry["lecturer"]
    assert "Петров П.П." in catalog_entry["lecturer"]
    assert "Иванов И.И." in catalog_entry["other"]
    assert "Петров П.П." in catalog_entry["other"]


def test_role_preferences_with_multiple_teachers(tmp_path: Path) -> None:
    service = resolver(tmp_path)
    applied = service.set_teacher_overrides({
        "@lecturer|Математика": "Иванов И.И., Петров П.П.",
    })
    assert applied == {}
    pref_entry = service.teacher_assignment_preferences[service._subject_key("Математика")]
    assert pref_entry["lecturer"] == ["Иванов И.И.", "Петров П.П."]


def test_manual_multiple_teachers_round_robin_avoids_occupied(tmp_path: Path) -> None:
    service = resolver(tmp_path)
    service.set_teacher_overrides({
        "Математика": "Иванов И.И., Петров П.П.",
    })

    # Group 1 gets Иванов И.И.
    first = service._assign_teacher(1, "Понедельник", 1, "Математика", "П", [])
    assert first == "Иванов И.И."

    # Group 2 at same slot gets Петров П.П. avoiding occupied Иванов И.И.
    second = service._assign_teacher(1, "Понедельник", 1, "Математика", "П", [])
    assert second == "Петров П.П."
    assert not any("уже занят" in w for w in service.warnings)


def test_occupancy_reuse_only_for_lectures_not_practice(tmp_path: Path) -> None:
    service = resolver(tmp_path)
    # Stream lectures share occupied teacher
    lec1 = service._assign_teacher(1, "Понедельник", 1, "Физика", "Л", ["Иванов И.И.", "Петров П.П."])
    lec2 = service._assign_teacher(1, "Понедельник", 1, "Физика", "Л", ["Иванов И.И.", "Петров П.П."])
    assert lec1 == "Иванов И.И."
    assert lec2 == "Иванов И.И."

    # Practice does NOT share occupied teacher for parallel groups
    prac1 = service._assign_teacher(1, "Вторник", 1, "Физика", "П", ["Иванов И.И.", "Петров П.П."])
    prac2 = service._assign_teacher(1, "Вторник", 1, "Физика", "П", ["Иванов И.И.", "Петров П.П."])
    assert prac1 == "Иванов И.И."
    assert prac2 == "Петров П.П."
