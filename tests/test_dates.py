from datetime import datetime

from src.data_loader import DataLoader
from src.transformer import transform_to_teacher_grid


def test_day_parser_handles_common_excel_representations() -> None:
    assert DataLoader._parse_day_of_month("02.09") == 2
    assert DataLoader._parse_day_of_month("15") == 15
    assert DataLoader._parse_day_of_month(" 7 ") == 7
    assert DataLoader._parse_day_of_month(datetime(2026, 9, 5)) == 5
    assert DataLoader._parse_day_of_month("нет даты") == 0


def test_generated_calendar_crosses_month_boundary() -> None:
    result = transform_to_teacher_grid(
        [],
        [],
        start_date_str="2026-03-30",
        end_date_str="2026-04-04",
    )
    assert result["dates"][0] == ("Март", 30, 1)
    assert result["dates"][2] == ("Апрель", 1, 1)
    assert result["dates"][-1] == ("Апрель", 4, 1)
