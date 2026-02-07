from typing import List, Dict, Tuple, Any
from dataclasses import asdict
from .data_loader import Lesson

def transform_to_teacher_grid(lessons: List[Lesson], teachers_config: List[Dict]) -> Dict[str, Any]:
    # 1. Identify all unique dates and sort them
    dates = set()
    for l in lessons:
        if l.date_day > 0:
            dates.add((l.month, l.date_day))
    
    # Simple sort for dates: we should really have a better way, 
    # but for now let's assume they appear in order in the schedule or sort by month/day
    # Mapping months to order
    month_order = {
        'Сентябрь': 9, 'Октябрь': 10, 'Ноябрь': 11, 'Декабрь': 12, 
        'Январь': 1, 'Февраль': 2, 'Март': 3, 'Апрель': 4, 'Май': 5, 'Июнь': 6, 'Июль': 7, 'Август': 8
    }
    # Wait, Jan/Feb are in the next year if Sept is start.
    def date_key(m_d):
        m, d = m_d
        order = month_order.get(m, 0)
        year_offset = 1 if order < 8 else 0 # 2024 for Sept-Dec, 2025 for Jan-Jul
        return (year_offset, order, d)
    
    sorted_dates = sorted(list(dates), key=date_key)
    
    # Extract metadata from the first available lesson
    semester_info = lessons[0].semester_info if lessons else ""
    year_info = lessons[0].year_info if lessons else ""

    # 2. Build the grid
    # Structure: { (teacher_name, pair_num, month, day): {groups: [], subject: str, type: str, room: str} }
    grid = {}
    for l in lessons:
        if l.teacher != 'Unknown':
            key = (l.teacher, l.pair_num, l.month, l.date_day)
            if key not in grid:
                grid[key] = {
                    'groups': [l.group],
                    'subject': l.subject,
                    'type': l.lesson_type_code,
                    'room': l.room
                }
            else:
                if l.group not in grid[key]['groups']:
                    grid[key]['groups'].append(l.group)
                # Optionally check if subject/room match, but usually they should if it's a combined lecture
            
    return {
        'grid': grid,
        'dates': sorted_dates,
        'teachers': [t['short_name'] for t in teachers_config],
        'semester_info': semester_info,
        'year_info': year_info
    }
