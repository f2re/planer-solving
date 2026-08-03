"""Best-effort calendar resolution shared by all schedule exporters."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .schedule_period_values import (
    DAY_INDEX,
    DAY_NAMES,
    MONTH_NAMES,
    SEMESTER_LABELS,
    _parse_slot_key,
    academic_year_from_text,
    canonical_month,
    month_number,
    semester_kind_from_months,
)
from .schedule_period_validation import build_file_period_report, compare_file_periods


@dataclass
class ResolvedScheduleCalendar:
    weeks: List[int]
    week_day_to_date: Dict[Tuple[int, str], date]
    source: str
    semester_kind: str = "unknown"
    academic_year: str = ""
    warnings: List[str] = field(default_factory=list)
    report: Dict[str, Any] = field(default_factory=dict)

    def date_for(self, week: int, day_name: str) -> Optional[date]:
        return self.week_day_to_date.get((int(week), day_name))

    @property
    def week_to_month(self) -> Dict[int, str]:
        result: Dict[int, str] = {}
        for week in self.weeks:
            value = self.date_for(week, "Пн")
            if value:
                result[week] = MONTH_NAMES[value.month]
        return result

    def summary_dates(self) -> List[Tuple[str, int, int]]:
        result: List[Tuple[str, int, int]] = []
        for week in self.weeks:
            for day_name in DAY_NAMES:
                value = self.date_for(week, day_name)
                if value:
                    result.append((MONTH_NAMES[value.month], value.day, week))
        return result


class SchedulePeriodError(ValueError):
    """Compatibility exception for unrecoverable infrastructure failures.

    Calendar disagreements are no longer unrecoverable and therefore do not
    raise this exception. It remains public for older integrations.
    """

    def __init__(self, errors: Sequence[str], *, warnings: Sequence[str] = (), report: Optional[Mapping[str, Any]] = None):
        self.errors = list(errors)
        self.warnings = list(warnings)
        self.report = dict(report or {})
        super().__init__("; ".join(self.errors) or "Не удалось согласовать период расписания.")


def _parse_configured_date(value: Any, fallback: date) -> date:
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return fallback


def _range_semester(start: date, end: date) -> str:
    months: List[int] = []
    cursor = date(start.year, start.month, 1)
    limit = date(end.year, end.month, 1)
    for _ in range(36):
        months.append(cursor.month)
        if cursor == limit:
            break
        cursor = date(
            cursor.year + (1 if cursor.month == 12 else 0),
            1 if cursor.month == 12 else cursor.month + 1,
            1,
        )
    return semester_kind_from_months(MONTH_NAMES[number] for number in months)


def _candidate_years(
    configured_start: date,
    configured_end: date,
    academic_year: Optional[Tuple[int, int]],
) -> List[int]:
    years = {
        configured_start.year - 1,
        configured_start.year,
        configured_end.year,
        configured_end.year + 1,
    }
    if academic_year:
        years.update({academic_year[0] - 1, academic_year[0], academic_year[1], academic_year[1] + 1})
    return sorted(years)


def _expected_years_for_month(
    month: int,
    semester_kind: str,
    academic_year: Optional[Tuple[int, int]],
    fallback_years: Sequence[int],
) -> Sequence[int]:
    if academic_year:
        first, second = academic_year
        if semester_kind == "spring":
            return [second]
        if semester_kind == "autumn":
            return [first if month >= 8 else second]
    return fallback_years


def _week_dates(base_monday: date, week: int) -> List[date]:
    monday = base_monday + timedelta(weeks=int(week) - 1)
    return [monday + timedelta(days=index) for index in range(len(DAY_NAMES))]


def _configured_week_numbers(start: date, end: date) -> List[int]:
    current_monday = start - timedelta(days=start.weekday())
    weeks: List[int] = []
    week = 1
    while current_monday <= end:
        weeks.append(week)
        current_monday += timedelta(weeks=1)
        week += 1
    return weeks


def _period_has_calendar_evidence(period: Mapping[str, Any]) -> bool:
    return bool((period.get("week_months") or {}) or (period.get("week_day_dates") or {}))


def _period_week_numbers(period: Mapping[str, Any]) -> set[int]:
    result: set[int] = set()
    for raw_week in period.get("week_numbers") or []:
        try:
            result.add(int(raw_week))
        except (TypeError, ValueError):
            continue
    for raw_week in (period.get("week_months") or {}).keys():
        try:
            result.add(int(raw_week))
        except (TypeError, ValueError):
            continue
    for raw_key in (period.get("week_day_dates") or {}).keys():
        parsed = _parse_slot_key(raw_key)
        if parsed:
            result.add(parsed[0])
    return result


def _issue(
    severity: str,
    code: str,
    message: str,
    *,
    resolution: str = "auto",
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


def _parse_override_date(value: Any) -> Optional[date]:
    if isinstance(value, date):
        return value
    if isinstance(value, Mapping):
        try:
            year = int(value.get("year") or 0)
            month = month_number(value.get("month"))
            day = int(value.get("day") or 0)
            if year >= 1900 and month and day:
                return date(year, month, day)
        except (TypeError, ValueError):
            return None
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _academic_year_from_dates(values: Iterable[date], semester_kind: str) -> str:
    dates = sorted(values)
    if not dates:
        return ""
    if semester_kind == "spring":
        year = dates[-1].year
        return f"{year - 1}/{year}"
    if semester_kind == "autumn":
        first = next((item.year for item in dates if item.month >= 8), dates[0].year - (1 if dates[0].month == 1 else 0))
        return f"{first}/{first + 1}"
    if dates[0].year != dates[-1].year:
        return f"{dates[0].year}/{dates[-1].year}"
    return ""


def resolve_schedule_calendar(
    lessons: Sequence[Any],
    *,
    start_date_str: Any,
    end_date_str: Any,
    period_reports: Optional[Sequence[Mapping[str, Any]]] = None,
    overrides: Optional[Mapping[str, Any]] = None,
) -> ResolvedScheduleCalendar:
    """Resolve one calendar, automatically reconciling recoverable conflicts.

    Priority is: manual operator corrections, consistent exact dates, majority
    of source dates, month labels, then workspace period. No calendar warning
    blocks schedule generation.
    """

    overrides = dict(overrides or {})
    today = date.today()
    fallback_start = date(today.year, 2, 1)
    fallback_end = date(today.year, 6, 30)
    configured_start = _parse_configured_date(overrides.get("start_date") or start_date_str, fallback_start)
    configured_end = _parse_configured_date(overrides.get("end_date") or end_date_str, fallback_end)
    issues: List[Dict[str, Any]] = []
    corrections: List[Dict[str, Any]] = []

    def add_issue(
        severity: str,
        code: str,
        message: str,
        *,
        resolution: str = "auto",
        action: Mapping[str, Any] | None = None,
    ) -> None:
        if any(item["code"] == code and item["message"] == message for item in issues):
            return
        issues.append(_issue(severity, code, message, resolution=resolution, action=action))

    if configured_end < configured_start:
        configured_start, configured_end = configured_end, configured_start
        add_issue(
            "warning",
            "workspace_period_reordered",
            "Дата начала пространства была позже даты окончания; границы переставлены автоматически.",
        )
    configured_monday = configured_start - timedelta(days=configured_start.weekday())
    policy = str(overrides.get("policy") or "auto").strip().lower()
    if policy not in {"auto", "source", "workspace"}:
        policy = "auto"

    usable_reports: List[Tuple[str, Mapping[str, Any]]] = []
    for index, report in enumerate(period_reports or []):
        period = report.get("period") or {}
        if period:
            label = str(report.get("file") or report.get("group") or f"Файл {index + 1}")
            usable_reports.append((label, period))

    if not usable_reports:
        grouped: Dict[str, List[Any]] = defaultdict(list)
        for lesson in lessons:
            grouped[str(getattr(lesson, "group", "") or "Без группы")].append(lesson)
        for label, items in grouped.items():
            week_numbers = sorted({int(getattr(item, "week")) for item in items})
            week_months: Dict[int, str] = {}
            week_day_dates: Dict[Tuple[int, str], Dict[str, Any]] = {}
            for item in items:
                week = int(getattr(item, "week"))
                day_name = str(getattr(item, "day_of_week", ""))
                month = canonical_month(getattr(item, "month", ""))
                day = int(getattr(item, "date_day", 0) or 0)
                year = int(getattr(item, "date_year", 0) or 0)
                if month:
                    week_months.setdefault(week, month)
                if day_name in DAY_INDEX and month and 1 <= day <= 31:
                    week_day_dates[(week, day_name)] = {"month": month, "day": day, "year": year}
            period, _, _ = build_file_period_report(
                week_numbers=week_numbers,
                week_months=week_months,
                week_day_dates=week_day_dates,
                semester_info=getattr(items[0], "semester_info", "") if items else "",
                year_info=getattr(items[0], "year_info", "") if items else "",
            )
            usable_reports.append((label, period))

    for _, period in usable_reports:
        for item in period.get("issues") or []:
            severity = "warning" if str(item.get("severity")) == "error" else str(item.get("severity") or "warning")
            add_issue(
                severity,
                str(item.get("code") or "source_period_issue"),
                str(item.get("message") or "Период требует проверки."),
                resolution=str(item.get("resolution") or "auto"),
                action=item.get("action") or {},
            )

    for left_index, (left_label, left) in enumerate(usable_reports):
        for right_label, right in usable_reports[left_index + 1:]:
            for item in compare_file_periods(left, right, reference_label=left_label, current_label=right_label):
                add_issue(
                    str(item.get("severity") or "warning"),
                    str(item.get("code") or "source_period_difference"),
                    str(item.get("message") or "Периоды файлов различаются."),
                    resolution=str(item.get("resolution") or "auto"),
                    action=item.get("action") or {},
                )

    has_source_evidence = any(_period_has_calendar_evidence(period) for _, period in usable_reports)
    source_weeks: set[int] = set()
    for _, period in usable_reports:
        source_weeks.update(_period_week_numbers(period))
    source_weeks.update(
        int(getattr(item, "week"))
        for item in lessons
        if getattr(item, "week", None) is not None
    )
    weeks = sorted(source_weeks) if source_weeks else _configured_week_numbers(configured_start, configured_end)
    if not weeks:
        weeks = [1]
        add_issue("warning", "weeks_recovered", "Не найдено номеров недель; создана первая неделя периода пространства.")

    semester_values = {
        str(period.get("semester_kind"))
        for _, period in usable_reports
        if str(period.get("semester_kind")) in {"spring", "autumn"}
    }
    if len(semester_values) > 1:
        add_issue(
            "warning",
            "source_semester_mismatch",
            "Файлы имеют разные подписи семестра; календарь строится по фактическим датам.",
            action={"type": "calendar_policy", "value": "source", "label": "Использовать даты файлов"},
        )
    source_semester = next(iter(semester_values), "unknown")

    academic_year_values = {
        str(period.get("academic_year"))
        for _, period in usable_reports
        if str(period.get("academic_year") or "")
    }
    if len(academic_year_values) > 1:
        add_issue(
            "warning",
            "source_academic_year_mismatch",
            "В заголовках указаны разные учебные годы; конкретные даты имеют приоритет.",
            action={"type": "edit_period", "label": "Проверить конкретные даты"},
        )
    academic_year_text = next(iter(academic_year_values), "")
    _, academic_year = academic_year_from_text(academic_year_text)

    configured_semester = _range_semester(configured_start, configured_end)
    if source_semester in {"spring", "autumn"} and configured_semester in {"spring", "autumn"} and source_semester != configured_semester:
        add_issue(
            "warning",
            "workspace_semester_mismatch",
            (
                f"Пространство настроено на {SEMESTER_LABELS[configured_semester]} семестр, а файлы похожи на "
                f"{SEMESTER_LABELS[source_semester]}. По умолчанию используются даты файлов; менять исходник не требуется."
            ),
            action={"type": "calendar_policy", "value": "workspace", "label": "Всё же использовать период пространства"},
        )

    observations: Dict[Tuple[int, str], List[Tuple[int, int, int, str, int]]] = defaultdict(list)
    week_month_hints: Dict[int, List[Tuple[int, str, int]]] = defaultdict(list)

    def add_observation(
        key: Tuple[int, str],
        month: Any,
        day: Any,
        year: Any,
        label: str,
        priority: int,
    ) -> None:
        number = month_number(month)
        try:
            day_number = int(day or 0)
            year_number = int(year or 0)
        except (TypeError, ValueError):
            return
        if number and 1 <= day_number <= 31:
            observations[key].append((number, day_number, year_number if year_number >= 1900 else 0, label, priority))

    for label, period in usable_reports:
        for raw_week, raw_month in (period.get("week_months") or {}).items():
            try:
                week = int(raw_week)
            except (TypeError, ValueError):
                continue
            number = month_number(raw_month)
            if number:
                week_month_hints[week].append((number, label, 1))
        for raw_week, raw_months in (period.get("week_month_sets") or {}).items():
            try:
                week = int(raw_week)
            except (TypeError, ValueError):
                continue
            for raw_month in raw_months or []:
                number = month_number(raw_month)
                if number:
                    week_month_hints[week].append((number, label, 2))
        for raw_key, item in (period.get("week_day_dates") or {}).items():
            parsed = _parse_slot_key(raw_key)
            if parsed:
                add_observation(parsed, item.get("month"), item.get("day"), item.get("year"), label, 5)

    for item in lessons:
        week = int(getattr(item, "week"))
        day_name = str(getattr(item, "day_of_week", ""))
        if day_name in DAY_INDEX:
            add_observation(
                (week, day_name),
                getattr(item, "month", ""),
                getattr(item, "date_day", 0),
                getattr(item, "date_year", 0),
                str(getattr(item, "group", "") or "занятие"),
                3,
            )

    for raw_key, raw_value in (overrides.get("week_day_dates") or {}).items():
        parsed = _parse_slot_key(str(raw_key))
        override_date = _parse_override_date(raw_value)
        if parsed and override_date:
            observations[parsed].append((
                override_date.month,
                override_date.day,
                override_date.year,
                "Ручная правка оператора",
                100,
            ))
    for raw_week, raw_month in (overrides.get("week_months") or {}).items():
        try:
            week = int(raw_week)
        except (TypeError, ValueError):
            continue
        number = month_number(raw_month)
        if number:
            week_month_hints[week].append((number, "Ручная правка оператора", 100))

    selected_observations: Dict[Tuple[int, str], Tuple[int, int, int, str, int]] = {}
    for key, candidates in observations.items():
        weighted: Counter[Tuple[int, int, int]] = Counter()
        for month, day, year, _, priority in candidates:
            weighted[(month, day, year)] += priority
            if year:
                weighted[(month, day, 0)] += max(1, priority // 2)
        best_key = max(weighted, key=lambda value: (weighted[value], bool(value[2])))
        matching = [
            item for item in candidates
            if item[:2] == best_key[:2] and (not best_key[2] or item[2] == best_key[2])
        ]
        selected = max(matching, key=lambda item: (item[4], bool(item[2])))
        selected_observations[key] = selected
        distinct = {(item[0], item[1], item[2]) for item in candidates}
        if len(distinct) > 1:
            add_issue(
                "warning",
                "source_date_reconciled",
                (
                    f"Для недели {key[0]}, {key[1]} встретились разные даты. Выбран наиболее согласованный "
                    f"вариант: {selected[1]:02d}.{selected[0]:02d}{'.' + str(selected[2]) if selected[2] else ''}."
                ),
                action={"type": "edit_period", "slot": f"{key[0]}:{key[1]}", "label": "Изменить выбранную дату"},
            )

    candidate_year_values = _candidate_years(configured_start, configured_end, academic_year)
    candidate_bases: Counter[date] = Counter()
    for (week, day_name), (month, day, explicit_year, _, priority) in selected_observations.items():
        years = [explicit_year] if explicit_year else _expected_years_for_month(
            month,
            source_semester,
            academic_year,
            candidate_year_values,
        )
        for year in years:
            try:
                value = date(year, month, day)
            except ValueError:
                continue
            if value.weekday() != DAY_INDEX[day_name]:
                continue
            monday = value - timedelta(days=DAY_INDEX[day_name])
            candidate_bases[monday - timedelta(weeks=week - 1)] += priority

    def exact_score(base: date) -> int:
        result = 0
        for (week, day_name), (month, day, explicit_year, _, priority) in selected_observations.items():
            value = base + timedelta(weeks=week - 1, days=DAY_INDEX[day_name])
            if value.month == month and value.day == day and (not explicit_year or value.year == explicit_year):
                result += priority
        return result

    def month_score(base: date) -> int:
        result = 0
        for week, hints in week_month_hints.items():
            resolved_months = {value.month for value in _week_dates(base, week)}
            for month, _, priority in hints:
                if month in resolved_months:
                    result += priority
        return result

    source = "workspace"
    base_monday = configured_monday
    if policy != "workspace" and candidate_bases:
        base_monday = max(
            candidate_bases,
            key=lambda base: (
                exact_score(base),
                month_score(base),
                candidate_bases[base],
                -abs((base - configured_monday).days),
            ),
        )
        source = "source_dates"
    elif policy != "workspace" and week_month_hints:
        search_start = date(min(candidate_year_values) - 1, 1, 1)
        search_end = date(max(candidate_year_values) + 1, 12, 31)
        cursor = search_start - timedelta(days=search_start.weekday())
        candidates: List[date] = []
        while cursor <= search_end:
            candidates.append(cursor)
            cursor += timedelta(days=7)
        if candidates:
            base_monday = max(candidates, key=lambda base: (month_score(base), -abs((base - configured_monday).days)))
            source = "source_months"
    elif policy == "workspace":
        source = "workspace_override"
    elif has_source_evidence:
        add_issue(
            "warning",
            "source_calendar_incomplete",
            "Календарная шкала файла неполна; недостающие даты достроены от периода пространства.",
        )
    else:
        add_issue(
            "warning",
            "calendar_unverified",
            "В файлах нет пригодных дат и месяцев; использован период рабочего пространства.",
            action={"type": "edit_layout", "field": "date_row_offset", "label": "Указать строку дат"},
        )

    week_day_to_date: Dict[Tuple[int, str], date] = {}
    for week in weeks:
        for day_name, day_index in DAY_INDEX.items():
            week_day_to_date[(week, day_name)] = base_monday + timedelta(weeks=week - 1, days=day_index)

    for key, selected in selected_observations.items():
        resolved = week_day_to_date.get(key)
        if not resolved:
            continue
        month, day, explicit_year, label, _priority = selected
        if resolved.month == month and resolved.day == day and (not explicit_year or resolved.year == explicit_year):
            continue
        correction = {
            "type": "calendar_correction",
            "slot": f"{key[0]}:{key[1]}",
            "source": label,
            "source_value": {"month": MONTH_NAMES[month], "day": day, "year": explicit_year},
            "resolved_value": resolved.isoformat(),
            "reason": "Дата не согласуется с общей последовательностью недель.",
            "blocking": False,
        }
        corrections.append(correction)
        add_issue(
            "warning",
            "calendar_source_conflict",
            (
                f"Дата {day:02d}.{month:02d}{'.' + str(explicit_year) if explicit_year else ''} для недели "
                f"{key[0]}, {key[1]} заменена на {resolved.strftime('%d.%m.%Y')} по общей последовательности."
            ),
            action={"type": "edit_period", "slot": correction["slot"], "label": "Исправить дату вручную"},
        )

    for week, hints in week_month_hints.items():
        resolved_months = {value.month for value in _week_dates(base_monday, week)}
        if any(month in resolved_months for month, _, _ in hints):
            continue
        label_values = ", ".join(sorted({MONTH_NAMES[month] for month, _, _ in hints}))
        add_issue(
            "warning",
            "calendar_month_hint_ignored",
            f"Подпись месяца для недели {week} ({label_values}) не совпала с общей шкалой и оставлена как замечание.",
            action={"type": "edit_period", "week": week, "label": "Уточнить месяц недели"},
        )

    source_start = min(week_day_to_date.values())
    source_end = max(week_day_to_date.values())
    if source != "workspace_override" and (
        abs((base_monday - configured_monday).days) > 7
        or source_start < configured_start - timedelta(days=7)
        or source_end > configured_end + timedelta(days=7)
    ):
        add_issue(
            "warning",
            "workspace_dates_adjusted",
            (
                f"Фактический календарь файлов ({source_start.strftime('%d.%m.%Y')}–{source_end.strftime('%d.%m.%Y')}) "
                "отличается от пространства. Оба итоговых файла используют фактические даты."
            ),
            action={"type": "calendar_policy", "value": "workspace", "label": "Использовать даты пространства"},
        )

    resolved_months = [MONTH_NAMES[value.month] for value in week_day_to_date.values()]
    resolved_semester = semester_kind_from_months(resolved_months)
    effective_semester = (
        resolved_semester if resolved_semester in {"spring", "autumn"}
        else source_semester if source_semester in {"spring", "autumn"}
        else configured_semester if configured_semester in {"spring", "autumn"}
        else "unknown"
    )
    if not academic_year_text:
        academic_year_text = _academic_year_from_dates(week_day_to_date.values(), effective_semester)

    matched_weight = exact_score(base_monday)
    total_weight = sum(item[4] for item in selected_observations.values())
    confidence = 1.0 if not total_weight else round(matched_weight / total_weight, 3)
    if confidence < 0.75:
        add_issue(
            "warning",
            "calendar_low_confidence",
            f"Календарь восстановлен с уверенностью {round(confidence * 100)}%. Его можно скорректировать прямо в таблице дат.",
            resolution="review",
            action={"type": "edit_period", "label": "Открыть таблицу дат"},
        )

    warnings = [item["message"] for item in issues if item["severity"] == "warning"]
    report: Dict[str, Any] = {
        "kind": "period_resolution",
        "configured_start_date": configured_start.isoformat(),
        "configured_end_date": configured_end.isoformat(),
        "configured_semester": configured_semester,
        "source_semester": source_semester,
        "semester_kind": effective_semester,
        "academic_year": academic_year_text,
        "weeks": weeks,
        "source_files": [label for label, _ in usable_reports],
        "calendar_source": source,
        "calendar_policy": policy,
        "resolved_week_1_monday": base_monday.isoformat(),
        "resolved_start_date": source_start.isoformat(),
        "resolved_end_date": source_end.isoformat(),
        "months": list(dict.fromkeys(resolved_months)),
        "confidence": confidence,
        "issues": issues,
        "corrections": corrections,
        "operator_actions": [item["action"] for item in issues if item.get("action")],
        "warnings": warnings,
        "errors": [],
        "blocking": False,
    }
    return ResolvedScheduleCalendar(
        weeks=weeks,
        week_day_to_date=week_day_to_date,
        source=source,
        semester_kind=effective_semester,
        academic_year=academic_year_text,
        warnings=warnings,
        report=report,
    )
