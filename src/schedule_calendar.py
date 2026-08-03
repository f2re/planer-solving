"""Resolve one verified calendar shared by all schedule exporters."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .schedule_period_values import (
    DAY_INDEX, DAY_NAMES, MONTH_NAMES, SEMESTER_LABELS,
    _parse_slot_key, academic_year_from_text, canonical_month,
    month_number, semester_kind_from_months,
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
    for _ in range(24):
        months.append(cursor.month)
        if cursor == limit:
            break
        cursor = date(cursor.year + (1 if cursor.month == 12 else 0), 1 if cursor.month == 12 else cursor.month + 1, 1)
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


def resolve_schedule_calendar(
    lessons: Sequence[Any],
    *,
    start_date_str: Any,
    end_date_str: Any,
    period_reports: Optional[Sequence[Mapping[str, Any]]] = None,
) -> ResolvedScheduleCalendar:
    """Resolve one checked calendar shared by summary and weekly exporters."""

    today = date.today()
    fallback_start = date(today.year, 2, 1)
    fallback_end = date(today.year, 6, 30)
    configured_start = _parse_configured_date(start_date_str, fallback_start)
    configured_end = _parse_configured_date(end_date_str, fallback_end)
    if configured_end < configured_start:
        raise SchedulePeriodError(["Дата окончания периода расположена раньше даты начала."])
    configured_monday = configured_start - timedelta(days=configured_start.weekday())

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

    errors: List[str] = []
    warnings: List[str] = []
    structured_issues: List[Dict[str, str]] = []

    def add_error(code: str, message: str) -> None:
        if message not in errors:
            errors.append(message)
            structured_issues.append({"severity": "error", "code": code, "message": message})

    def add_warning(code: str, message: str) -> None:
        if message not in warnings:
            warnings.append(message)
            structured_issues.append({"severity": "warning", "code": code, "message": message})

    for _, period in usable_reports:
        for item in period.get("issues") or []:
            severity = str(item.get("severity") or "warning")
            code = str(item.get("code") or "source_period_issue")
            message = str(item.get("message") or "").strip()
            if not message:
                continue
            if severity == "error":
                add_error(code, message)
            else:
                add_warning(code, message)

    for left_index, (left_label, left) in enumerate(usable_reports):
        for right_label, right in usable_reports[left_index + 1:]:
            for item in compare_file_periods(left, right, reference_label=left_label, current_label=right_label):
                if item["severity"] == "error":
                    add_error(item["code"], item["message"])
                else:
                    add_warning(item["code"], item["message"])

    weeks = sorted({
        int(week)
        for _, period in usable_reports
        for week in (period.get("week_numbers") or [])
    } | {int(getattr(item, "week")) for item in lessons})
    if not weeks:
        add_error("weeks_missing", "В разобранных данных нет учебных недель.")

    semester_values = {
        str(period.get("semester_kind"))
        for _, period in usable_reports
        if str(period.get("semester_kind")) in {"spring", "autumn"}
    }
    if len(semester_values) > 1:
        add_error("source_semester_mismatch", "Загруженные расписания относятся к разным семестрам.")
    source_semester = next(iter(semester_values), "unknown")

    academic_year_values = {
        str(period.get("academic_year"))
        for _, period in usable_reports
        if str(period.get("academic_year") or "")
    }
    if len(academic_year_values) > 1:
        add_error("source_academic_year_mismatch", "Загруженные расписания относятся к разным учебным годам.")
    academic_year_text = next(iter(academic_year_values), "")
    _, academic_year = academic_year_from_text(academic_year_text)

    configured_semester = _range_semester(configured_start, configured_end)
    if source_semester in {"spring", "autumn"} and configured_semester in {"spring", "autumn"} and source_semester != configured_semester:
        add_error(
            "workspace_semester_mismatch",
            (
                f"Период пространства ({configured_start.strftime('%d.%m.%Y')}–{configured_end.strftime('%d.%m.%Y')}) "
                f"относится к {SEMESTER_LABELS[configured_semester]} семестру, а исходные файлы — к "
                f"{SEMESTER_LABELS[source_semester]}. Формирование остановлено: исправьте даты пространства или загрузите нужный семестр."
            ),
        )

    configured_academic_year = ""
    if configured_semester == "spring":
        configured_academic_year = f"{configured_start.year - 1}/{configured_start.year}"
    elif configured_semester == "autumn":
        first_year = configured_start.year - 1 if configured_start.month == 1 else configured_start.year
        configured_academic_year = f"{first_year}/{first_year + 1}"
    if academic_year_text and configured_academic_year and academic_year_text != configured_academic_year:
        add_error(
            "workspace_academic_year_mismatch",
            (
                f"В настройках пространства выбран учебный год {configured_academic_year}, "
                f"а исходные файлы относятся к {academic_year_text}. Формирование остановлено."
            ),
        )

    observations: Dict[Tuple[int, str], Tuple[int, int, int, str]] = {}
    week_months: Dict[int, Tuple[int, str]] = {}
    for label, period in usable_reports:
        for raw_week, raw_month in (period.get("week_months") or {}).items():
            try:
                week = int(raw_week)
            except (TypeError, ValueError):
                continue
            number = month_number(raw_month)
            if number:
                previous = week_months.get(week)
                if previous and previous[0] != number:
                    add_error(
                        "source_week_month_mismatch",
                        f"Для недели {week} в исходных файлах указаны разные месяцы: {MONTH_NAMES[previous[0]]} и {MONTH_NAMES[number]}.",
                    )
                else:
                    week_months[week] = (number, label)
        for raw_key, item in (period.get("week_day_dates") or {}).items():
            parsed = _parse_slot_key(raw_key)
            if not parsed:
                continue
            month = month_number(item.get("month"))
            try:
                day = int(item.get("day") or 0)
                year = int(item.get("year") or 0)
            except (TypeError, ValueError):
                continue
            if not month or not 1 <= day <= 31:
                continue
            previous = observations.get(parsed)
            candidate = (month, day, year if year >= 1900 else 0, label)
            if previous and previous[:2] != candidate[:2]:
                add_error(
                    "source_date_mismatch",
                    (
                        f"Для недели {parsed[0]}, {parsed[1]} указаны разные даты: "
                        f"{previous[1]} {MONTH_NAMES[previous[0]].lower()} и {day} {MONTH_NAMES[month].lower()}."
                    ),
                )
            elif previous and previous[2] and candidate[2] and previous[2] != candidate[2]:
                add_error("source_date_year_mismatch", f"Для недели {parsed[0]}, {parsed[1]} указаны разные годы.")
            else:
                observations[parsed] = candidate if not previous or candidate[2] else previous

    # Lessons may provide dates even when an older report has no period block.
    for item in lessons:
        week = int(getattr(item, "week"))
        day_name = str(getattr(item, "day_of_week", ""))
        month = month_number(getattr(item, "month", ""))
        day = int(getattr(item, "date_day", 0) or 0)
        year = int(getattr(item, "date_year", 0) or 0)
        if day_name not in DAY_INDEX or not month or not 1 <= day <= 31:
            continue
        key = (week, day_name)
        previous = observations.get(key)
        candidate = (month, day, year if year >= 1900 else 0, str(getattr(item, "group", "")))
        if previous and previous[:2] != candidate[:2]:
            add_error(
                "source_date_mismatch",
                f"Для недели {week}, {day_name} занятия содержат разные даты.",
            )
        else:
            observations.setdefault(key, candidate)

    report: Dict[str, Any] = {
        "kind": "period_validation",
        "configured_start_date": configured_start.isoformat(),
        "configured_end_date": configured_end.isoformat(),
        "configured_semester": configured_semester,
        "source_semester": source_semester,
        "academic_year": academic_year_text,
        "weeks": weeks,
        "source_files": [label for label, _ in usable_reports],
        "issues": structured_issues,
    }
    if errors:
        report["errors"] = errors
        report["warnings"] = warnings
        raise SchedulePeriodError(errors, warnings=warnings, report=report)

    candidate_year_values = _candidate_years(configured_start, configured_end, academic_year)
    candidate_bases: Counter[date] = Counter()
    for (week, day_name), (month, day, explicit_year, _) in observations.items():
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
            base = monday - timedelta(weeks=week - 1)
            candidate_bases[base] += 1

    def exact_score(base: date) -> int:
        result = 0
        for (week, day_name), (month, day, explicit_year, _) in observations.items():
            value = base + timedelta(weeks=week - 1, days=DAY_INDEX[day_name])
            if value.month == month and value.day == day and (not explicit_year or value.year == explicit_year):
                result += 1
        return result

    def month_score(base: date) -> int:
        result = 0
        for week, (month, _) in week_months.items():
            if month in {value.month for value in _week_dates(base, week)}:
                result += 1
        return result

    source = "workspace"
    base_monday: Optional[date] = None
    if candidate_bases:
        ranked = sorted(
            candidate_bases,
            key=lambda base: (
                exact_score(base),
                month_score(base),
                candidate_bases[base],
                -abs((base - configured_monday).days),
            ),
            reverse=True,
        )
        base_monday = ranked[0]
        if exact_score(base_monday) != len(observations):
            add_error(
                "calendar_sequence_mismatch",
                "Даты в исходных расписаниях не образуют единый недельный календарь. Проверьте номера недель и строки дат.",
            )
        else:
            source = "source_dates"
    elif week_months:
        search_start = date(min(candidate_year_values) - 1, 1, 1)
        search_end = date(max(candidate_year_values) + 1, 12, 31)
        cursor = search_start - timedelta(days=search_start.weekday())
        candidates: List[date] = []
        while cursor <= search_end:
            candidates.append(cursor)
            cursor += timedelta(days=7)
        candidates.sort(key=lambda base: (month_score(base), -abs((base - configured_monday).days)), reverse=True)
        if candidates and month_score(candidates[0]) == len(week_months):
            base_monday = candidates[0]
            source = "source_months"
        else:
            add_error(
                "month_calendar_mismatch",
                "Строка месяцев не согласуется ни с одним календарём выбранного учебного года. Проверьте номера недель и месяцы.",
            )
    else:
        base_monday = configured_monday
        add_warning(
            "calendar_unverified",
            "В исходных файлах нет пригодных дат и месяцев; использован период рабочего пространства без проверки по Excel.",
        )

    if errors or base_monday is None:
        report["issues"] = structured_issues
        report["errors"] = errors or ["Не удалось определить начало календаря."]
        report["warnings"] = warnings
        raise SchedulePeriodError(report["errors"], warnings=warnings, report=report)

    for (week, day_name), (month, day, explicit_year, label) in observations.items():
        value = base_monday + timedelta(weeks=week - 1, days=DAY_INDEX[day_name])
        if value.month != month or value.day != day or (explicit_year and value.year != explicit_year):
            add_error(
                "calendar_source_conflict",
                f"Дата из файла «{label}» для недели {week}, {day_name} не совпадает с общим календарём.",
            )
            break
    for week, (month, label) in week_months.items():
        if month not in {value.month for value in _week_dates(base_monday, week)}:
            add_error(
                "calendar_month_conflict",
                f"Месяц недели {week} в файле «{label}» не совпадает с восстановленным календарём.",
            )
            break
    if errors:
        report["issues"] = structured_issues
        report["errors"] = errors
        report["warnings"] = warnings
        raise SchedulePeriodError(errors, warnings=warnings, report=report)

    week_day_to_date: Dict[Tuple[int, str], date] = {}
    for week in weeks:
        for day_name, day_index in DAY_INDEX.items():
            week_day_to_date[(week, day_name)] = base_monday + timedelta(weeks=week - 1, days=day_index)

    source_start = min(week_day_to_date.values())
    source_end = max(week_day_to_date.values())
    if source != "workspace" and (
        abs((base_monday - configured_monday).days) > 7
        or source_start < configured_start - timedelta(days=7)
        or source_end > configured_end + timedelta(days=7)
    ):
        add_warning(
            "workspace_dates_adjusted",
            (
                f"Точные даты исходных файлов ({source_start.strftime('%d.%m.%Y')}–{source_end.strftime('%d.%m.%Y')}) "
                f"не полностью совпадают с настройками пространства. В обоих итоговых файлах использован календарь Excel."
            ),
        )

    report.update({
        "calendar_source": source,
        "resolved_week_1_monday": base_monday.isoformat(),
        "resolved_start_date": source_start.isoformat(),
        "resolved_end_date": source_end.isoformat(),
        "months": list(dict.fromkeys(MONTH_NAMES[value.month] for value in week_day_to_date.values())),
        "issues": structured_issues,
        "errors": [],
        "warnings": warnings,
    })
    return ResolvedScheduleCalendar(
        weeks=weeks,
        week_day_to_date=week_day_to_date,
        source=source,
        semester_kind=source_semester if source_semester != "unknown" else configured_semester,
        academic_year=academic_year_text,
        warnings=warnings,
        report=report,
    )
