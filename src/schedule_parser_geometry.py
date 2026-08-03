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
        """Resolve week columns, scanning and repairing when hints are incomplete."""

        header_cols = [
            value for value in layout.resolved_week_columns()
            if 1 <= int(value) <= matrix.worksheet.max_column
        ]
        data_cols = layout.week_data_columns or [col + layout.week_data_col_offset for col in header_cols]
        generated_numbers = any(
            item.get("field") == "week_numbers" and not item.get("before")
            for item in report.get("auto_repairs", [])
        )
        explicit_numbers = [] if generated_numbers else list(layout.week_numbers or [])
        numbers = explicit_numbers or [value_as_int(matrix.value(layout.weeks_row, col)) for col in header_cols]
        result: List[Tuple[int, int, int]] = []

        def append_week(week: Any, header_col: int, data_col: int) -> None:
            parsed = value_as_int(week)
            if parsed is None:
                return
            minimum = 0 if layout.allow_week_zero else 1
            if not minimum <= parsed <= 60:
                return
            if not 1 <= data_col <= matrix.worksheet.max_column:
                return
            item = (int(parsed), int(header_col), int(data_col))
            if item not in result:
                result.append(item)

        for index, header_col in enumerate(header_cols):
            week = numbers[index] if index < len(numbers) else value_as_int(matrix.value(layout.weeks_row, header_col))
            data_col = data_cols[index] if index < len(data_cols) else header_col + layout.week_data_col_offset
            if week is None:
                report["empty_week_columns"].append(header_col)
                continue
            append_week(week, header_col, data_col)

        if not result and 1 <= layout.weeks_row <= matrix.worksheet.max_row:
            for header_col in range(1, matrix.worksheet.max_column + 1):
                week = value_as_int(matrix.value(layout.weeks_row, header_col))
                append_week(week, header_col, header_col + layout.week_data_col_offset)
            if result:
                report["warnings"].append(
                    "Столбцы недель найдены сканированием всей указанной строки и применены автоматически."
                )
                report.setdefault("auto_repairs", []).append({
                    "type": "layout_patch",
                    "field": "week_columns",
                    "after": [item[1] for item in result],
                    "reason": "Номера недель обнаружены в строке автоматически.",
                    "blocking": False,
                })

        if not result and header_cols:
            minimum = 0 if layout.allow_week_zero else 1
            for index, header_col in enumerate(header_cols):
                data_col = data_cols[index] if index < len(data_cols) else header_col + layout.week_data_col_offset
                append_week(minimum + index, header_col, data_col)
            if result:
                report["warnings"].append(
                    "Номера недель не прочитались из ячеек; временно использована последовательность по порядку столбцов."
                )
                report.setdefault("actions", []).append({
                    "type": "edit_layout",
                    "field": "week_numbers",
                    "selection_mode": "weeks",
                    "label": "Уточнить номера недель",
                    "blocking": False,
                })

        result.sort(key=lambda item: (item[0], item[1]))
        if not result:
            report["warnings"].append("Не удалось определить ни одного пригодного столбца недели.")
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
