from typing import List, Dict, Tuple, Any
from dataclasses import asdict
from .data_loader import Lesson

def transform_to_teacher_grid(lessons: List[Lesson], teachers_config: List[Dict]) -> Dict[str, Any]:
    # 1. Identify all unique dates and sort them
    dates = set()
    for l in lessons:
        if l.date_day > 0:
            dates.add((l.month, l.date_day))
    
    # Mapping months to order
    month_order = {
        'Сентябрь': 9, 'Октябрь': 10, 'Ноябрь': 11, 'Декабрь': 12, 
        'Январь': 1, 'Февраль': 2, 'Март': 3, 'Апрель': 4, 'Май': 5, 'Июнь': 6, 'Июль': 7, 'Август': 8
    }
    
    def date_key(m_d):
        m, d = m_d
        order = month_order.get(m, 0)
        year_offset = 1 if order < 8 else 0 
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