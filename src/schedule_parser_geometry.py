"""Exact week, legend and combined-cell parser geometry."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

from .schedule_analyzer import LESSON_CODE_RE, ScheduleLayout, WorksheetMatrix, is_legend_record, normalize_text, value_as_int


class ScheduleParserGeometry:
    @staticmethod
    def _metadata(matrix: WorksheetMatrix) -> Tuple[str, str]:
        semester = year = ""
        for row in range(1, min(matrix.worksheet.max_row, 12) + 1):
            for col in range(1, min(matrix.worksheet.max_column, 14) + 1):
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
        start = layout.legend_data_start_row or (layout.legend_start_row + layout.legend_data_start_offset)
        end = min(layout.legend_end_row or matrix.worksheet.max_row, matrix.worksheet.max_row)
        mapping: Dict[str, Dict[str, List[str]]] = {}
        blanks = 0
        for row in range(start, end + 1):
            code = normalize_text(matrix.row_value(row, layout.legend_code_col)) if layout.legend_code_col else ""
            subject = normalize_text(matrix.row_value(row, layout.legend_subject_col)) if layout.legend_subject_col else ""
            lecturer_text = normalize_text(matrix.row_value(row, layout.legend_lecturer_col)) if layout.legend_lecturer_col else ""
            other_text = normalize_text(matrix.row_value(row, layout.legend_other_col)) if layout.legend_other_col else ""
            if not is_legend_record(code, subject, lecturer_text, other_text):
                blanks += 1
                if blanks >= 2:
                    break
                continue
            blanks = 0
            lecturers = self._extract_teachers(lecturer_text)
            others = self._extract_teachers(other_text)
            if layout.teacher_role_fallback == "any":
                if not lecturers and others:
                    lecturers = list(others)
                if not others and lecturers:
                    others = list(lecturers)
                if not lecturers and not others:
                    entire = " ".join(normalize_text(matrix.value(row, col)) for col in range(1, matrix.worksheet.max_column + 1))
                    lecturers = others = self._extract_teachers(entire)
            entry = {"lecturer": lecturers, "other": others}
            for key in (code, subject):
                normalized = self._subject_key(key)
                if normalized:
                    mapping[normalized] = entry
        report["legend_entries"] = len(mapping)
        if not mapping:
            report["warnings"].append("В заданном блоке дисциплин не найдено ни одной пригодной строки.")
        return mapping

    def _weeks(self, matrix: WorksheetMatrix, layout: ScheduleLayout, report: Dict[str, Any]) -> List[Tuple[int, int, int]]:
        header_cols = layout.resolved_week_columns()
        data_cols = layout.week_data_columns or [col + layout.week_data_col_offset for col in header_cols]
        numbers = layout.week_numbers or [value_as_int(matrix.value(layout.weeks_row, col)) for col in header_cols]
        result = []
        for index, header_col in enumerate(header_cols):
            week = numbers[index] if index < len(numbers) else value_as_int(matrix.value(layout.weeks_row, header_col))
            if week is None:
                report["empty_week_columns"].append(header_col)
                continue
            minimum = 0 if layout.allow_week_zero else 1
            if not minimum <= week <= 60:
                report["warnings"].append(f"В столбце {header_col} найден недопустимый номер недели: {week}.")
                continue
            data_col = data_cols[index] if index < len(data_cols) else header_col + layout.week_data_col_offset
            if not 1 <= data_col <= matrix.worksheet.max_column:
                report["warnings"].append(f"Столбец данных недели {week} выходит за пределы листа.")
                continue
            result.append((int(week), header_col, int(data_col)))
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
            elif not room and re.search(r"(?:ауд\.?|каб\.?|спорт|зал|плац|клуб|\b\d{2,4}(?:[-/][0-9а-яa-z]+)?\b)", line, re.I):
                room = line
        return code, subject, room, self._extract_teachers(raw)
