import os
import collections
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

        type_colors = {
            "lecture": "FFF4CC", 
            "practice": "E2F0D9", 
            "lab": "DEEBF7" 
        }

        for i, a in enumerate(self.assignments, 2):
            row_data = [
                a.week_number, a.assignment_date, a.day_of_week, 
                a.start_time.strftime("%H:%M"), a.end_time.strftime("%H:%M"),
                a.slot_number, a.discipline_name, a.lesson_type, a.topic,
                a.group_name, a.teacher_name, a.room_name, a.building
            ]
            ws.append(row_data)
            
            bg_color = "F9F9F9" if i % 2 == 1 else "FFFFFF"
            row_fill = PatternFill(start_color=bg_color, end_color=bg_color, fill_type="solid")
            
            type_color = type_colors.get(a.lesson_type.lower(), bg_color)
            type_fill = PatternFill(start_color=type_color, end_color=type_color, fill_type="solid")

            for col_num in range(1, len(headers) + 1):
                cell = ws.cell(row=i, column=col_num)
                cell.border = thin_border
                cell.fill = type_fill if col_num == 8 else row_fill

        for col in ws.columns:
            max_length = 0
            for cell in col:
                try:
                    if cell.value:
                        max_length = max(max_length, len(str(cell.value)))
                except: pass
            ws.column_dimensions[col[0].column_letter].width = max_length + 2

    def _create_teacher_schedule(self, ws):
        teacher_map = collections.defaultdict(list)
        for a in self.assignments:
            teacher_map[a.teacher_name].append(a)
            
        row_idx = 1
        headers = ["Дата", "День", "Время", "Дисциплина", "Группа", "Аудитория"]
        
        header_fill = PatternFill(start_color="D9D9D9", end_color="D9D9D9", fill_type="solid")
        teacher_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
        teacher_font = Font(bold=True, color="FFFFFF")
        thin_border = Border(left=Side(style='thin'), right=Side(style='thin'), top=Side(style='thin'), bottom=Side(style='thin'))

        for teacher_name in sorted(teacher_map.keys()):
            ws.merge_cells(start_row=row_idx, start_column=1, end_row=row_idx, end_column=len(headers))
            cell = ws.cell(row=row_idx, column=1, value=teacher_name)
            cell.fill = teacher_fill
            cell.font = teacher_font
            cell.alignment = Alignment(horizontal="center")
            row_idx += 1
            
            for col, h in enumerate(headers, 1):
                cell = ws.cell(row=row_idx, column=col, value=h)
                cell.fill = header_fill
                cell.font = Font(bold=True)
                cell.border = thin_border
            row_idx += 1
            
            for a in sorted(teacher_map[teacher_name], key=lambda x: (x.assignment_date, x.start_time)):
                ws.append([
                    a.assignment_date, a.day_of_week, 
                    f"{a.start_time.strftime('%H:%M')}-{a.end_time.strftime('%H:%M')}",
                    a.discipline_name, a.group_name, f"{a.room_name} ({a.building})"
                ])
                for col in range(1, len(headers) + 1):
                    ws.cell(row=row_idx, column=col).border = thin_border
                row_idx += 1
            row_idx += 1 

    def _create_group_schedule(self, ws):
        groups = sorted(list(set(a.group_name for a in self.assignments)))
        time_points = self.data.get('valid_global_slots', [])
        
        if not time_points: return

        # Styles
        header_fill = PatternFill(start_color="D9D9D9", end_color="D9D9D9", fill_type="solid")
        gap_fill = PatternFill(start_color="CCCCCC", end_color="CCCCCC", fill_type="solid")
        thin_border = Border(left=Side(style='thin'), right=Side(style='thin'), top=Side(style='thin'), bottom=Side(style='thin'))
        
        # Header
        ws.cell(row=1, column=1, value="Дата").fill = header_fill
        ws.cell(row=1, column=2, value="Пара").fill = header_fill
        for col, group in enumerate(groups, 3):
            cell = ws.cell(row=1, column=col, value=group)
            cell.font = Font(bold=True)
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center")
            
        sched_map = {}
        group_day_range = collections.defaultdict(lambda: (float('inf'), float('-inf')))
        for a in self.assignments:
            sched_map[(a.assignment_date, a.slot_number, a.group_name)] = a
            # Track first and last slot for gaps
            r = group_day_range[(a.assignment_date, a.group_name)]
            group_day_range[(a.assignment_date, a.group_name)] = (min(r[0], a.slot_number), max(r[1], a.slot_number))
            
        row_idx = 2
        for date_obj, slot_obj in time_points:
            ws.cell(row=row_idx, column=1, value=date_obj).border = thin_border
            ws.cell(row=row_idx, column=2, value=slot_obj.slot_number).border = thin_border
            
            for col_idx, group in enumerate(groups, 3):
                cell = ws.cell(row=row_idx, column=col_idx)
                cell.border = thin_border
                a = sched_map.get((date_obj, slot_obj.slot_number, group))
                if a:
                    cell.value = f"{a.discipline_name}\n{a.teacher_name}\n{a.room_name}"
                    cell.alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")
                else:
                    # Check if it's a gap
                    first, last = group_day_range.get((date_obj, group), (float('inf'), float('-inf')))
                    if first < slot_obj.slot_number < last:
                        cell.fill = gap_fill
            row_idx += 1
            
        # Set column widths
        ws.column_dimensions['A'].width = 12
        ws.column_dimensions['B'].width = 6
        for col_idx in range(3, len(groups) + 3):
            ws.column_dimensions[get_column_letter(col_idx)].width = 25

    def _create_room_usage(self, ws):
        headers = ["Аудитория", "Корпус", "Тип", "Вместимость", "Часов занято", "Процент загрузки"]
        ws.append(headers)
        
        # Styles
        header_fill = PatternFill(start_color="D9D9D9", end_color="D9D9D9", fill_type="solid")
        for col in range(1, len(headers) + 1):
            cell = ws.cell(row=1, column=col)
            cell.fill = header_fill
            cell.font = Font(bold=True)
            cell.alignment = Alignment(horizontal="center")

        total_slots = len(self.data.get('valid_global_slots', []))
        room_usage = collections.defaultdict(int)
        for a in self.assignments:
            room_usage[a.room_name] += 1
            
        row_idx = 2
        for room in sorted(self.data['rooms'], key=lambda x: x.room_name):
            used_slots = room_usage[room.room_name]
            load_pct = (used_slots / total_slots) * 100 if total_slots > 0 else 0
            
            # Color coding for load_pct
            if load_pct <= 50:
                color = "E2F0D9" # Green
            elif load_pct <= 80:
                color = "FFF4CC" # Yellow
            else:
                color = "F8CBAD" # Red/Orange
                
            fill = PatternFill(start_color=color, end_color=color, fill_type="solid")
            
            ws.append([
                room.room_name, room.building, room.room_type, room.capacity,
                used_slots * 1.5, f"{load_pct:.1f}%"
            ])
            
            ws.cell(row=row_idx, column=6).fill = fill
            row_idx += 1

        for col in ws.columns:
            ws.column_dimensions[col[0].column_letter].width = 15

    def _create_metadata(self, ws):
        ws.append(["Параметр", "Значение"])
        stats = self.config.get("stats", {})
        
        metadata = [
            ("Дата формирования", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            ("Период", f"{self.config.get('schedule_start_date')} - {self.config.get('schedule_end_date')}"),
            ("Всего назначено занятий", len(self.assignments)),
            ("Всего запрошено занятий", len(self.data.get('lessons', []))),
            ("Статус решения", stats.get("status", "Unknown")),
            ("Объективная функция", stats.get("objective_value", "N/A")),
            ("Время решения (сек)", f"{stats.get('solve_time', 0):.2f}"),
            ("Кол-во групп", len(set(a.group_name for a in self.assignments))),
            ("Кол-во преподавателей", len(set(a.teacher_name for a in self.assignments))),
            ("Кол-во аудиторий", len(set(a.room_name for a in self.assignments))),
        ]
        
        for k, v in metadata:
            ws.append([k, v])
            
        if stats.get("warnings"):
            ws.append([])
            ws.append(["Предупреждения"])
            for w in stats["warnings"]:
                ws.append([w])

    def _create_warnings_file(self):
        stats = self.config.get("stats", {})
        warnings_path = os.path.join(self.config['output_directory'], 'warnings.txt')
        with open(warnings_path, "w", encoding="utf-8") as f:
            f.write("=== ОТЧЕТ О СОСТАВЛЕНИИ РАСПИСАНИЯ ===\n")
            f.write(f"Дата: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            
            f.write("[ИНФОРМАЦИЯ]\n")
            f.write(f"- Статус решения: {stats.get('status', 'Unknown')}\n")
            f.write(f"- Всего запланировано занятий: {len(self.assignments)}\n")
            f.write(f"- Учтено временных слотов: {len(self.data.get('valid_global_slots', []))}\n")
            
            if stats.get("warnings"):
                f.write("\n[ПРЕДУПРЕЖДЕНИЯ]\n")
                for w in stats["warnings"]:
                    f.write(f"- {w}\n")