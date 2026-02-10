import openpyxl
from openpyxl.styles import Alignment, Border, Side, Font, PatternFill
from datetime import datetime, timedelta
import pandas as pd
import os
import json
from src.data_loader import DataLoader, Lesson
from typing import List, Dict, Any

def get_week_dates(start_date: datetime, week_num: int):
    # Find the Monday of the week containing start_date
    monday = start_date - timedelta(days=start_date.weekday())
    # Advance to the desired week
    target_monday = monday + timedelta(weeks=week_num - 1)
    
    dates = []
    for i in range(6): # Mon to Sat
        dates.append(target_monday + timedelta(days=i))
    return dates

def copy_cell(source_cell, target_cell):
    if source_cell.has_style:
        target_cell.font = copy_obj(source_cell.font)
        target_cell.border = copy_obj(source_cell.border)
        target_cell.fill = copy_obj(source_cell.fill)
        target_cell.number_format = source_cell.number_format
        target_cell.protection = copy_obj(source_cell.protection)
        target_cell.alignment = copy_obj(source_cell.alignment)
    target_cell.value = source_cell.value

def copy_obj(obj):
    from copy import copy
    return copy(obj)

def generate_weekly_semester_schedule(
    teachers_config: List[Dict], 
    lessons: List[Lesson], 
    template_path: str, 
    output_path: str,
    start_date_str: str,
    end_date_str: str
):
    start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
    end_date = datetime.strptime(end_date_str, "%Y-%m-%d")
    
    # Load template
    template_wb = openpyxl.load_workbook(template_path)
    template_ws = template_wb.active
    
    # Create new workbook
    output_wb = openpyxl.Workbook()
    # Remove default sheet
    output_wb.remove(output_wb.active)
    
    # Calculate weeks
    current_date = start_date - timedelta(days=start_date.weekday())
    weeks = []
    week_num = 1
    while current_date <= end_date:
        weeks.append(week_num)
        week_num += 1
        current_date += timedelta(weeks=1)

    # Group lessons by week, teacher, day, pair
    day_map = {'Пн': 0, 'Вт': 1, 'Ср': 2, 'Чт': 3, 'Пт': 4, 'Сб': 5}
    
    schedule_grid = {} # (week, teacher_short_name, day_idx, pair_num) -> data
    for l in lessons:
        key = (l.week, l.teacher, day_map.get(l.day_of_week, -1), l.pair_num)
        if key not in schedule_grid:
            schedule_grid[key] = []
        schedule_grid[key].append(l)

    for week_num in weeks:
        ws = output_wb.create_sheet(title=f"Неделя {week_num}")
        
        # Set column widths
        for c in range(1, 11):
            ws.column_dimensions[openpyxl.utils.get_column_letter(c)].width = template_ws.column_dimensions[openpyxl.utils.get_column_letter(c)].width

        # Copy headers (rows 1 to 12)
        for r in range(1, 13):
            for c in range(1, 11):
                copy_cell(template_ws.cell(row=r, column=c), ws.cell(row=r, column=c))
            if r in template_ws.row_dimensions:
                ws.row_dimensions[r].height = template_ws.row_dimensions[r].height

        # Update dates in header (Row 11)
        week_dates = get_week_dates(start_date, week_num)
        day_names_full = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота"]
        for i, dt in enumerate(week_dates):
            col = 5 + i
            date_str = dt.strftime("%d.%m")
            ws.cell(row=11, column=col).value = day_names_full[i] + "\n(" + date_str + ")"
            ws.cell(row=11, column=col).alignment = Alignment(wrapText=True, horizontal='center', vertical='center')

        # Fill teachers
        current_row = 13
        for idx, t_info in enumerate(teachers_config):
            teacher_short = t_info['short_name']
            
            for p_idx in range(1, 5):
                row = current_row + p_idx - 1
                
                # Apply styles from template row 14
                for c in range(1, 11):
                    copy_cell(template_ws.cell(row=14, column=c), ws.cell(row=row, column=c))
                    ws.cell(row=row, column=c).value = None # Clear value after copying style

                # Set values
                if p_idx == 1:
                    ws.cell(row=row, column=1).value = idx + 1
                    ws.cell(row=row, column=3).value = teacher_short
                
                pair_labels = {1: '1-2', 2: '3-4', 3: '5-6', 4: '7-8'}
                ws.cell(row=row, column=4).value = pair_labels[p_idx]
                
                for d_idx in range(6):
                    col = 5 + d_idx
                    lessons_at_slot = schedule_grid.get((week_num, teacher_short, d_idx, p_idx), [])
                    if lessons_at_slot:
                        cell_parts = []
                        for l in lessons_at_slot:
                            cell_parts.append(f"{l.subject}, {l.group}, {l.room}")
                        ws.cell(row=row, column=col).value = "\n".join(cell_parts)
                        ws.cell(row=row, column=col).alignment = Alignment(wrapText=True, horizontal='center', vertical='center')
                        ws.cell(row=row, column=col).font = Font(name='Arial', size=7)

            # Merge
            ws.merge_cells(start_row=current_row, start_column=1, end_row=current_row + 3, end_column=1)
            ws.merge_cells(start_row=current_row, start_column=3, end_row=current_row + 3, end_column=3)
            current_row += 4

    output_wb.save(output_path)

if __name__ == "__main__":
    with open('teachers.json', 'r', encoding='utf-8') as f:
        teachers = json.load(f)
    with open('config.json', 'r', encoding='utf-8') as f:
        config = json.load(f)
    loader = DataLoader('teachers.json')
    all_lessons = []
    obrazec_dir = 'obrazec'
    if os.path.exists(obrazec_dir):
        files = [f for f in os.listdir(obrazec_dir) if f.endswith('.xlsx') and not f.startswith('~') and not f.startswith('_') and f != 'Недельное.xlsx']
        for filename in files:
            path = os.path.join(obrazec_dir, filename)
            all_lessons.extend(loader.load_group_schedule(path))
    
    generate_weekly_semester_schedule(
        teachers_config=teachers,
        lessons=all_lessons,
        template_path='obrazec/Недельное.xlsx',
        output_path='output/weekly_schedule_semester.xlsx',
        start_date_str=config.get('schedule_start_date', '2026-02-10'),
        end_date_str=config.get('schedule_end_date', '2026-06-30')
    )
    print("Generated output/weekly_schedule_semester.xlsx")