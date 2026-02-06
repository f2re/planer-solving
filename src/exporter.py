import os
import pandas as pd
from datetime import datetime
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from typing import List, Dict, Any
from .model import ScheduleAssignment

class Exporter:
    def __init__(self, assignments: List[ScheduleAssignment], data: Dict[str, Any], config: Dict[str, Any], output_path: str):
        self.assignments = sorted(assignments, key=lambda x: (x.assignment_date, x.start_time, x.group_name))
        self.data = data
        self.config = config
        self.output_path = output_path

    def export(self):
        wb = Workbook()
        
        # Sheet 1: General Schedule
        self._create_general_schedule(wb.active)
        wb.active.title = "Общее расписание"
        
        # Sheet 2: Teachers
        self._create_teacher_schedule(wb.create_sheet("Расписание по преподавателям"))
        
        # Sheet 3: Groups
        self._create_group_schedule(wb.create_sheet("Расписание по группам"))
        
        # Sheet 4: Rooms
        self._create_room_usage(wb.create_sheet("Использование аудиторий"))
        
        # Sheet 5: Metadata
        self._create_metadata(wb.create_sheet("Метаданные и статистика"))
        
        wb.save(self.output_path)
        self._create_warnings_file()

    def _create_general_schedule(self, ws):
        headers = [
            "Неделя", "Дата", "День недели", "Время начала", "Время окончания", 
            "Пара №", "Дисциплина", "Тип занятия", "Тема", "Группа", 
            "Преподаватель", "Аудитория", "Корпус"
        ]
        ws.append(headers)
        
        # Styles
        header_fill = PatternFill(start_color="D9D9D9", end_color="D9D9D9", fill_type="solid")
        header_font = Font(bold=True)
        center_align = Alignment(horizontal="center")
        thin_border = Border(left=Side(style='thin'), right=Side(style='thin'), top=Side(style='thin'), bottom=Side(style='thin'))
        
        for col_num, header in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col_num)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = center_align
            cell.border = thin_border

        # Colors for lesson types
        type_colors = {
            "lecture": "FFF4CC", # Yellow
            "practice": "E2F0D9", # Green
            "lab": "DEEBF7" # Blue
        }

        for i, a in enumerate(self.assignments, 2):
            row_data = [
                a.week_number, a.assignment_date, a.day_of_week, 
                a.start_time.strftime("%H:%M"), a.end_time.strftime("%H:%M"),
                a.slot_number, a.discipline_name, a.lesson_type, a.topic,
                a.group_name, a.teacher_name, a.room_name, a.building
            ]
            ws.append(row_data)
            
            # Alternating row background
            bg_color = "E7F3FF" if i % 2 == 1 else "FFFFFF"
            row_fill = PatternFill(start_color=bg_color, end_color=bg_color, fill_type="solid")
            
            # Specific color for Lesson Type column (8)
            type_color = type_colors.get(a.lesson_type.lower(), bg_color)
            type_fill = PatternFill(start_color=type_color, end_color=type_color, fill_type="solid")

            for col_num in range(1, len(headers) + 1):
                cell = ws.cell(row=i, column=col_num)
                cell.border = thin_border
                if col_num == 8:
                    cell.fill = type_fill
                else:
                    cell.fill = row_fill

        # Auto-width
        for col in ws.columns:
            max_length = 0
            column = col[0].column_letter
            for cell in col:
                try:
                    if len(str(cell.value)) > max_length:
                        max_length = len(str(cell.value))
                except:
                    pass
            adjusted_width = (max_length + 2)
            ws.column_dimensions[column].width = adjusted_width

    def _create_teacher_schedule(self, ws):
        # Implementation for teacher blocks
        pass

    def _create_group_schedule(self, ws):
        # Implementation for group grid
        pass

    def _create_room_usage(self, ws):
        # Implementation for room stats
        pass

    def _create_metadata(self, ws):
        # Basic metadata
        ws.append(["Дата составления", datetime.now().strftime("%Y-%m-%d %H:%M:%S")])
        ws.append(["Solver", "Google OR-Tools CP-SAT"])
        ws.append(["Всего занятий запланировано", len(self.assignments)])

    def _create_warnings_file(self):
        warnings_path = os.path.join(os.path.dirname(self.output_path), "warnings.txt")
        with open(warnings_path, "w", encoding="utf-8") as f:
            f.write("=== ОТЧЕТ О СОСТАВЛЕНИИ РАСПИСАНИЯ ===\n")
            f.write(f"Дата: {datetime.now().isoformat()}\n\n")
            f.write("[ИНФОРМАЦИЯ]\n")
            f.write(f"- Всего запланировано занятий: {len(self.assignments)}\n")
