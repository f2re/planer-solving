from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

from .data_loader import Lesson
from .schedule_period import MONTH_NAMES, ResolvedScheduleCalendar, resolve_schedule_calendar


UNASSIGNED_TEACHER = "Не назначен"


def _teacher_name(value: Any) -> str:
    text = str(value or "").strip()
    return UNASSIGNED_TEACHER if text.casefold() in {"", "unknown", "none"} else text


def transform_to_teacher_grid(
    lessons: List[Lesson],
    teachers_config: List[Dict],
    start_date_str: str = '2026-02-10',
    end_date_str: str = '2026-06-30',
    *,
    period_reports: Optional[Sequence[Mapping[str, Any]]] = None,
    resolved_calendar: Optional[ResolvedScheduleCalendar] = None,
) -> Dict[str, Any]:
    """Build both summary grids without discarding recoverable lessons."""

    calendar = resolved_calendar or resolve_schedule_calendar(
        lessons,
        start_date_str=start_date_str,
        end_date_str=end_date_str,
        period_reports=period_reports,
    )
    generated_dates = calendar.summary_dates()
    week_day_to_full_date = {
        (week, day_name): (MONTH_NAMES[value.month], value.day)
        for (week, day_name), value in calendar.week_day_to_date.items()
    }

    grid_raw = {}
    grid_vertical = {}
    unassigned_found = False
    for lesson in lessons:
        teacher = _teacher_name(lesson.teacher)
        if teacher == UNASSIGNED_TEACHER:
            unassigned_found = True
        month_day = week_day_to_full_date.get((lesson.week, lesson.day_of_week))
        if not month_day:
            continue
        month, day = month_day
        summary_key = (teacher, lesson.pair_num, month, day)
        bucket = grid_raw.setdefault(summary_key, {
            'groups': [], 'subjects': [], 'types': [], 'rooms': []
        })
        for key, value in (
            ('groups', lesson.group),
            ('subjects', lesson.subject),
            ('types', lesson.lesson_type_code),
            ('rooms', str(lesson.room) if lesson.room else ''),
        ):
            if value and value not in bucket[key]:
                bucket[key].append(value)

        vertical_key = (teacher, lesson.week, lesson.day_of_week, lesson.pair_num)
        vertical = grid_vertical.setdefault(vertical_key, {
            'groups': [], 'subject': lesson.subject,
            'type': lesson.lesson_type_code, 'room': str(lesson.room)
        })
        if lesson.group not in vertical['groups']:
            vertical['groups'].append(lesson.group)

    grid = {
        key: {
            'groups': value['groups'],
            'subject': ' / '.join(value['subjects']),
            'type': ' / '.join(value['types']),
            'room': ' / '.join(value['rooms']),
        }
        for key, value in grid_raw.items()
    }
    semester_info = lessons[0].semester_info if lessons else ''
    year_info = lessons[0].year_info if lessons else ''
    teacher_names = [teacher['short_name'] for teacher in teachers_config]
    if unassigned_found and UNASSIGNED_TEACHER not in teacher_names:
        teacher_names.append(UNASSIGNED_TEACHER)
    return {
        'grid': grid,
        'grid_vertical': grid_vertical,
        'dates': generated_dates,
        'weeks': list(calendar.weeks),
        'week_to_month': calendar.week_to_month,
        'week_day_to_date': week_day_to_full_date,
        'teachers': teacher_names,
        'semester_info': semester_info,
        'year_info': year_info,
        'period_report': calendar.report,
        'period_warnings': list(calendar.warnings),
        '_calendar': calendar,
    }
