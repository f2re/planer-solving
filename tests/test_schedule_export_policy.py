from types import SimpleNamespace

from web.backend.schedule_export_policy import install_schedule_export_policy
from web.backend import workspace_schedule


def _lesson(
    *,
    day: str,
    subject: str,
    teacher: str,
) -> SimpleNamespace:
    return SimpleNamespace(
        week=1,
        day_of_week=day,
        pair_num=1,
        subject=subject,
        lesson_type_code="Л",
        room="101",
        teacher=teacher,
        group="101",
    )


def test_unassigned_lessons_remain_in_diagnostics_but_not_export_input() -> None:
    install_schedule_export_policy()
    lessons = [
        _lesson(day="Пн", subject="Своя дисциплина", teacher="Иванов И.И."),
        _lesson(day="Вт", subject="Чужая дисциплина", teacher=""),
    ]
    teachers = [{
        "id": 1,
        "short_name": "Иванов И.И.",
        "full_name": "Иванов Иван Иванович",
    }]

    report = workspace_schedule.resolve_teacher_collisions(
        lessons,
        teachers,
        candidate_catalog={},
        manual_overrides={},
    )

    assert len(lessons) == 1
    assert lessons[0].subject == "Своя дисциплина"
    assert lessons[0].teacher == "Иванов И.И."
    assert report["source_lesson_count"] == 2
    assert report["lesson_count"] == 1
    assert report["exported_lesson_count"] == 1
    assert report["excluded_unassigned_lesson_count"] == 1
    assert report["export_policy"] == "confirmed-teachers-only-v1"

    issue = next(
        item
        for item in report["issues"]
        if item["code"] == "teacher_conflicts_unresolved"
    )
    assert "исключено занятий: 1" in issue["message"]
    assert "только в диагностике" in issue["default_decision"]
    assert "не создают раздел «Не назначен»" in issue["impact"]
    assert "помещены в раздел «Не назначен»" not in issue["default_decision"]


def test_schedule_export_policy_installation_is_idempotent() -> None:
    install_schedule_export_policy()
    first = workspace_schedule.resolve_teacher_collisions
    install_schedule_export_policy()
    assert workspace_schedule.resolve_teacher_collisions is first
