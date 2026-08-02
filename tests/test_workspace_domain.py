from datetime import date

from src.workspace_domain import default_semester_settings


def test_default_semester_dates_follow_current_academic_half_year():
    assert default_semester_settings(date(2026, 3, 15)) == {
        "schedule_start_date": "2026-02-01",
        "schedule_end_date": "2026-06-30",
    }
    assert default_semester_settings(date(2026, 8, 2)) == {
        "schedule_start_date": "2026-09-01",
        "schedule_end_date": "2027-01-31",
    }
