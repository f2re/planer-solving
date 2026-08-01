from src.schedule_analyzer import ScheduleLayout


def test_layout_rejects_reversed_ranges() -> None:
    layout = ScheduleLayout(
        sheet_name="Лист1",
        weeks_row=4,
        first_week_col=10,
        last_week_col=5,
        grid_start_row=20,
        grid_end_row=10,
    )
    diagnostics = layout.validate()
    codes = {item.code for item in diagnostics if item.severity == "error"}
    assert "invalid_week_range" in codes
    assert "invalid_grid_range" in codes
