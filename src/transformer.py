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
        if (l.date_day == 0 or l.month == "Unknown") and l.week in [w for w, d in week_day_to_date.keys() if d == l.day_of_week]:
            # This is slightly inefficient, let's use the direct key
            key = (l.week, l.day_of_week)
            if key in week_day_to_date:
                l.month, l.date_day = week_day_to_date[key]

    # 2. Identify all unique dates and sort them
    dates = set()
    for l in lessons:
        if l.date_day > 0:
            dates.add((l.month, l.date_day))
    
    # Mapping months to order
    month_order = {
        'Сентябрь': 9, 'Октябрь': 10, 'Ноябрь': 11, 'Декабрь': 12, 
        'Январь': 1, 'Февраль': 2, 'Март': 3, 'Апрель': 4, 'Май': 5, 'Июнь': 6, 'Июль': 7, 'Август': 8,
        '09': 9, '10': 10, '11': 11, '12': 12, '01': 1, '02': 2, '03': 3, '04': 4, '05': 5, '06': 6, '07': 7, '08': 8,
        '1': 1, '2': 2, '3': 3, '4': 4, '5': 5, '6': 6, '7': 7, '8': 8, '9': 9
    }
    
    def date_key(m_d):
        m, d = m_d
        if not m:
            return (2, 0, d)
            
        m_str = str(m).strip().lower()
        
        # Try to find month order
        order = 0
        for name, val in month_order.items():
            if m_str.startswith(name.lower()[:3]):
                order = val
                break
        
        if order == 0:
            # Fallback for numeric strings if any
            if m_str.isdigit():
                order = int(m_str)
            else:
                return (2, 0, d)
        
        # Determine year offset. Assume academic year starts in September (9)
        # Months 9-12 are year X, months 1-8 are year X+1
        if order < 9:
            year_offset = 1
        else:
            year_offset = 0 
            
        return (year_offset, order, d)
    
    sorted_dates = sorted(list(dates), key=date_key)
    
    # Extract metadata from the first available lesson
    semester_info = lessons[0].semester_info if lessons else ""
    year_info = lessons[0].year_info if lessons else ""

    # 2. Build the grid
    # Intermediate structure to handle conflicts (multiple subjects in same slot)
    grid_raw = {}
    for l in lessons:
        if l.teacher != 'Unknown':
            key = (l.teacher, l.pair_num, l.month, l.date_day)
            if key not in grid_raw:
                grid_raw[key] = {
                    'groups': [l.group],
                    'subjects': [l.subject],
                    'types': [l.lesson_type_code],
                    'rooms': [str(l.room)] if l.room else []
                }
            else:
                if l.group and l.group not in grid_raw[key]['groups']:
                    grid_raw[key]['groups'].append(l.group)
                if l.subject and l.subject not in grid_raw[key]['subjects']:
                    grid_raw[key]['subjects'].append(l.subject)
                if l.lesson_type_code and l.lesson_type_code not in grid_raw[key]['types']:
                    grid_raw[key]['types'].append(l.lesson_type_code)
                r_str = str(l.room) if l.room else ""
                if r_str and r_str not in grid_raw[key]['rooms']:
                    grid_raw[key]['rooms'].append(r_str)
            
    # Flatten intermediate structure for exporter
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
        'dates': sorted_dates,
        'teachers': [t['short_name'] for t in teachers_config],
        'semester_info': semester_info,
        'year_info': year_info
    }