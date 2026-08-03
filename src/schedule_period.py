"""Public schedule-period API used by parsing and both exporters."""
from __future__ import annotations

from datetime import date
from typing import Any, Mapping, Optional, Sequence

from .schedule_calendar import (
    ResolvedScheduleCalendar,
    SchedulePeriodError,
    resolve_schedule_calendar as _resolve_schedule_calendar,
)
from .schedule_period_validation import (
    build_file_period_report,
    compare_file_periods,
)
from .schedule_period_values import (
    DAY_INDEX,
    DAY_NAMES,
    MONTH_GENITIVE,
    MONTH_NAMES,
    canonical_month,
    extract_date_parts,
    month_number,
    next_month,
    semester_kind_from_months,
    semester_kind_from_text,
)


def _manual_date(value: Any) -> Optional[date]:
    if isinstance(value, date):
        return value
    if isinstance(value, Mapping):
        try:
            year = int(value.get("year") or 0)
            month = month_number(value.get("month"))
            day = int(value.get("day") or 0)
            return date(year, month, day) if year >= 1900 and month and day else None
        except (TypeError, ValueError):
            return None
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def resolve_schedule_calendar(
    lessons: Sequence[Any],
    *,
    start_date_str: Any,
    end_date_str: Any,
    period_reports: Optional[Sequence[Mapping[str, Any]]] = None,
    overrides: Optional[Mapping[str, Any]] = None,
) -> ResolvedScheduleCalendar:
    """Resolve the calendar and then apply operator dates literally.

    Automatic reconciliation chooses a coherent weekly scale. A value entered
    by the operator is not another weak hint: it is the final value for that
    particular cell, even when it intentionally breaks the inferred sequence.
    """

    result = _resolve_schedule_calendar(
        lessons,
        start_date_str=start_date_str,
        end_date_str=end_date_str,
        period_reports=period_reports,
        overrides=overrides,
    )
    manual_values = (overrides or {}).get("week_day_dates") or {}
    applied = []
    manual_slots: set[str] = set()
    for raw_slot, raw_value in manual_values.items():
        try:
            raw_week, day_name = str(raw_slot).split(":", 1)
            key = (int(raw_week), day_name)
        except (TypeError, ValueError):
            continue
        manual = _manual_date(raw_value)
        if manual is None or day_name not in DAY_INDEX or key not in result.week_day_to_date:
            continue
        slot = f"{key[0]}:{key[1]}"
        manual_slots.add(slot)
        previous = result.week_day_to_date[key]
        result.week_day_to_date[key] = manual
        if previous != manual:
            applied.append({
                "type": "operator_date",
                "slot": slot,
                "before": previous.isoformat(),
                "after": manual.isoformat(),
                "reason": "Точная ручная правка оператора.",
                "blocking": False,
            })

    if manual_slots:
        # Remove provisional automatic decisions for cells whose final value is
        # explicitly controlled by the operator. The report must not claim that
        # an operator date was rejected and accepted at the same time.
        result.report["corrections"] = [
            item for item in result.report.get("corrections", [])
            if str(item.get("slot") or "") not in manual_slots
        ]
        result.report["issues"] = [
            item for item in result.report.get("issues", [])
            if not (
                item.get("code") == "calendar_source_conflict"
                and str((item.get("action") or {}).get("slot") or "") in manual_slots
            )
        ]

    if applied:
        values = list(result.week_day_to_date.values())
        result.source = "operator_dates"
        result.report["calendar_source"] = result.source
        result.report["resolved_start_date"] = min(values).isoformat()
        result.report["resolved_end_date"] = max(values).isoformat()
        result.report["months"] = list(dict.fromkeys(MONTH_NAMES[value.month] for value in values))
        result.report.setdefault("corrections", []).extend(applied)
        result.report.setdefault("issues", []).append({
            "severity": "info",
            "code": "operator_dates_applied",
            "message": f"Применено ручных правок дат: {len(applied)}.",
            "blocking": False,
            "resolution": "operator",
            "action": {},
        })
        result.report["operator_override_count"] = len(applied)

    warnings = [
        str(item.get("message") or "")
        for item in result.report.get("issues", [])
        if item.get("severity") == "warning" and item.get("message")
    ]
    result.report["warnings"] = warnings
    result.warnings = warnings
    return result


__all__ = [
    "DAY_INDEX",
    "DAY_NAMES",
    "MONTH_GENITIVE",
    "MONTH_NAMES",
    "ResolvedScheduleCalendar",
    "SchedulePeriodError",
    "build_file_period_report",
    "canonical_month",
    "compare_file_periods",
    "extract_date_parts",
    "month_number",
    "next_month",
    "resolve_schedule_calendar",
    "semester_kind_from_months",
    "semester_kind_from_text",
]
