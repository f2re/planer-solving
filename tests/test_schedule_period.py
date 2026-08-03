from dataclasses import dataclass

from src.schedule_period import (
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


def test_file_report_warns_but_keeps_header_month_conflict():
    period, warnings, errors = build_file_period_report(
        week_numbers=[1, 2],
        week_months={1: "Сентябрь", 2: "Сентябрь"},
        week_day_dates={(1, "Пн"): {"month": "Сентябрь", "day": 7, "year": 2026}},
        semester_info="Весенний семестр",
        year_info="2025/2026 учебный год",
    )
    assert period["semester_declared"] == "spring"
    assert period["semester_by_months"] == "autumn"
    assert any("Заголовок" in item for item in warnings)
    assert errors == []
    assert period["blocking"] is False


def test_cross_file_comparison_returns_editable_warnings():
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
    assert all(item["blocking"] is False for item in issues)
    assert all(item["severity"] != "error" for item in issues)


def test_february_source_generates_february_even_when_workspace_says_august():
    lessons = [
        Lesson("101", 1, "Пн", 9, "Февраль", "Весенний семестр", "2025/2026", 2026),
        Lesson("101", 2, "Пн", 16, "Февраль", "Весенний семестр", "2025/2026", 2026),
    ]
    calendar = resolve_schedule_calendar(
        lessons,
        start_date_str="2026-08-03",
        end_date_str="2026-12-31",
    )
    assert calendar.date_for(1, "Пн").isoformat() == "2026-02-09"
    assert calendar.source == "source_dates"
    assert any(item["code"] == "workspace_semester_mismatch" for item in calendar.report["issues"])
    assert calendar.report["errors"] == []


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


def test_week_month_row_is_advisory_when_explicit_dates_exist():
    period, warnings, errors = build_file_period_report(
        week_numbers=[1],
        week_months={1: "Август"},
        week_day_dates={(1, "Пн"): {"month": "Февраль", "day": 9, "year": 2026}},
        semester_info="Весенний семестр",
        year_info="2025/2026",
    )
    assert errors == []
    assert warnings
    assert period["week_day_dates"]["1:Пн"]["month"] == "Февраль"
    assert any(item.get("action") for item in period["issues"])


def test_same_semester_but_wrong_workspace_year_is_not_blocked():
    lessons = [
        Lesson("101", 1, "Пн", 9, "Февраль", "Весенний семестр", "2025/2026", 2026),
    ]
    calendar = resolve_schedule_calendar(
        lessons,
        start_date_str="2027-02-01",
        end_date_str="2027-06-30",
    )
    assert calendar.date_for(1, "Пн").isoformat() == "2026-02-09"
    assert calendar.report["blocking"] is False
    assert calendar.report["errors"] == []


def test_period_warnings_from_file_reports_do_not_block_batch_generation():
    period, _, _ = build_file_period_report(
        week_numbers=[1],
        week_months={1: "Сентябрь"},
        week_day_dates={(1, "Пн"): {"month": "Сентябрь", "day": 7, "year": 2026}},
        semester_info="Весенний семестр",
        year_info="2025/2026",
    )
    report = {"file": "wrong.xlsx", "warnings": ["period"], "period": period}
    calendar = resolve_schedule_calendar(
        [],
        start_date_str="2026-02-01",
        end_date_str="2026-06-30",
        period_reports=[report],
    )
    assert calendar.report["blocking"] is False
    assert calendar.report["errors"] == []
    assert calendar.weeks == [1]


def test_month_change_inside_week_is_normal_calendar_transition():
    period, warnings, errors = build_file_period_report(
        week_numbers=[1],
        week_months={1: "Февраль"},
        week_day_dates={
            (1, "Пн"): {"month": "Февраль", "day": 26, "year": 2024},
            (1, "Вт"): {"month": "Февраль", "day": 27, "year": 2024},
            (1, "Ср"): {"month": "Февраль", "day": 28, "year": 2024},
            (1, "Чт"): {"month": "Февраль", "day": 29, "year": 2024},
            (1, "Пт"): {"month": "Март", "day": 1, "year": 2024},
            (1, "Сб"): {"month": "Март", "day": 2, "year": 2024},
        },
        semester_info="Весенний семестр",
        year_info="2023/2024",
    )
    assert errors == []
    assert not any("не совпадает" in warning for warning in warnings)
    transition = next(item for item in period["issues"] if item["code"] == "week_month_transition")
    assert transition["severity"] == "info"
    assert transition["resolution"] == "auto"
    assert period["week_transitions"] == [{"week": 1, "months": ["Февраль", "Март"], "sequential": True}]


def test_adjacent_month_labels_for_same_week_are_not_a_conflict():
    february, _, _ = build_file_period_report(
        week_numbers=[1],
        week_months={1: "Февраль"},
        week_day_dates={(1, "Пт"): {"month": "Март", "day": 1, "year": 2024}},
        semester_info="Весенний семестр",
        year_info="2023/2024",
    )
    march, _, _ = build_file_period_report(
        week_numbers=[1],
        week_months={1: "Март"},
        week_day_dates={(1, "Пт"): {"month": "Март", "day": 1, "year": 2024}},
        semester_info="Весенний семестр",
        year_info="2023/2024",
    )
    issues = compare_file_periods(february, march, reference_label="a.xlsx", current_label="b.xlsx")
    boundary = [item for item in issues if item["code"] == "source_week_month_transition"]
    assert boundary
    assert boundary[0]["severity"] == "info"


def test_operator_override_has_priority():
    lessons = [Lesson("101", 1, "Пн", 9, "Февраль", "Весенний семестр", "2025/2026", 2026)]
    calendar = resolve_schedule_calendar(
        lessons,
        start_date_str="2026-02-01",
        end_date_str="2026-06-30",
        overrides={"week_day_dates": {"1:Пн": "2026-02-16"}},
    )
    assert calendar.date_for(1, "Пн").isoformat() == "2026-02-16"
