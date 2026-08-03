from dataclasses import dataclass

import pytest

from src.schedule_period import (
    SchedulePeriodError,
    build_file_period_report,
    compare_file_periods,
    resolve_schedule_calendar,
)


@dataclass
class Lesson:
    group: str
    week: int
    day_of_week: str
    date_day: int
    month: str
    semester_info: str = ""
    year_info: str = ""
    date_year: int = 0


def test_file_report_rejects_semester_header_month_conflict():
    period, warnings, errors = build_file_period_report(
        week_numbers=[1, 2],
        week_months={1: "Сентябрь", 2: "Сентябрь"},
        week_day_dates={(1, "Пн"): {"month": "Сентябрь", "day": 7, "year": 2026}},
        semester_info="Весенний семестр",
        year_info="2025/2026 учебный год",
    )
    assert period["semester_declared"] == "spring"
    assert period["semester_by_months"] == "autumn"
    assert any("Заголовок" in item for item in errors)
    assert not warnings


def test_cross_file_comparison_detects_different_months_and_semesters():
    spring, _, _ = build_file_period_report(
        week_numbers=[1],
        week_months={1: "Февраль"},
        week_day_dates={(1, "Пн"): {"month": "Февраль", "day": 9, "year": 2026}},
        semester_info="Весенний семестр",
        year_info="2025/2026",
    )
    autumn, _, _ = build_file_period_report(
        week_numbers=[1],
        week_months={1: "Сентябрь"},
        week_day_dates={(1, "Пн"): {"month": "Сентябрь", "day": 7, "year": 2026}},
        semester_info="Осенний семестр",
        year_info="2026/2027",
    )
    issues = compare_file_periods(spring, autumn, reference_label="spring.xlsx", current_label="autumn.xlsx")
    codes = {item["code"] for item in issues}
    assert "source_semester_mismatch" in codes
    assert "source_academic_year_mismatch" in codes
    assert "source_week_month_mismatch" in codes


def test_february_source_cannot_silently_generate_august():
    lessons = [
        Lesson("101", 1, "Пн", 9, "Февраль", "Весенний семестр", "2025/2026", 2026),
        Lesson("101", 2, "Пн", 16, "Февраль", "Весенний семестр", "2025/2026", 2026),
    ]
    with pytest.raises(SchedulePeriodError) as caught:
        resolve_schedule_calendar(
            lessons,
            start_date_str="2026-08-03",
            end_date_str="2026-12-31",
        )
    assert any("Формирование остановлено" in item for item in caught.value.errors)
    assert caught.value.report["source_semester"] == "spring"


def test_source_dates_define_one_calendar_for_all_exports():
    lessons = [
        Lesson("101", 0, "Пн", 2, "Февраль", "Весенний семестр", "2025/2026", 2026),
        Lesson("101", 1, "Пн", 9, "Февраль", "Весенний семестр", "2025/2026", 2026),
        Lesson("101", 2, "Сб", 21, "Февраль", "Весенний семестр", "2025/2026", 2026),
    ]
    calendar = resolve_schedule_calendar(
        lessons,
        start_date_str="2026-02-01",
        end_date_str="2026-06-30",
    )
    assert calendar.weeks == [0, 1, 2]
    assert calendar.date_for(0, "Пн").isoformat() == "2026-02-02"
    assert calendar.date_for(1, "Пн").isoformat() == "2026-02-09"
    assert calendar.date_for(2, "Сб").isoformat() == "2026-02-21"
    assert calendar.summary_dates()[0] == ("Февраль", 2, 0)
    assert calendar.week_to_month == {0: "Февраль", 1: "Февраль", 2: "Февраль"}


def test_january_is_part_of_autumn_semester():
    period, warnings, errors = build_file_period_report(
        week_numbers=[17],
        week_months={17: "Январь"},
        week_day_dates={(17, "Пн"): {"month": "Январь", "day": 11, "year": 2027}},
        semester_info="Осенний семестр",
        year_info="2026/2027",
    )
    assert period["semester_kind"] == "autumn"
    assert not errors
    assert not warnings


def test_week_month_row_is_checked_against_explicit_dates():
    _, _, errors = build_file_period_report(
        week_numbers=[1],
        week_months={1: "Август"},
        week_day_dates={(1, "Пн"): {"month": "Февраль", "day": 9, "year": 2026}},
        semester_info="Весенний семестр",
        year_info="2025/2026",
    )
    assert any("строка месяцев" in item for item in errors)


def test_same_semester_but_wrong_academic_year_is_blocked():
    lessons = [
        Lesson("101", 1, "Пн", 9, "Февраль", "Весенний семестр", "2025/2026", 2026),
    ]
    with pytest.raises(SchedulePeriodError) as caught:
        resolve_schedule_calendar(
            lessons,
            start_date_str="2027-02-01",
            end_date_str="2027-06-30",
        )
    assert any("учебный год" in item for item in caught.value.errors)


def test_period_errors_from_file_reports_block_batch_generation():
    period, _, _ = build_file_period_report(
        week_numbers=[1],
        week_months={1: "Сентябрь"},
        week_day_dates={(1, "Пн"): {"month": "Сентябрь", "day": 7, "year": 2026}},
        semester_info="Весенний семестр",
        year_info="2025/2026",
    )
    report = {"file": "wrong.xlsx", "errors": ["period"], "period": period}
    with pytest.raises(SchedulePeriodError) as caught:
        resolve_schedule_calendar(
            [],
            start_date_str="2026-02-01",
            end_date_str="2026-06-30",
            period_reports=[report],
        )
    assert any("Заголовок" in item for item in caught.value.errors)
