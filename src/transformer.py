from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List

from .data_loader import Lesson

MONTH_NAMES = {
    1: 'Январь', 2: 'Февраль', 3: 'Март', 4: 'Апрель', 5: 'Май', 6: 'Июнь',
    7: 'Июль', 8: 'Август', 9: 'Сентябрь', 10: 'Октябрь', 11: 'Ноябрь', 12: 'Декабрь'
}
DAY_MAP = {'Пн': 0, 'Вт': 1, 'Ср': 2, 'Чт': 3, 'Пт': 4, 'Сб': 5}
REVERSE_DAY_MAP = {value: key for key, value in DAY_MAP.items()}


def transform_to_teacher_grid(
    lessons: List[Lesson],
    teachers_config: List[Dict],
    start_date_str: str = '2026-02-10',
    end_date_str: str = '2026-06-30'
) -> Dict[str, Any]:
    try:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d')
    except (TypeError, ValueError):
        start_date = datetime.now().replace(month=2, day=1, hour=0, minute=0, second=0, microsecond=0)
        end_date = start_date.replace(month=6, day=30)

    monday = start_date - timedelta(days=start_date.weekday())
    has_week_zero = any(getattr(item, "week", None) == 0 for item in lessons)
    minimum_week = 0 if has_week_zero else 1

    generated_dates = []
    week_day_to_full_date = {}
    week_to_month = {}
    weeks_set = set()

    current_week = minimum_week
    current_monday = monday + timedelta(weeks=minimum_week - 1)
    # Week 0 is a real value in several supplied schedules and represents the
    # Monday immediately before configured week 1. Positive weeks outside the
    # configured semester remain ignored, preserving the previous behaviour.
    while current_monday <= end_date:
        weeks_set.add(current_week)
        for day_index in range(6):
            dt = current_monday + timedelta(days=day_index)
            month_name = MONTH_NAMES[dt.month]
            day_num = dt.day
            day_short = REVERSE_DAY_MAP[day_index]
            generated_dates.append((month_name, day_num, current_week))
            week_day_to_full_date[(current_week, day_short)] = (month_name, day_num)
            week_to_month.setdefault(current_week, month_name)
        current_monday += timedelta(weeks=1)
        current_week += 1

    grid_raw = {}
    grid_vertical = {}
    for lesson in lessons:
        if str(lesson.teacher).strip().casefold() in {'', 'unknown', 'none'}:
            continue
        month_day = week_day_to_full_date.get((lesson.week, lesson.day_of_week))
        if not month_day:
            continue
        month, day = month_day
        summary_key = (lesson.teacher, lesson.pair_num, month, day)
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

        vertical_key = (lesson.teacher, lesson.week, lesson.day_of_week, lesson.pair_num)
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
    return {
        'grid': grid,
        'grid_vertical': grid_vertical,
        'dates': generated_dates,
        'weeks': sorted(weeks_set),
        'week_to_month': week_to_month,
        'week_day_to_date': week_day_to_full_date,
        'teachers': [teacher['short_name'] for teacher in teachers_config],
        'semester_info': semester_info,
        'year_info': year_info,
    }
