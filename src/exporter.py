import openpyxl
from openpyxl.styles import Alignment, Border, Side, Font, PatternFill
from typing import List, Dict, Tuple, Any

def _get_fills():
    return {
        'Л': PatternFill(start_color='FFFFE0', end_color='FFFFE0', fill_type='solid'),
        'П': PatternFill(start_color='E0FFFF', end_color='E0FFFF', fill_type='solid'),
        'С': PatternFill(start_color='E0FFFF', end_color='E0FFFF', fill_type='solid'),
        'ЛР': PatternFill(start_color='E0FFE0', end_color='E0FFE0', fill_type='solid'),
        'Экз': PatternFill(start_color='FFE0E0', end_color='FFE0E0', fill_type='solid'),
    }

def _apply_summary_header(ws, transformed_data, dates):
    header_font = Font(name='Times New Roman', size=8, bold=True)
    header_alignment = Alignment(horizontal='center', vertical='center')
    
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=5 + len(dates))
    
    semester_part = transformed_data.get('semester_info', 'На семестр')
    if "расписание учебных занятий" in semester_part.lower():
        semester_part = semester_part.lower().replace("расписание учебных занятий", "").strip().capitalize()
    
    if "на " not in semester_part.lower() and semester_part:
        semester_part = f"На {semester_part.lower()}"
    
    year_part = transformed_data.get('year_info', '')
    title_text = f"{semester_part} {year_part}".strip()
    
    title_cell = ws.cell(row=1, column=1, value=title_text)
    title_cell.font = header_font
    title_cell.alignment = Alignment(horizontal='left', vertical='center')

    cols = ['№ п/п', 'Должность', 'Звание', 'Фамилия, имя, отчество', 'Месяц']
    for i, col_name in enumerate(cols):
        cell = ws.cell(row=2, column=i+1, value=col_name)
        cell.font = header_font
        cell.alignment = header_alignment
        if col_name != 'Месяц':
             ws.merge_cells(start_row=2, start_column=i+1, end_row=4, end_column=i+1)

    ws.cell(row=3, column=5, value='№ недели').font = header_font
    ws.cell(row=3, column=5, value='№ недели').alignment = header_alignment
    ws.cell(row=4, column=5, value='№ часа').font = header_font
    ws.cell(row=4, column=5, value='№ часа').alignment = header_alignment
    
    ws.column_dimensions['A'].width = 8.57
    ws.column_dimensions['B'].width = 16.43
    ws.column_dimensions['C'].width = 15.86
    ws.column_dimensions['D'].width = 24.71
    ws.column_dimensions['E'].width = 5.71

    current_col = 6
    last_month = None
    month_start_col = 6
    for i, (month, day, week_num) in enumerate(dates):
        # Fill week number in row 3
        w_cell = ws.cell(row=3, column=current_col, value=week_num)
        w_cell.font = header_font
        w_cell.alignment = header_alignment

        # Fill day in row 4
        cell = ws.cell(row=4, column=current_col, value=day)
        cell.font = header_font
        cell.alignment = header_alignment
        ws.column_dimensions[openpyxl.utils.get_column_letter(current_col)].width = 13.0
        
        if month != last_month:
            if last_month is not None:
                ws.merge_cells(start_row=2, start_column=month_start_col, end_row=2, end_column=current_col-1)
                m_cell = ws.cell(row=2, column=month_start_col, value=last_month.upper())
                m_cell.font = header_font
                m_cell.alignment = header_alignment
            last_month = month
            month_start_col = current_col
        current_col += 1
        
    if last_month is not None:
        ws.merge_cells(start_row=2, start_column=month_start_col, end_row=2, end_column=current_col-1)
        m_cell = ws.cell(row=2, column=month_start_col, value=last_month.upper())
        m_cell.font = header_font
        m_cell.alignment = header_alignment

def _fill_summary_rows(ws, start_row, teachers_list, transformed_data):
    dates = transformed_data['dates']
    grid = transformed_data['grid']
    data_font = Font(name='Calibri', size=11)
    header_font = Font(name='Times New Roman', size=8, bold=True)
    header_alignment = Alignment(horizontal='center', vertical='center')
    thin_side = Side(style='thin')
    border = Border(left=thin_side, right=thin_side, top=thin_side, bottom=thin_side)
    fills = _get_fills()

    current_row = start_row
    for idx, t_info in enumerate(teachers_list):
        teacher_name = t_info['short_name']
        c1 = ws.cell(row=current_row, column=1, value=idx + 1)
        c2 = ws.cell(row=current_row, column=2, value=t_info.get('position', ''))
        c3 = ws.cell(row=current_row, column=3, value=t_info.get('rank', ''))
        c4 = ws.cell(row=current_row, column=4, value=t_info['full_name'])
        for c in [c1, c2, c3, c4]:
            c.font = data_font
            c.alignment = Alignment(horizontal='center', vertical='center', wrapText=True)
            ws.merge_cells(start_row=current_row, start_column=c.column, end_row=current_row + 3, end_column=c.column)

        for p in range(1, 5):
            pair_label = {1: '1-2', 2: '3-4', 3: '5-6', 4: '7-8'}[p]
            p_cell = ws.cell(row=current_row + p - 1, column=5, value=pair_label)
            p_cell.font = header_font
            p_cell.alignment = header_alignment
            for d_idx, (month, day, week_num) in enumerate(dates):
                item = grid.get((teacher_name, p, month, day))
                cell = ws.cell(row=current_row + p - 1, column=6 + d_idx)
                if item:
                    groups_str = ", ".join(item['groups'])
                    cell_val = f"{item['type']}\n{item['subject']}\n{item['room']}\n{groups_str}"
                    cell.value = cell_val
                    cell.alignment = Alignment(wrapText=True, horizontal='center', vertical='center', shrinkToFit=True)
                    cell.font = Font(size=8)
                    l_type = item['type'].split('/')[0] if '/' in item['type'] else item['type']
                    if l_type in fills: cell.fill = fills[l_type]
        current_row += 4
    for row in ws.iter_rows(min_row=2, max_row=current_row - 1, min_col=1, max_col=5 + len(dates)):
        for cell in row: cell.border = border

def _fill_teacher_vertical(ws, teacher_info, transformed_data):
    weeks = transformed_data['weeks']
    grid_v = transformed_data['grid_vertical']
    week_to_month = transformed_data['week_to_month']
    week_day_to_date = transformed_data['week_day_to_date']
    teacher_name = teacher_info['short_name']
    
    header_font = Font(name='Times New Roman', size=10, bold=True)
    header_alignment = Alignment(horizontal='center', vertical='center')
    thin_side = Side(style='thin')
    border = Border(left=thin_side, right=thin_side, top=thin_side, bottom=thin_side)
    fills = _get_fills()

    # Layout for teacher:
    # Row 1: Months
    # Row 2: Week Numbers
    # Then for each day: 
    #   Row Date
    #   Row Pair 1 (3 sub-rows)
    #   Row Pair 2 (3 sub-rows)
    #   ...
    
    ws.column_dimensions['A'].width = 15
    ws.column_dimensions['B'].width = 10
    ws.cell(row=1, column=1, value="Уч. недели").font = header_font
    ws.cell(row=2, column=1, value="Месяц").font = header_font
    
    # 1. Headers (Weeks and Months)
    last_month = None
    month_start_col = 3
    for i, w in enumerate(weeks):
        col = 3 + i
        ws.cell(row=1, column=col, value=w).font = header_font
        ws.cell(row=1, column=col, value=w).alignment = header_alignment
        ws.column_dimensions[openpyxl.utils.get_column_letter(col)].width = 15
        
        month = week_to_month.get(w, "Unknown")
        if month != last_month:
            if last_month is not None:
                ws.merge_cells(start_row=2, start_column=month_start_col, end_row=2, end_column=col-1)
                m_cell = ws.cell(row=2, column=month_start_col, value=last_month.upper())
                m_cell.font = header_font
                m_cell.alignment = header_alignment
            last_month = month
            month_start_col = col
    if last_month:
        ws.merge_cells(start_row=2, start_column=month_start_col, end_row=2, end_column=3 + len(weeks) - 1)
        ws.cell(row=2, column=month_start_col, value=last_month.upper()).font = header_font
        ws.cell(row=2, column=month_start_col, value=last_month.upper()).alignment = header_alignment

    # 2. Days and Lessons
    days = [('Пн', 'ПОНЕДЕЛЬНИК'), ('Вт', 'ВТОРНИК'), ('Ср', 'СРЕДА'), ('Чт', 'ЧЕТВЕРГ'), ('Пт', 'ПЯТНИЦА'), ('Сб', 'СУББОТА')]
    current_row = 3
    
    for d_short, d_full in days:
        # Date row
        ws.cell(row=current_row, column=1, value="Даты").font = header_font
        ws.cell(row=current_row, column=1).alignment = header_alignment
        for i, w in enumerate(weeks):
            m_d = week_day_to_date.get((w, d_short))
            if m_d:
                ws.cell(row=current_row, column=3+i, value=m_d[1]).font = header_font
                ws.cell(row=current_row, column=3+i, value=m_d[1]).alignment = header_alignment
        current_row += 1
        
        # Day row
        day_start_row = current_row
        day_cell = ws.cell(row=current_row, column=1, value=d_full)
        day_cell.font = header_font
        day_cell.alignment = Alignment(textRotation=90, vertical='center', horizontal='center')
        
        for p in range(1, 5):
            pair_label = {1: '1-2', 2: '3-4', 3: '5-6', 4: '7-8'}[p]
            time_label = {1: '9.00-10.35', 2: '10.55-12.30', 3: '12.50-14.25', 4: '15.25-17.00'}[p]
            
            p_label_cell = ws.cell(row=current_row, column=2, value=pair_label)
            p_label_cell.font = Font(size=8, bold=True)
            p_label_cell.alignment = header_alignment
            
            t_label_cell = ws.cell(row=current_row+1, column=2, value=time_label)
            t_label_cell.font = Font(size=7)
            t_label_cell.alignment = header_alignment
            
            ws.merge_cells(start_row=current_row, start_column=2, end_row=current_row+2, end_column=2)

            for i, w in enumerate(weeks):
                item = grid_v.get((teacher_name, w, d_short, p))
                if item:
                    # 3 sub-rows per lesson
                    c_type = ws.cell(row=current_row, column=3+i, value=item['type'])
                    c_subj = ws.cell(row=current_row+1, column=3+i, value=item['subject'])
                    groups_str = ", ".join(item['groups'])
                    room_str = f"{item['room']} ({groups_str})" if item['room'] else groups_str
                    c_room = ws.cell(row=current_row+2, column=3+i, value=room_str)
                    
                    for c in [c_type, c_subj, c_room]:
                        c.font = Font(size=8)
                        c.alignment = Alignment(wrapText=True, horizontal='center', vertical='center')
                    
                    l_type = item['type'].split('/')[0] if '/' in item['type'] else item['type']
                    if l_type in _get_fills():
                        for r_off in range(3):
                            ws.cell(row=current_row+r_off, column=3+i).fill = _get_fills()[l_type]
            
            current_row += 3
        
        ws.merge_cells(start_row=day_start_row, start_column=1, end_row=current_row-1, end_column=1)
    
    # Apply borders
    for r in range(1, current_row):
        for c in range(1, 3 + len(weeks)):
            ws.cell(row=r, column=c).border = border

def export_to_excel(transformed_data: Dict[str, Any], teachers_config: List[Dict], output_path: str):
    wb = openpyxl.Workbook()
    ws_summary = wb.active
    ws_summary.title = 'Сводное расписание'
    _apply_summary_header(ws_summary, transformed_data, transformed_data['dates'])
    _fill_summary_rows(ws_summary, 5, teachers_config, transformed_data)

    for t_info in teachers_config:
        parts = t_info['full_name'].split()
        if len(parts) >= 3: sheet_title = f"{parts[0]} {parts[1][0]}.{parts[2][0]}."
        elif len(parts) == 2: sheet_title = f"{parts[0]} {parts[1][0]}."
        else: sheet_title = parts[0]
        
        ws_teacher = wb.create_sheet(title=sheet_title[:31])
        _fill_teacher_vertical(ws_teacher, t_info, transformed_data)

    wb.save(output_path)
