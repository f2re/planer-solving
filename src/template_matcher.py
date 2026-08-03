"""Evaluate saved layouts against a workbook and rank them by useful parsed data."""
from __future__ import annotations

from copy import deepcopy
import logging
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from .data_loader import DataLoader
from .schedule_analyzer import ScheduleLayout
from .template_definition import component_candidates, normalize_definition

logger = logging.getLogger(__name__)


def _value(item: Any, name: str, default: Any = "") -> Any:
    if isinstance(item, Mapping):
        return item.get(name, default)
    return getattr(item, name, default)


def _lesson_signature(lesson: Any) -> tuple[Any, ...]:
    return (
        _value(lesson, "week", 0),
        _value(lesson, "day_of_week", ""),
        _value(lesson, "pair_num", 0),
        str(_value(lesson, "subject", "")).strip().casefold(),
        str(_value(lesson, "room", "")).strip().casefold(),
    )


def score_candidate(report: Mapping[str, Any], lessons: Sequence[Any]) -> Dict[str, Any]:
    errors = [str(item) for item in report.get("errors", []) if str(item).strip()]
    warnings = [str(item) for item in report.get("warnings", []) if str(item).strip()]
    lesson_count = len(lessons)
    signatures = {_lesson_signature(item) for item in lessons}
    unique_lessons = len(signatures)
    duplicate_lessons = max(0, lesson_count - unique_lessons)
    mapped_lessons = sum(
        1
        for item in lessons
        if str(_value(item, "teacher", "Unknown")).strip().casefold()
        not in {"", "unknown", "none"}
    )
    unknown_teachers = max(0, lesson_count - mapped_lessons)
    subjects = {
        str(_value(item, "subject", "")).strip().casefold()
        for item in lessons
        if str(_value(item, "subject", "")).strip()
    }
    weeks = {
        int(_value(item, "week", 0))
        for item in lessons
        if str(_value(item, "week", "")).strip().isdigit()
        and int(_value(item, "week", 0)) > 0
    }
    legend_entries = max(0, int(report.get("legend_entries", 0) or 0))
    empty_week_columns = len(report.get("empty_week_columns", []) or [])

    uniqueness_ratio = unique_lessons / lesson_count if lesson_count else 0.0
    mapping_ratio = mapped_lessons / lesson_count if lesson_count else 0.0
    week_coverage = min(1.0, len(weeks) / 4.0)
    subject_coverage = min(1.0, len(subjects) / 4.0)
    quality = (
        mapping_ratio * 0.45
        + uniqueness_ratio * 0.25
        + week_coverage * 0.15
        + subject_coverage * 0.15
    )

    usable = bool(lesson_count) and not errors
    if not usable:
        score = -100_000.0 - len(errors) * 5_000.0 - len(warnings) * 25.0
        quality = 0.0
    else:
        information = (
            unique_lessons * 5.0
            + mapped_lessons * 6.0
            + len(subjects) * 3.0
            + len(weeks) * 4.0
            + min(legend_entries, max(1, len(subjects) * 2)) * 1.5
        )
        penalties = (
            duplicate_lessons * 8.0
            + unknown_teachers * 2.5
            + len(warnings) * 2.0
            + empty_week_columns * 1.5
        )
        score = information * (0.65 + quality * 0.35) - penalties

    reasons: List[str] = []
    if errors:
        reasons.append(f"Критических ошибок: {len(errors)}")
    if lesson_count:
        reasons.append(f"Распознано уникальных занятий: {unique_lessons}")
        reasons.append(f"Преподаватель определён: {mapped_lessons} из {lesson_count}")
        reasons.append(f"Учебных недель: {len(weeks)}, дисциплин: {len(subjects)}")
    if duplicate_lessons:
        reasons.append(f"Повторных записей: {duplicate_lessons}")
    if warnings:
        reasons.append(f"Предупреждений: {len(warnings)}")
    if not reasons:
        reasons.append("Полезные данные не найдены")

    return {
        "usable": usable,
        "score": round(score, 3),
        "quality_percent": round(quality * 100),
        "metrics": {
            "lesson_count": lesson_count,
            "unique_lessons": unique_lessons,
            "mapped_lessons": mapped_lessons,
            "unknown_teacher_lessons": unknown_teachers,
            "unique_subjects": len(subjects),
            "active_weeks": len(weeks),
            "legend_entries": legend_entries,
            "duplicate_lessons": duplicate_lessons,
            "warning_count": len(warnings),
            "error_count": len(errors),
            "empty_week_columns": empty_week_columns,
        },
        "errors": errors,
        "warnings": warnings,
        "reasons": reasons,
    }


def _evaluate_single(
    *,
    file_path: str | Path,
    teachers_path: str | Path,
    group_name: str,
    layout: Mapping[str, Any],
    component_id: str | None,
    component_label: str,
    fingerprint_similarity: float,
) -> Dict[str, Any]:
    candidate_layout = deepcopy(dict(layout))
    loader = DataLoader(str(teachers_path))
    try:
        normalized = ScheduleLayout.from_dict(candidate_layout)
        lessons = loader.load_group_schedule(
            str(file_path),
            group_name=group_name,
            layout=normalized,
        )
        report = dict(loader.last_report)
    except Exception:
        logger.exception("Cannot evaluate layout component %s for %s", component_label, file_path)
        lessons = []
        report = {
            "errors": ["Шаблон не удалось проверить."],
            "warnings": [],
            "legend_entries": 0,
            "empty_week_columns": [],
        }
    result = score_candidate(report, lessons)
    result["parser_score"] = result["score"]
    result["fingerprint_similarity"] = round(float(fingerprint_similarity), 2)
    if result["usable"]:
        result["score"] = round(float(result["score"]) + float(fingerprint_similarity) * 0.25, 3)
        if fingerprint_similarity:
            result["reasons"].append(
                f"Структурное сходство формата: {round(float(fingerprint_similarity))}%"
            )
    result.update({
        "layout": candidate_layout,
        "component_id": component_id,
        "component_label": component_label,
    })
    return result


def evaluate_layout(
    *,
    file_path: str | Path,
    teachers_path: str | Path,
    group_name: str,
    layout: Mapping[str, Any],
    source: str,
    name: str,
    template_id: str | None = None,
    available_sheets: Iterable[str] = (),
    fallback_sheet: str = "",
    workbook_fingerprint: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    """Run the real parser for every component and return the best one."""

    definition = normalize_definition(layout)
    candidates = component_candidates(
        definition,
        workbook_fingerprint,
        available_sheets,
        fallback_sheet,
    )
    evaluated = [
        _evaluate_single(
            file_path=file_path,
            teachers_path=teachers_path,
            group_name=group_name,
            layout=item["layout"],
            component_id=item["component_id"],
            component_label=item["component_label"],
            fingerprint_similarity=item["fingerprint_similarity"],
        )
        for item in candidates
    ]
    selected = sorted(
        evaluated,
        key=lambda item: (
            float(item.get("score", -100_000)),
            int(item.get("quality_percent", 0)),
            float(item.get("fingerprint_similarity", 0)),
        ),
        reverse=True,
    )[0]
    selected.update({
        "source": source,
        "name": name,
        "template_id": template_id,
        "candidate_key": f"{source}:{template_id or 'automatic'}",
        "definition": definition,
        "component_results": [{
            "component_id": item.get("component_id"),
            "component_label": item.get("component_label"),
            "score": item.get("score"),
            "quality_percent": item.get("quality_percent"),
            "fingerprint_similarity": item.get("fingerprint_similarity"),
            "usable": item.get("usable"),
        } for item in evaluated],
    })
    return selected


def rank_candidates(candidates: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(
        (dict(item) for item in candidates),
        key=lambda item: (
            float(item.get("score", -100_000)),
            int(item.get("quality_percent", 0)),
            int(item.get("metrics", {}).get("mapped_lessons", 0)),
            int(item.get("metrics", {}).get("unique_lessons", 0)),
            float(item.get("fingerprint_similarity", 0)),
            1 if item.get("source") == "automatic" else 0,
        ),
        reverse=True,
    )
