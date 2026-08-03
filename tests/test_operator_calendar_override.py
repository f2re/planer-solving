from dataclasses import dataclass

from src.schedule_period import resolve_schedule_calendar


@dataclass
class Lesson:
    group: str
    week: int
    day_of_week: str
    date_day: int
    month: str
    semester_info: str = "Весенний семестр"
    year_info: str = "2025/2026"
    date_year: int = 2026


def test_manual_cell_date_is_literal_even_when_many_source_dates_support_other_base():
    days = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб"]
    lessons = []
    for week in range(1, 9):
        monday_day = 2 + (week - 1) * 7
        for offset, day_name in enumerate(days):
            day_number = monday_day + offset
            month = "Февраль" if day_number <= 28 else "Март"
            if day_number > 28:
                day_number -= 28
            lessons.append(Lesson("101", week, day_name, day_number, month))

    calendar = resolve_schedule_calendar(
        lessons,
        start_date_str="2026-02-01",
        end_date_str="2026-04-30",
        overrides={"week_day_dates": {"1:Пн": "2026-02-16"}},
    )
    assert calendar.date_for(1, "Пн").isoformat() == "2026-02-16"
    assert calendar.source == "operator_dates"
    assert calendar.report["operator_override_count"] == 1
    assert any(item["type"] == "operator_date" for item in calendar.report["corrections"])
