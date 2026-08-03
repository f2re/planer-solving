"""Per-file and cross-file validation of academic schedule periods."""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Sequence, Tuple

from .schedule_period_values import (
    DAY_INDEX, DAY_NAMES, MONTH_NAMES, SEMESTER_LABELS,
    _parse_slot_key, _slot_key, _text, academic_year_from_text,
    canonical_month, month_number, semester_kind_from_months,
    semester_kind_from_text,
)


def build_file_period_report(
    *,
    week_numbers: Sequence[int],
    week_months: Mapping[int, Any],
    week_day_dates: Mapping[Tuple[int, str], Mapping[str, Any]],
    semester_info: Any = "",
    year_info: Any = "",
) -> Tuple[Dict[str, Any], List[str], List[str]]:
    """Build a JSON-safe period summary and parser-stage diagnostics."""

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

    ordered_months: List[str] = []
    for week in weeks:
        month = normalized_week_months.get(str(week))
        if month and month not in ordered_months:
            ordered_months.append(month)
    for key in sorted(normalized_dates, key=lambda item: (_parse_slot_key(item) or (10_000, ""))[0]):
        month = normalized_dates[key]["month"]
        if month not in ordered_months:
            ordered_months.append(month)

    declared = semester_kind_from_text(semester_info)
    derived = semester_kind_from_months(ordered_months)
    academic_year, _ = academic_year_from_text(f"{year_info} {semester_info}")
    issues: List[Dict[str, str]] = []

    def issue(severity: str, code: str, message: str) -> None:
        issues.append({"severity": severity, "code": code, "message": message})

    if derived == "mixed":
        issue(
            "error",
            "mixed_semester_months",
            "В одном исходном расписании одновременно обнаружены месяцы весеннего и осеннего семестров.",
        )
    elif declared != "unknown" and derived not in {"unknown", declared}:
        issue(
            "error",
            "semester_month_mismatch",
            f"Заголовок указывает {SEMESTER_LABELS[declared]} семестр, а месяцы относятся к {SEMESTER_LABELS[derived]} семестру.",
        )
    missing_month_weeks = [week for week in weeks if str(week) not in normalized_week_months]
    if not ordered_months:
        issue(
            "warning",
            "months_not_found",
            "Месяцы исходного расписания не определены. Перед формированием необходимо проверить строку месяцев и даты.",
        )
    elif missing_month_weeks:
        preview = ", ".join(map(str, missing_month_weeks[:8]))
        suffix = "…" if len(missing_month_weeks) > 8 else ""
        issue(
            "warning",
            "month_gaps",
            f"Не удалось определить месяц для недель: {preview}{suffix}.",
        )
    for week in weeks:
        header_month = normalized_week_months.get(str(week))
        date_months = {
            item["month"]
            for key, item in normalized_dates.items()
            if (_parse_slot_key(key) or (None, None))[0] == week
        }
        if header_month and date_months and header_month not in date_months:
            issue(
                "error",
                "week_month_date_mismatch",
                (
                    f"Для недели {week} строка месяцев указывает «{header_month}», "
                    f"а строка дат относится к: {', '.join(sorted(date_months))}."
                ),
            )

    expected_dates = len(weeks) * len(DAY_NAMES)
    if expected_dates and not normalized_dates:
        issue(
            "warning",
            "dates_not_found",
            "Даты дней недели не распознаны; календарь можно будет проверить только по строке месяцев.",
        )

    effective_semester = declared if declared != "unknown" else (derived if derived != "mixed" else "unknown")
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

    ordered_slots = sorted(
        normalized_dates.items(),
        key=lambda item: (
            (_parse_slot_key(item[0]) or (10_000, ""))[0],
            DAY_INDEX.get((_parse_slot_key(item[0]) or (0, ""))[1], 99),
        ),
    )
    period = {
        "week_numbers": weeks,
        "week_months": normalized_week_months,
        "week_day_dates": normalized_dates,
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
    }
    warnings = [item["message"] for item in issues if item["severity"] == "warning"]
    errors = [item["message"] for item in issues if item["severity"] == "error"]
    return period, warnings, errors


def compare_file_periods(
    reference: Mapping[str, Any],
    current: Mapping[str, Any],
    *,
    reference_label: str,
    current_label: str,
) -> List[Dict[str, str]]:
    """Compare two parser reports before their lessons are merged."""

    issues: List[Dict[str, str]] = []
    ref_semester = str(reference.get("semester_kind") or "unknown")
    cur_semester = str(current.get("semester_kind") or "unknown")
    if ref_semester in {"spring", "autumn"} and cur_semester in {"spring", "autumn"} and ref_semester != cur_semester:
        issues.append({
            "severity": "error",
            "code": "source_semester_mismatch",
            "message": (
                f"Файлы относятся к разным семестрам: «{reference_label}» — {SEMESTER_LABELS[ref_semester]}, "
                f"«{current_label}» — {SEMESTER_LABELS[cur_semester]}."
            ),
        })
    ref_year = str(reference.get("academic_year") or "")
    cur_year = str(current.get("academic_year") or "")
    if ref_year and cur_year and ref_year != cur_year:
        issues.append({
            "severity": "error",
            "code": "source_academic_year_mismatch",
            "message": f"Файлы относятся к разным учебным годам: «{reference_label}» — {ref_year}, «{current_label}» — {cur_year}.",
        })

    ref_week_months = {int(key): canonical_month(value) for key, value in (reference.get("week_months") or {}).items()}
    cur_week_months = {int(key): canonical_month(value) for key, value in (current.get("week_months") or {}).items()}
    for week in sorted(set(ref_week_months) & set(cur_week_months)):
        left, right = ref_week_months[week], cur_week_months[week]
        if left and right and left != right:
            issues.append({
                "severity": "error",
                "code": "source_week_month_mismatch",
                "message": f"Неделя {week} имеет разные месяцы: «{reference_label}» — {left}, «{current_label}» — {right}.",
            })
            break

    ref_dates = reference.get("week_day_dates") or {}
    cur_dates = current.get("week_day_dates") or {}
    for key in sorted(set(ref_dates) & set(cur_dates)):
        left, right = ref_dates[key], cur_dates[key]
        left_value = (canonical_month(left.get("month")), int(left.get("day") or 0))
        right_value = (canonical_month(right.get("month")), int(right.get("day") or 0))
        if all(left_value) and all(right_value) and left_value != right_value:
            issues.append({
                "severity": "error",
                "code": "source_date_mismatch",
                "message": (
                    f"Дата {key.replace(':', ', ')} различается: «{reference_label}» — "
                    f"{left_value[1]} {left_value[0].lower()}, «{current_label}» — {right_value[1]} {right_value[0].lower()}."
                ),
            })
            break
    return issues
