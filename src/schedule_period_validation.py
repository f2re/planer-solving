"""Non-blocking validation of academic schedule periods."""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Sequence, Tuple

from .schedule_period_values import (
    DAY_INDEX,
    DAY_NAMES,
    MONTH_NAMES,
    SEMESTER_LABELS,
    _parse_slot_key,
    _slot_key,
    _text,
    academic_year_from_text,
    canonical_month,
    month_number,
    next_month,
    semester_kind_from_months,
    semester_kind_from_text,
)


def _adjacent_month(left: Any, right: Any) -> bool:
    left_name = canonical_month(left)
    right_name = canonical_month(right)
    return bool(left_name and right_name and (next_month(left_name) == right_name or next_month(right_name) == left_name))


def _ordered_unique(values: Sequence[Any]) -> List[str]:
    result: List[str] = []
    for value in values:
        month = canonical_month(value)
        if month and (not result or result[-1] != month):
            result.append(month)
    return result


def _is_sequential_month_path(values: Sequence[Any]) -> bool:
    ordered = _ordered_unique(values)
    return all(current == previous or next_month(previous) == current for previous, current in zip(ordered, ordered[1:]))


def _issue(
    severity: str,
    code: str,
    message: str,
    *,
    resolution: str = "review",
    action: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    return {
        "severity": severity,
        "code": code,
        "message": message,
        "blocking": False,
        "resolution": resolution,
        "action": dict(action or {}),
    }


def build_file_period_report(
    *,
    week_numbers: Sequence[int],
    week_months: Mapping[int, Any],
    week_day_dates: Mapping[Tuple[int, str], Mapping[str, Any]],
    semester_info: Any = "",
    year_info: Any = "",
) -> Tuple[Dict[str, Any], List[str], List[str]]:
    """Build a JSON-safe period report without rejecting recoverable input.

    The month label above a week is a formatting hint, not a statement that all
    six days belong to that month. Exact dates and their chronological sequence
    have higher priority. Any uncertainty is returned as an editable suggestion.
    """

    weeks = sorted({int(value) for value in week_numbers})
    normalized_week_months: Dict[str, str] = {}
    for week in weeks:
        month = canonical_month(week_months.get(week))
        if month:
            normalized_week_months[str(week)] = month

    normalized_dates: Dict[str, Dict[str, Any]] = {}
    for (week, day_name), item in week_day_dates.items():
        if day_name not in DAY_INDEX:
            continue
        month = canonical_month(item.get("month"))
        try:
            day = int(item.get("day") or 0)
            year = int(item.get("year") or 0)
        except (TypeError, ValueError):
            continue
        if month and 1 <= day <= 31:
            normalized_dates[_slot_key(int(week), day_name)] = {
                "month": month,
                "day": day,
                "year": year if year >= 1900 else 0,
            }

    ordered_slots = sorted(
        normalized_dates.items(),
        key=lambda item: (
            (_parse_slot_key(item[0]) or (10_000, ""))[0],
            DAY_INDEX.get((_parse_slot_key(item[0]) or (0, ""))[1], 99),
        ),
    )
    date_month_path = [item[1]["month"] for item in ordered_slots]
    ordered_months = _ordered_unique([
        *[normalized_week_months.get(str(week)) for week in weeks],
        *date_month_path,
    ])

    week_month_sets: Dict[str, List[str]] = {}
    week_transitions: List[Dict[str, Any]] = []
    issues: List[Dict[str, Any]] = []
    for week in weeks:
        day_months = [
            normalized_dates[_slot_key(week, day_name)]["month"]
            for day_name in DAY_NAMES
            if _slot_key(week, day_name) in normalized_dates
        ]
        header = normalized_week_months.get(str(week))
        month_set: List[str] = []
        for value in [header, *day_months]:
            month = canonical_month(value)
            if month and month not in month_set:
                month_set.append(month)
        week_month_sets[str(week)] = month_set

        distinct_dates = _ordered_unique(day_months)
        if len(distinct_dates) > 1:
            sequential = _is_sequential_month_path(distinct_dates)
            week_transitions.append({
                "week": week,
                "months": distinct_dates,
                "sequential": sequential,
            })
            if sequential:
                issues.append(_issue(
                    "info",
                    "week_month_transition",
                    (
                        f"Неделя {week} переходит из {distinct_dates[0].lower()} в "
                        f"{distinct_dates[-1].lower()}. Это нормальный календарный переход; "
                        "даты приняты автоматически."
                    ),
                    resolution="auto",
                ))
            else:
                issues.append(_issue(
                    "warning",
                    "week_month_order_uncertain",
                    f"В неделе {week} месяцы идут необычно: {', '.join(distinct_dates)}.",
                    action={
                        "type": "edit_period",
                        "week": week,
                        "label": "Проверить даты этой недели",
                    },
                ))

        if header and day_months and header not in day_months:
            if any(_adjacent_month(header, value) for value in day_months):
                issues.append(_issue(
                    "info",
                    "month_header_boundary",
                    (
                        f"Подпись «{header}» над неделей {week} относится к границе месяцев. "
                        "Точные даты имеют приоритет."
                    ),
                    resolution="auto",
                ))
            else:
                issues.append(_issue(
                    "warning",
                    "week_month_date_mismatch",
                    (
                        f"Подпись месяца над неделей {week} — «{header}», а даты относятся к: "
                        f"{', '.join(_ordered_unique(day_months))}. Использованы точные даты."
                    ),
                    resolution="auto",
                    action={
                        "type": "edit_period",
                        "week": week,
                        "label": "Уточнить месяц или даты",
                    },
                ))

    declared = semester_kind_from_text(semester_info)
    derived = semester_kind_from_months(date_month_path or ordered_months)
    academic_year, _ = academic_year_from_text(f"{year_info} {semester_info}")

    if derived == "mixed":
        if _is_sequential_month_path(date_month_path or ordered_months):
            issues.append(_issue(
                "info",
                "semester_boundary_sequence",
                "Календарь последовательно пересекает условную границу семестров; даты сохранены без блокировки.",
                resolution="auto",
            ))
        else:
            issues.append(_issue(
                "warning",
                "mixed_semester_months",
                "В исходном расписании обнаружены месяцы разных условных семестров.",
                action={
                    "type": "calendar_policy",
                    "value": "source",
                    "label": "Использовать последовательность дат Excel",
                },
            ))
    elif declared != "unknown" and derived not in {"unknown", declared}:
        issues.append(_issue(
            "warning",
            "semester_month_mismatch",
            (
                f"Заголовок указывает {SEMESTER_LABELS[declared]} семестр, а даты больше похожи на "
                f"{SEMESTER_LABELS[derived]}. Для результата использована фактическая последовательность дат."
            ),
            resolution="auto",
            action={
                "type": "calendar_policy",
                "value": "source",
                "label": "Оставить календарь исходного файла",
            },
        ))

    missing_month_weeks = [week for week in weeks if not week_month_sets.get(str(week))]
    if not ordered_months:
        issues.append(_issue(
            "warning",
            "months_not_found",
            "Месяцы не распознаны; календарь будет восстановлен по периоду рабочего пространства.",
            resolution="auto",
            action={
                "type": "calendar_policy",
                "value": "workspace",
                "label": "Использовать период пространства",
            },
        ))
    elif missing_month_weeks:
        preview = ", ".join(map(str, missing_month_weeks[:8]))
        suffix = "…" if len(missing_month_weeks) > 8 else ""
        issues.append(_issue(
            "warning",
            "month_gaps",
            f"Для недель {preview}{suffix} месяц будет достроен по соседним датам.",
            resolution="auto",
        ))

    expected_dates = len(weeks) * len(DAY_NAMES)
    if expected_dates and not normalized_dates:
        issues.append(_issue(
            "warning",
            "dates_not_found",
            "Строка дат не распознана; будет использована строка месяцев или период пространства.",
            resolution="auto",
            action={
                "type": "edit_layout",
                "field": "date_row_offset",
                "label": "Уточнить строку дат",
            },
        ))

    effective_semester = (
        derived if derived in {"spring", "autumn"}
        else declared if declared in {"spring", "autumn"}
        else "unknown"
    )
    if not academic_year:
        explicit_years = sorted({
            int(item.get("year") or 0)
            for item in normalized_dates.values()
            if int(item.get("year") or 0) >= 1900
        })
        if len(explicit_years) == 1:
            source_year = explicit_years[0]
            if effective_semester == "spring":
                academic_year = f"{source_year - 1}/{source_year}"
            elif effective_semester == "autumn":
                has_january = any(month_number(item.get("month")) == 1 for item in normalized_dates.values())
                first_year = source_year - 1 if has_january and not any(
                    month_number(item.get("month")) in {8, 9, 10, 11, 12}
                    for item in normalized_dates.values()
                ) else source_year
                academic_year = f"{first_year}/{first_year + 1}"

    period = {
        "week_numbers": weeks,
        "week_months": normalized_week_months,
        "week_month_sets": week_month_sets,
        "week_day_dates": normalized_dates,
        "week_transitions": week_transitions,
        "months": ordered_months,
        "semester_kind": effective_semester,
        "semester_declared": declared,
        "semester_by_months": derived,
        "semester_label": SEMESTER_LABELS.get(effective_semester, "не определён"),
        "semester_info": _text(semester_info),
        "year_info": _text(year_info),
        "academic_year": academic_year,
        "date_cells_found": len(normalized_dates),
        "date_cells_expected": expected_dates,
        "first_source_date": ({"slot": ordered_slots[0][0], **ordered_slots[0][1]} if ordered_slots else None),
        "last_source_date": ({"slot": ordered_slots[-1][0], **ordered_slots[-1][1]} if ordered_slots else None),
        "issues": issues,
        "operator_actions": [item["action"] for item in issues if item.get("action")],
        "blocking": False,
    }
    warnings = [item["message"] for item in issues if item["severity"] == "warning"]
    return period, warnings, []


def compare_file_periods(
    reference: Mapping[str, Any],
    current: Mapping[str, Any],
    *,
    reference_label: str,
    current_label: str,
) -> List[Dict[str, Any]]:
    """Compare files and return suggestions instead of blocking the batch."""

    issues: List[Dict[str, Any]] = []
    ref_semester = str(reference.get("semester_kind") or "unknown")
    cur_semester = str(current.get("semester_kind") or "unknown")
    if ref_semester in {"spring", "autumn"} and cur_semester in {"spring", "autumn"} and ref_semester != cur_semester:
        issues.append(_issue(
            "warning",
            "source_semester_mismatch",
            (
                f"Файлы помечены как разные семестры: «{reference_label}» — {SEMESTER_LABELS[ref_semester]}, "
                f"«{current_label}» — {SEMESTER_LABELS[cur_semester]}. Они всё равно будут сведены по фактическим датам."
            ),
            resolution="auto",
            action={
                "type": "calendar_policy",
                "value": "source",
                "label": "Свести по датам файлов",
            },
        ))

    ref_year = str(reference.get("academic_year") or "")
    cur_year = str(current.get("academic_year") or "")
    if ref_year and cur_year and ref_year != cur_year:
        issues.append(_issue(
            "warning",
            "source_academic_year_mismatch",
            f"Учебные годы различаются: «{reference_label}» — {ref_year}, «{current_label}» — {cur_year}.",
            action={
                "type": "edit_period",
                "label": "Проверить год конкретных дат",
            },
        ))

    ref_sets = reference.get("week_month_sets") or {
        key: [value] for key, value in (reference.get("week_months") or {}).items()
    }
    cur_sets = current.get("week_month_sets") or {
        key: [value] for key, value in (current.get("week_months") or {}).items()
    }
    for raw_week in sorted(set(ref_sets) & set(cur_sets), key=lambda value: int(value)):
        left = [month for value in ref_sets.get(raw_week, []) if (month := canonical_month(value))]
        right = [month for value in cur_sets.get(raw_week, []) if (month := canonical_month(value))]
        if not left or not right or set(left) & set(right):
            continue
        if any(_adjacent_month(a, b) for a in left for b in right):
            issues.append(_issue(
                "info",
                "source_week_month_transition",
                (
                    f"Неделя {raw_week} подписана соседними месяцами в разных файлах "
                    f"({', '.join(left)} / {', '.join(right)}). Это допустимо на границе месяца."
                ),
                resolution="auto",
            ))
        else:
            issues.append(_issue(
                "warning",
                "source_week_month_mismatch",
                (
                    f"Для недели {raw_week} файлы дают разные месяцы: «{reference_label}» — "
                    f"{', '.join(left)}, «{current_label}» — {', '.join(right)}. Выберется наиболее согласованный календарь."
                ),
                resolution="auto",
                action={
                    "type": "edit_period",
                    "week": int(raw_week),
                    "label": "Уточнить неделю вручную",
                },
            ))

    ref_dates = reference.get("week_day_dates") or {}
    cur_dates = current.get("week_day_dates") or {}
    for key in sorted(set(ref_dates) & set(cur_dates)):
        left, right = ref_dates[key], cur_dates[key]
        left_value = (canonical_month(left.get("month")), int(left.get("day") or 0), int(left.get("year") or 0))
        right_value = (canonical_month(right.get("month")), int(right.get("day") or 0), int(right.get("year") or 0))
        if left_value[:2] == right_value[:2] and (not left_value[2] or not right_value[2] or left_value[2] == right_value[2]):
            continue
        issues.append(_issue(
            "warning",
            "source_date_mismatch",
            (
                f"Дата {key.replace(':', ', ')} различается: «{reference_label}» — "
                f"{left_value[1]} {(left_value[0] or '').lower()}, «{current_label}» — "
                f"{right_value[1]} {(right_value[0] or '').lower()}. Используется вариант, согласованный с большинством дат."
            ),
            resolution="auto",
            action={
                "type": "edit_period",
                "slot": key,
                "label": "Выбрать дату вручную",
            },
        ))
    return issues
