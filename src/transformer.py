from typing import List, Dict, Tuple, Any
from dataclasses import asdict
from datetime import datetime, timedelta
from .data_loader import Lesson

def transform_to_teacher_grid(
    lessons: List[Lesson], 
    teachers_config: List[Dict],
    start_date_str: str = '2026-02-10',
    end_date_str: str = '2026-06-30'
) -> Dict[str, Any]:
    # 1. Parse dates and generate the full date range
    try:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d')
    except Exception:
        # Fallback if format is wrong
        start_date = datetime(2026, 2, 10)
        end_date = datetime(2026, 6, 30)
    
    # Logic from weekly_exporter.py: Find Monday of the first week
    monday = start_date - timedelta(days=start_date.weekday())
    
    month_names = {
        1: 'Январь', 2: 'Февраль', 3: 'Март', 4: 'Апрель', 5: 'Май', 6: 'Июнь',
        7: 'Июль', 8: 'Август', 9: 'Сентябрь', 10: 'Октябрь', 11: 'Ноябрь', 12: 'Декабрь'
    }
    day_map = {'Пн': 0, 'Вт': 1, 'Ср': 2, 'Чт': 3, 'Пт': 4, 'Сб': 5}
    reverse_day_map = {v: k for k, v in day_map.items()}

    generated_dates = [] # List of (month_name, day_num, week_num)
    week_day_to_full_date = {} # (week_num, day_short_name) -> (month_name, day_num)
    week_to_month = {}
    weeks_set = set()

    current_monday = monday
    week_num = 1
    while current_monday <= end_date:
        weeks_set.add(week_num)
        for i in range(6): # Mon to Sat
            dt = current_monday + timedelta(days=i)
            # We include all days of the week if the week starts before end_date
            
            month_name = month_names[dt.month]
            day_num = dt.day
            day_short = reverse_day_map[i]
            
            generated_dates.append((month_name, day_num, week_num))
            week_day_to_full_date[(week_num, day_short)] = (month_name, day_num)
            
            if week_num not in week_to_month:
                week_to_month[week_num] = month_name
                
        current_monday += timedelta(weeks=1)
        week_num += 1

    sorted_weeks = sorted(list(weeks_set))
    
    # 2. Build grids
    grid_raw = {}
    grid_vertical = {}
    
    for l in lessons:
        if l.teacher != 'Unknown':
            # Find the correct date from our generated range
            m_d = week_day_to_full_date.get((l.week, l.day_of_week))
            if not m_d:
                continue # Lesson outside range or invalid week/day
            
            month, day = m_d
            
            # Summary grid key: (teacher, pair, month, day)
            s_key = (l.teacher, l.pair_num, month, day)
            if s_key not in grid_raw:
                grid_raw[s_key] = {'groups': [l.group], 'subjects': [l.subject], 'types': [l.lesson_type_code], 'rooms': [str(l.room)] if l.room else []}
            else:
                if l.group not in grid_raw[s_key]['groups']: grid_raw[s_key]['groups'].append(l.group)
                if l.subject not in grid_raw[s_key]['subjects']: grid_raw[s_key]['subjects'].append(l.subject)
                if l.lesson_type_code not in grid_raw[s_key]['types']: grid_raw[s_key]['types'].append(l.lesson_type_code)
                r_str = str(l.room) if l.room else ''
                if r_str and r_str not in grid_raw[s_key]['rooms']: grid_raw[s_key]['rooms'].append(r_str)

            # Vertical grid key: (teacher, week, day, pair)
            v_key = (l.teacher, l.week, l.day_of_week, l.pair_num)
            if v_key not in grid_vertical:
                grid_vertical[v_key] = {'groups': [l.group], 'subject': l.subject, 'type': l.lesson_type_code, 'room': str(l.room)}
            else:
                if l.group not in grid_vertical[v_key]['groups']:
                    grid_vertical[v_key]['groups'].append(l.group)

    # Flatten summary grid
    grid = {}
    for key, data in grid_raw.items():
        grid[key] = {
            'groups': data['groups'],
            'subject': ' / '.join(data['subjects']),
            'type': ' / '.join(data['types']),
            'room': ' / '.join(data['rooms'])
        }

    semester_info = lessons[0].semester_info if lessons else ''
    year_info = lessons[0].year_info if lessons else ''

    return {
        'grid': grid,
        'grid_vertical': grid_vertical,
        'dates': generated_dates,
        'weeks': sorted_weeks,
        'week_to_month': week_to_month,
        'week_day_to_date': week_day_to_full_date,
        'teachers': [t['short_name'] for t in teachers_config],
        'semester_info': semester_info,
        'year_info': year_info
    }
