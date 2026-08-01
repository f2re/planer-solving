"""Excel schedule parser driven by an operator-confirmed layout."""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, Union

from openpyxl import load_workbook

from .schedule_analyzer import (
    LESSON_CODE_RE,
    MONTH_PREFIXES,
    ScheduleAnalyzer,
    ScheduleLayout,
    WorksheetMatrix,
    normalize_text,
    value_as_int,
)

logger = logging.getLogger(__name__)


@dataclass
class Lesson:
    group: str
    subject: str
    lesson_type_code: str
    room: str
    week: int
    day_of_week: str
    pair_num: int
    teacher: str
    date_day: int
    month: str
    semester_info: str = ""
    year_info: str = ""


class DataLoader:
    """Parses multiple files while retaining teacher occupancy and round-robin state."""

    def __init__(self, teachers_config_path: str):
        try:
            data = json.loads(Path(teachers_config_path).read_text(encoding="utf-8"))
            self.teachers_config = data if isinstance(data, list) else []
        except Exception as exc:
            logger.error("Cannot load teachers config %s: %s", teachers_config_path, exc)
            self.teachers_config = []
        self.occupancy: Dict[Tuple[int, str, int, str], str] = {}
        self.subject_counters: Dict[Tuple[str, str], int] = {}
        self.warnings: List[str] = []
        self.last_report: Dict[str, Any] = {}
        self.teachers_by_surname: Dict[str, List[Dict[str, Any]]] = {}
        self._index_teachers()

    def _index_teachers(self) -> None:
        for teacher in self.teachers_config:
            full = normalize_text(teacher.get("full_name"))
            short = normalize_text(teacher.get("short_name")) or full
            parts = (full or short).split()
            if not parts:
                continue
            surname = parts[0].lower().replace("ё", "е")
            patterns = []
            if len(parts) >= 3 and parts[1] and parts[2]:
                s, first, middle = re.escape(parts[0]), re.escape(parts[1][0]), re.escape(parts[2][0])
                patterns = [
                    re.compile(rf"{s}\s+{first}\.?\s*{middle}\.?", re.I),
                    re.compile(rf"{first}\.?\s*{middle}\.?\s+{s}", re.I),
                    re.compile(rf"{s}\s+{first}\.?{middle}\.?", re.I),
                ]
            self.teachers_by_surname.setdefault(surname, []).append({"short": short, "patterns": patterns})

    def _extract_teachers(self, value: Any) -> List[str]:
        text = normalize_text(value)
        searchable = text.lower().replace("ё", "е")
        found: List[str] = []
        for surname, variants in self.teachers_by_surname.items():
            if not re.search(rf"(?<![\w-]){re.escape(surname)}(?![\w-])", searchable, re.I):
                continue
            precise = [item["short"] for item in variants if any(pattern.search(text) for pattern in item["patterns"])]
            if precise:
                found.extend(precise)
            elif len(variants) == 1:
                found.append(variants[0]["short"])
        return list(dict.fromkeys(found))

    def _assign_teacher(self, week: int, day: str, pair: int, subject: str, lesson_type: str, candidates: Sequence[str]) -> str:
        teachers = list(dict.fromkeys(normalize_text(item) for item in candidates if normalize_text(item)))
        if not teachers:
            return "Unknown"
        for teacher in teachers:
            if self.occupancy.get((week, day, pair, teacher)) == subject:
                return teacher
        counter_key = (subject, lesson_type)
        start = self.subject_counters.get(counter_key, 0)
        for shift in range(len(teachers)):
            index = (start + shift) % len(teachers)
            teacher = teachers[index]
            key = (week, day, pair, teacher)
            if key not in self.occupancy:
                self.occupancy[key] = subject
                self.subject_counters[counter_key] = (index + 1) % len(teachers)
                return teacher
        teacher = teachers[start % len(teachers)]
        occupied = self.occupancy.get((week, day, pair, teacher), "другая дисциплина")
        self.subject_counters[counter_key] = (start + 1) % len(teachers)
        message = f"Конфликт: {teacher} уже занят на {occupied} (неделя {week}, {day}, {pair} пара); добавлено {subject} ({lesson_type})."
        self.warnings.append(message)
        return teacher

    @staticmethod
    def _subject_key(value: Any) -> str:
        return re.sub(r"[^0-9a-zа-я]+", "", normalize_text(value).lower().replace("ё", "е"))

    @staticmethod
    def _day_number(value: Any) -> int:
        if isinstance(value, (date, datetime)):
            return value.day
        match = re.search(r"(?<!\d)(\d{1,2})(?:[./-]\d{1,2})?", normalize_text(value))
        if match and 1 <= int(match.group(1)) <= 31:
            return int(match.group(1))
        number = value_as_int(value)
        return number if number is not None and 1 <= number <= 31 else 0

    _parse_day_of_month = _day_number

    @staticmethod
    def _month(value: Any, previous: str = "Unknown") -> str:
        if isinstance(value, (date, datetime)):
            return ["", "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"][value.month]
        text = normalize_text(value).lower()
        return next((name for prefix, name in MONTH_PREFIXES.items() if text.startswith(prefix)), previous)

    @staticmethod
    def _lesson_type(code: str) -> str:
        match = re.match(r"^(лр|л|п|с|у|зо|экз|зач|конс)", normalize_text(code), re.I)
        if not match:
            return "П"
        return {"ЗАЧ": "ЗО", "КОНС": "П"}.get(match.group(1).upper(), match.group(1).upper())

    def _metadata(self, matrix: WorksheetMatrix) -> Tuple[str, str]:
        semester = year = ""
        for row in range(1, min(matrix.worksheet.max_row, 12) + 1):
            for col in range(1, min(matrix.worksheet.max_column, 12) + 1):
                text = normalize_text(matrix.value(row, col))
                lower = text.lower()
                if "семестр" in lower and not semester:
                    semester = text
                if (("учебн" in lower and "год" in lower) or re.search(r"\b20\d{2}\s*[-/]\s*20\d{2}\b", lower)) and not year:
                    year = text
        return semester, year

    def _legend(self, matrix: WorksheetMatrix, layout: ScheduleLayout, report: Dict[str, Any]) -> Dict[str, Dict[str, List[str]]]:
        if layout.legend_start_row is None:
            report["warnings"].append("Не указан блок дисциплин и преподавателей; назначения будут искаться только в сетке.")
            return {}
        if layout.legend_code_col is None and layout.legend_subject_col is None:
            report["warnings"].append("В блоке дисциплин не задан ни код, ни наименование дисциплины.")
            return {}
        start = layout.legend_start_row + layout.legend_data_start_offset
        end = min(layout.legend_end_row or matrix.worksheet.max_row, matrix.worksheet.max_row)
        mapping: Dict[str, Dict[str, List[str]]] = {}
        blanks = 0
        for row in range(start, end + 1):
            code = normalize_text(matrix.value(row, layout.legend_code_col)) if layout.legend_code_col else ""
            subject = normalize_text(matrix.value(row, layout.legend_subject_col)) if layout.legend_subject_col else ""
            lecturer_text = normalize_text(matrix.value(row, layout.legend_lecturer_col)) if layout.legend_lecturer_col else ""
            other_text = normalize_text(matrix.value(row, layout.legend_other_col)) if layout.legend_other_col else ""
            if not any((code, subject, lecturer_text, other_text)):
                blanks += 1
                if blanks >= 3:
                    break
                continue
            blanks = 0
            lecturers, others = self._extract_teachers(lecturer_text), self._extract_teachers(other_text)
            if not lecturers and not others:
                entire = " ".join(normalize_text(matrix.value(row, col)) for col in range(1, matrix.worksheet.max_column + 1))
                lecturers = others = self._extract_teachers(entire)
            elif not lecturers:
                lecturers = list(others)
            elif not others:
                others = list(lecturers)
            entry = {"Л": lecturers, "П": others, "С": others, "У": others, "ЛР": others, "ЗО": others, "ЭКЗ": others}
            for key in (code, subject):
                normalized = self._subject_key(key)
                if normalized:
                    mapping[normalized] = entry
        report["legend_entries"] = len(mapping)
        if not mapping:
            report["warnings"].append("В заданном блоке дисциплин не найдено ни одной пригодной строки.")
        return mapping

    def _weeks(self, matrix: WorksheetMatrix, layout: ScheduleLayout, report: Dict[str, Any]) -> List[Tuple[int, int, int]]:
        result = []
        for header_col in range(layout.first_week_col, layout.last_week_col + 1, layout.week_col_step):
            week = value_as_int(matrix.value(layout.weeks_row, header_col))
            if week is None:
                report["empty_week_columns"].append(header_col)
                continue
            if not 1 <= week <= 60:
                report["warnings"].append(f"В столбце {header_col} найден недопустимый номер недели: {week}.")
                continue
            data_col = header_col + layout.week_data_col_offset
            if not 1 <= data_col <= matrix.worksheet.max_column:
                report["warnings"].append(f"Столбец данных недели {week} выходит за пределы листа.")
                continue
            result.append((week, header_col, data_col))
        if not result:
            report["errors"].append("В заданном диапазоне не найдено номеров учебных недель.")
        return result

    def _combined(self, value: Any) -> Tuple[str, str, str, List[str]]:
        raw = str(value or "").replace("\r", "\n")
        lines = [normalize_text(item) for item in raw.split("\n") if normalize_text(item)]
        code = subject = room = ""
        for line in lines:
            if not code and LESSON_CODE_RE.search(line):
                code = line
            elif not subject:
                subject = line
            elif not room and re.search(r"(?:ауд\.?|каб\.?|спорт|зал|\b\d{2,4}[а-яa-z]?\b)", line, re.I):
                room = line
        return code, subject, room, self._extract_teachers(raw)

    def load_group_schedule(self, file_path: str, group_name: Optional[str] = None, layout: Optional[Union[ScheduleLayout, Dict[str, Any]]] = None) -> List[Lesson]:
        path = Path(file_path)
        group_name = normalize_text(group_name) or path.stem
        report: Dict[str, Any] = {
            "file": path.name, "group": group_name, "lesson_count": 0, "mapped_lessons": 0,
            "unknown_teacher_lessons": 0, "unknown_subjects": [], "legend_entries": 0,
            "empty_week_columns": [], "warnings": [], "errors": [], "samples": [],
        }
        self.last_report = report
        try:
            workbook = load_workbook(path, data_only=True, read_only=False)
        except Exception as exc:
            report["errors"].append(f"Не удалось открыть Excel-файл: {exc}")
            return []
        if layout is None:
            analysis = ScheduleAnalyzer().analyze(str(path))
            selected = analysis.layout
            report["warnings"].extend(item.message for item in analysis.diagnostics if item.severity != "info")
        else:
            selected = layout if isinstance(layout, ScheduleLayout) else ScheduleLayout.from_dict(layout)
        if selected.sheet_name not in workbook.sheetnames:
            report["errors"].append(f"Лист «{selected.sheet_name}» отсутствует в книге.")
            return []
        sheet = workbook[selected.sheet_name]
        matrix = WorksheetMatrix(sheet)
        validation = selected.validate(sheet)
        report["warnings"].extend(item.message for item in validation if item.severity == "warning")
        report["errors"].extend(item.message for item in validation if item.severity == "error")
        if report["errors"]:
            return []
        semester, year = self._metadata(matrix)
        legend = self._legend(matrix, selected, report)
        weeks = self._weeks(matrix, selected, report)
        if not weeks:
            return []
        months, current_month = {}, "Unknown"
        for _, header_col, data_col in weeks:
            if selected.months_row:
                current_month = self._month(matrix.value(selected.months_row, header_col), current_month)
            months[data_col] = current_month
        lessons: List[Lesson] = []
        unknown: Set[str] = set()
        grid_end = selected.grid_end_row or sheet.max_row
        for day_index, day_name in enumerate(selected.day_names):
            day_start = selected.grid_start_row + day_index * selected.day_block_rows
            if day_start > grid_end or day_start > sheet.max_row:
                break
            date_row = day_start + selected.date_row_offset
            for pair_index in range(selected.pairs_per_day):
                pair = pair_index + 1
                base = day_start + pair_index * selected.pair_row_stride
                if base > grid_end or base > sheet.max_row:
                    continue
                for week, _, data_col in weeks:
                    schedule_teachers: List[str] = []
                    if selected.cell_mode == "combined_cell":
                        code, subject, room, schedule_teachers = self._combined(matrix.value(base + selected.code_row_offset, data_col))
                    else:
                        code = normalize_text(matrix.value(base + selected.code_row_offset, data_col))
                        subject = normalize_text(matrix.value(base + selected.subject_row_offset, data_col))
                        room = normalize_text(matrix.value(base + selected.room_row_offset, data_col))
                        if selected.teacher_row_offset is not None:
                            schedule_teachers = self._extract_teachers(matrix.value(base + selected.teacher_row_offset, data_col))
                    if not code and not subject:
                        continue
                    if not subject:
                        parsed_code, parsed_subject, parsed_room, parsed_teachers = self._combined(code)
                        if parsed_subject:
                            code, subject, room = parsed_code, parsed_subject, room or parsed_room
                            schedule_teachers.extend(parsed_teachers)
                    if not subject:
                        report["warnings"].append(f"Неделя {week}, {day_name}, пара {pair}: есть код занятия, но не найдена дисциплина.")
                        continue
                    lesson_type = self._lesson_type(code)
                    legend_teachers = legend.get(self._subject_key(subject), {}).get(lesson_type, [])
                    if selected.teacher_source == "schedule":
                        candidates = schedule_teachers
                    elif selected.teacher_source == "both":
                        candidates = list(dict.fromkeys([*schedule_teachers, *legend_teachers]))
                    else:
                        candidates = legend_teachers
                    teacher = self._assign_teacher(week, day_name, pair, subject, lesson_type, candidates)
                    if teacher == "Unknown":
                        report["unknown_teacher_lessons"] += 1; unknown.add(subject)
                    else:
                        report["mapped_lessons"] += 1
                    lesson = Lesson(
                        group_name, subject, code, room, week, day_name, pair, teacher,
                        self._day_number(matrix.value(date_row, data_col)) if 1 <= date_row <= sheet.max_row else 0,
                        months.get(data_col, "Unknown"), semester, year,
                    )
                    lessons.append(lesson)
                    if len(report["samples"]) < 12:
                        report["samples"].append(asdict(lesson))
        report["lesson_count"] = len(lessons)
        report["unknown_subjects"] = sorted(unknown)
        if not lessons:
            report["errors"].append("По заданной разметке не найдено ни одного занятия.")
        elif report["unknown_teacher_lessons"]:
            report["warnings"].append(f"Для {report['unknown_teacher_lessons']} занятий не удалось определить преподавателя.")
        return lessons
