"""Export policy for lessons that do not belong to a confirmed teacher.

Unresolved rows remain in diagnostics and in the current edit session, but they
must not be emitted as a synthetic ``Не назначен`` teacher schedule.
"""
from __future__ import annotations

from functools import wraps
from typing import Any, Dict, Mapping, MutableSequence, Sequence

UNASSIGNED_MARKERS = {
    "",
    "unknown",
    "none",
    "не назначен",
    "не назначено",
    "не назначена",
    "не назначены",
    "не задан",
}


def _normalized_teacher(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().replace("ё", "е").split())


def _is_unassigned_lesson(lesson: Any) -> bool:
    return _normalized_teacher(getattr(lesson, "teacher", "")) in UNASSIGNED_MARKERS


def _rewrite_unassigned_issue(report: Dict[str, Any], excluded_count: int) -> None:
    issues = report.setdefault("issues", [])
    matching = [
        issue
        for issue in issues
        if issue.get("code") == "teacher_conflicts_unresolved"
    ]
    if not matching:
        matching.append({
            "code": "teacher_conflicts_unresolved",
            "scope": "teacher",
            "category": "conflict",
            "severity": "problem",
            "priority": 100,
            "actions": [],
            "action": {},
            "blocking": False,
            "source": "schedule_export_policy",
            "items": [],
        })
        issues.extend(matching)

    for issue in matching:
        issue.update({
            "message": (
                "Для части строк не подтверждён преподаватель. "
                f"Из итоговых файлов исключено занятий: {excluded_count}."
            ),
            "default_decision": (
                "Не включать такие строки в расписание преподавателей; "
                "оставить их только в диагностике для проверки оператором."
            ),
            "impact": (
                "Итоговые файлы содержат только занятия с подтверждённым "
                "преподавателем и не создают раздел «Не назначен»."
            ),
            "resolved": False,
            "resolution": "excluded_from_export",
        })


def install_schedule_export_policy() -> None:
    """Install the output filter once for every application process."""

    from web.backend import workspace_schedule

    if getattr(workspace_schedule, "_schedule_export_policy_installed", False):
        return

    original = workspace_schedule.resolve_teacher_collisions

    @wraps(original)
    def resolve_without_unassigned(
        lessons: Sequence[Any],
        teachers_config: Sequence[Mapping[str, Any]],
        *,
        candidate_catalog: Mapping[str, Any] | None = None,
        manual_overrides: Mapping[str, str] | None = None,
    ) -> Dict[str, Any]:
        report = dict(original(
            lessons,
            teachers_config,
            candidate_catalog=candidate_catalog,
            manual_overrides=manual_overrides,
        ))

        retained = [
            lesson
            for lesson in lessons
            if not _is_unassigned_lesson(lesson)
        ]
        excluded_count = len(lessons) - len(retained)

        if isinstance(lessons, MutableSequence):
            lessons[:] = retained
        elif excluded_count:
            raise TypeError(
                "Фильтрация неназначенных занятий требует изменяемого списка."
            )

        source_count = int(report.get("lesson_count") or len(retained) + excluded_count)
        report["source_lesson_count"] = source_count
        report["lesson_count"] = len(retained)
        report["exported_lesson_count"] = len(retained)
        report["excluded_unassigned_lesson_count"] = excluded_count
        report["export_policy"] = "confirmed-teachers-only-v1"

        if excluded_count:
            _rewrite_unassigned_issue(report, excluded_count)

        return report

    workspace_schedule.resolve_teacher_collisions = resolve_without_unassigned
    workspace_schedule._schedule_export_policy_installed = True
