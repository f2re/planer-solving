from typing import List, Dict, Tuple, Any
from dataclasses import asdict
from .data_loader import Lesson

def transform_to_teacher_grid(lessons: List[Lesson], teachers_config: List[Dict]) -> Dict[str, Any]:
    # 1. Generalize dates: Map (week, day_of_week) to (month, day)
    week_day_to_date = {}
    for l in lessons:
        if l.date_day > 0 and l.month != "Unknown":
            key = (l.week, l.day_of_week)
            if key not in week_day_to_date:
                week_day_to_date[key] = (l.month, l.date_day)
    
    # Fill in missing dates in lessons
    for l in lessons:
        if (l.date_day == 0 or l.month == "Unknown"):
            key = (l.week, l.day_of_week)
            if key in week_day_to_date:
                l.month, l.date_day = week_day_to_date[key]

    # 2. Identify all unique dates and weeks
    dates = set()
    weeks = set()
    for l in lessons:
        if l.date_day > 0:
            dates.add((l.month, l.date_day))
        weeks.add(l.week)
    
    sorted_weeks = sorted(list(weeks))
    
    # Mapping weeks to their month (using the date of the first day available in that week)
    # This helps in the vertical layout to group weeks under months
    week_to_month = {}
    for w in sorted_weeks:
        # Check days in order Пн, Вт...
        for d_name in ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб']:
            if (w, d_name) in week_day_to_date:
                week_to_month[w] = week_day_to_date[(w, d_name)][0]
                break
        if w not in week_to_month:
            week_to_month[w] = "Unknown"

    month_order = {
        'Сентябрь': 9, 'Октябрь': 10, 'Ноябрь': 11, 'Декабрь': 12, 
        'Январь': 1, 'Февраль': 2, 'Март': 3, 'Апрель': 4, 'Май': 5, 'Июнь': 6, 'Июль': 7, 'Август': 8
    }
    
    def date_key(m_d):
        m, d = m_d
        if not m: return (2, 0, d)
        m_str = str(m).strip().capitalize()
        order = month_order.get(m_str, 0)
        year_offset = 1 if 1 <= order < 9 else 0
        return (year_offset, order, d)
    
    sorted_dates = sorted(list(dates), key=date_key)
    
    # Extract metadata from the first available lesson
    semester_info = lessons[0].semester_info if lessons else ""
    year_info = lessons[0].year_info if lessons else ""

    # 3. Build the grid for summary
    grid_raw = {}
    # 4. Build the grid for teacher vertical layout (by week)
    # key: (teacher, week, day, pair)
    grid_vertical = {}
    
    for l in lessons:
        if l.teacher != 'Unknown':
            # Summary grid key
            s_key = (l.teacher, l.pair_num, l.month, l.date_day)
            if s_key not in grid_raw:
                grid_raw[s_key] = {'groups': [l.group], 'subjects': [l.subject], 'types': [l.lesson_type_code], 'rooms': [str(l.room)] if l.room else []}
            else:
                if l.group not in grid_raw[s_key]['groups']: grid_raw[s_key]['groups'].append(l.group)
                if l.subject not in grid_raw[s_key]['subjects']: grid_raw[s_key]['subjects'].append(l.subject)
                if l.lesson_type_code not in grid_raw[s_key]['types']: grid_raw[s_key]['types'].append(l.lesson_type_code)
                r_str = str(l.room) if l.room else ""
                if r_str and r_str not in grid_raw[s_key]['rooms']: grid_raw[s_key]['rooms'].append(r_str)
            
            # Vertical grid key
            v_key = (l.teacher, l.week, l.day_of_week, l.pair_num)
            if v_key not in grid_vertical:
                grid_vertical[v_key] = {'groups': [l.group], 'subject': l.subject, 'type': l.lesson_type_code, 'room': str(l.room)}
            else:
                # If same teacher has multiple groups at same time
                if l.group not in grid_vertical[v_key]['groups']:
                    grid_vertical[v_key]['groups'].append(l.group)

    # Flatten summary grid
    grid = {}
    for key, data in grid_raw.items():
        grid[key] = {
            'groups': data['groups'],
            'subject': " / ".join(data['subjects']),
            'type': " / ".join(data['types']),
            'room': " / ".join(data['rooms'])
        }
            
    return {
        'grid': grid,
        'grid_vertical': grid_vertical,
        'dates': sorted_dates,
        'weeks': sorted_weeks,
        'week_to_month': week_to_month,
        'week_day_to_date': week_day_to_date,
        'teachers': [t['short_name'] for t in teachers_config],
        'semester_info': semester_info,
        'year_info': year_info
    }
            
    return {
        'lessons': lessons,
        'grid': grid,
        'dates': sorted_dates,
        'teachers': [t['short_name'] for t in teachers_config],
        'semester_info': semester_info,
        'year_info': year_info
    }