"""Template-independent discovery and preview of Excel schedule layouts."""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
import math
import re
import statistics
from typing import Any, Dict, List, Optional, Sequence, Tuple

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

DAY_NAMES = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб"]
MONTH_PREFIXES = {
    "янв": "Январь", "фев": "Февраль", "мар": "Март", "апр": "Апрель",
    "май": "Май", "июн": "Июнь", "июл": "Июль", "авг": "Август",
    "сен": "Сентябрь", "окт": "Октябрь", "ноя": "Ноябрь", "дек": "Декабрь",
}
LESSON_CODE_RE = re.compile(
    r"^(?:лр|л|п|с|у|зо|экз|зач|конс)(?:\s*[/\\.\-]|\b)", re.IGNORECASE
)
DAY_PATTERNS = {
    "Пн": re.compile(r"^(?:пн|понедельник)\.?$", re.I),
    "Вт": re.compile(r"^(?:вт|вторник)\.?$", re.I),
    "Ср": re.compile(r"^(?:ср|среда)\.?$", re.I),
    "Чт": re.compile(r"^(?:чт|четверг)\.?$", re.I),
    "Пт": re.compile(r"^(?:пт|пятница)\.?$", re.I),
    "Сб": re.compile(r"^(?:сб|суббота)\.?$", re.I),
}


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).replace("\xa0", " ").replace("ё", "е").replace("Ё", "Е")).strip()


def value_as_int(value: Any) -> Optional[int]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        return int(value)
    text = normalize_text(value)
    if re.fullmatch(r"\d{1,2}(?:\.0+)?", text):
        return int(float(text))
    return None


def excel_display(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (date, datetime)):
        return value.strftime("%d.%m.%Y")
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return normalize_text(value)


@dataclass
class Diagnostic:
    severity: str
    code: str
    message: str
    row: Optional[int] = None
    column: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ScheduleLayout:
    """Operator-editable coordinates; all rows and columns are 1-based."""

    sheet_name: str = ""
    weeks_row: int = 1
    first_week_col: int = 1
    last_week_col: int = 1
    week_col_step: int = 1
    week_data_col_offset: int = 0
    months_row: Optional[int] = None
    grid_start_row: int = 1
    grid_end_row: Optional[int] = None
    day_block_rows: int = 13
    pairs_per_day: int = 4
    pair_row_stride: int = 3
    date_row_offset: int = -1
    code_row_offset: int = 0
    subject_row_offset: int = 1
    room_row_offset: int = 2
    teacher_row_offset: Optional[int] = None
    day_names: List[str] = field(default_factory=lambda: list(DAY_NAMES))
    legend_start_row: Optional[int] = None
    legend_end_row: Optional[int] = None
    legend_data_start_offset: int = 3
    legend_code_col: Optional[int] = 1
    legend_subject_col: Optional[int] = None
    legend_lecturer_col: Optional[int] = None
    legend_other_col: Optional[int] = None
    cell_mode: str = "row_layers"
    teacher_source: str = "legend"

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "ScheduleLayout":
        allowed = cls.__dataclass_fields__
        data = {key: value for key, value in raw.items() if key in allowed}
        data["day_names"] = data.get("day_names") or list(DAY_NAMES)
        return cls(**data)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def validate(self, worksheet: Optional[Worksheet] = None) -> List[Diagnostic]:
        result: List[Diagnostic] = []
        required = {
            "строка недель": self.weeks_row,
            "первый столбец недели": self.first_week_col,
            "последний столбец недели": self.last_week_col,
            "шаг столбцов недель": self.week_col_step,
            "начало сетки": self.grid_start_row,
            "высота блока дня": self.day_block_rows,
            "число пар": self.pairs_per_day,
            "шаг строки пары": self.pair_row_stride,
        }
        optional = {
            "строка месяцев": self.months_row,
            "конец сетки": self.grid_end_row,
            "начало легенды": self.legend_start_row,
            "конец легенды": self.legend_end_row,
            "столбец обозначения": self.legend_code_col,
            "столбец дисциплины": self.legend_subject_col,
            "столбец лектора": self.legend_lecturer_col,
            "столбец других преподавателей": self.legend_other_col,
        }
        for label, value in required.items():
            if not isinstance(value, int) or value < 1:
                result.append(Diagnostic("error", "invalid_coordinate", f"Поле «{label}» должно быть положительным целым числом."))
        for label, value in optional.items():
            if value is not None and (not isinstance(value, int) or value < 1):
                result.append(Diagnostic("error", "invalid_coordinate", f"Поле «{label}» должно быть положительным целым числом."))
        if self.first_week_col > self.last_week_col:
            result.append(Diagnostic("error", "invalid_week_range", "Первый столбец недель расположен правее последнего."))
        if self.grid_end_row and self.grid_start_row > self.grid_end_row:
            result.append(Diagnostic("error", "invalid_grid_range", "Начало сетки расположено ниже её конца."))
        if self.legend_start_row and self.legend_end_row and self.legend_start_row > self.legend_end_row:
            result.append(Diagnostic("error", "invalid_legend_range", "Начало блока дисциплин расположено ниже его конца."))
        if self.cell_mode not in {"row_layers", "combined_cell"}:
            result.append(Diagnostic("error", "invalid_cell_mode", "Неизвестный режим расположения занятия в ячейках."))
        if self.teacher_source not in {"legend", "schedule", "both"}:
            result.append(Diagnostic("error", "invalid_teacher_source", "Неизвестный источник преподавателя."))
        if not self.day_names:
            result.append(Diagnostic("error", "missing_days", "Не задан список дней недели."))
        if worksheet:
            if self.weeks_row > worksheet.max_row or self.grid_start_row > worksheet.max_row:
                result.append(Diagnostic("error", "row_out_of_range", "Координаты расписания выходят за пределы листа."))
            if self.first_week_col > worksheet.max_column:
                result.append(Diagnostic("error", "column_out_of_range", "Первый столбец недель выходит за пределы листа."))
            if self.last_week_col > worksheet.max_column:
                result.append(Diagnostic("warning", "column_out_of_range", "Последний столбец недель правее фактической области листа."))
        return result


class WorksheetMatrix:
    """Merged-cell-aware access without mutating the workbook."""

    def __init__(self, worksheet: Worksheet):
        self.worksheet = worksheet
        self._anchors: Dict[Tuple[int, int], Tuple[int, int]] = {}
        for area in worksheet.merged_cells.ranges:
            anchor = (area.min_row, area.min_col)
            for row in range(area.min_row, area.max_row + 1):
                for col in range(area.min_col, area.max_col + 1):
                    self._anchors[(row, col)] = anchor

    def value(self, row: int, col: int) -> Any:
        anchor = self._anchors.get((row, col), (row, col))
        return self.worksheet.cell(*anchor).value

    def is_merged(self, row: int, col: int) -> bool:
        return (row, col) in self._anchors

    def merged_anchor(self, row: int, col: int) -> Tuple[int, int]:
        return self._anchors.get((row, col), (row, col))


@dataclass
class AnalysisResult:
    sheet_names: List[str]
    selected_sheet: str
    max_row: int
    max_column: int
    confidence: float
    layout: ScheduleLayout
    diagnostics: List[Diagnostic]
    schedule_preview: Dict[str, int]
    legend_preview: Dict[str, int]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sheet_names": self.sheet_names,
            "selected_sheet": self.selected_sheet,
            "max_row": self.max_row,
            "max_column": self.max_column,
            "confidence": round(self.confidence, 3),
            "layout": self.layout.to_dict(),
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "schedule_preview": self.schedule_preview,
            "legend_preview": self.legend_preview,
        }


class ScheduleAnalyzer:
    def _select_sheet(self, workbook: Any, preferred: Optional[str]) -> str:
        if preferred in workbook.sheetnames:
            return preferred
        scores = []
        for sheet in workbook.worksheets:
            keywords = weeks = nonempty = 0
            for row in sheet.iter_rows(max_row=min(sheet.max_row, 120), max_col=min(sheet.max_column, 80)):
                for cell in row:
                    text = normalize_text(cell.value).lower()
                    nonempty += bool(text)
                    keywords += any(token in text for token in ("недел", "дисцип", "лектор", "преподав", "обозн"))
                    number = value_as_int(cell.value)
                    weeks += number is not None and 1 <= number <= 60
            scores.append((keywords * 20 + weeks * 1.5 + math.log1p(nonempty), sheet.title))
        return max(scores)[1]

    @staticmethod
    def _longest_sequence(values: Sequence[Tuple[int, int]]) -> List[Tuple[int, int]]:
        best: List[Tuple[int, int]] = []
        current: List[Tuple[int, int]] = []
        for col, number in sorted(values):
            if current and not (col - current[-1][0] <= 4 and number in {current[-1][1], current[-1][1] + 1}):
                best = current if len(current) > len(best) else best
                current = []
            if current and number == current[-1][1] and len(current) >= 2 and current[-2][1] == number:
                continue
            current.append((col, number))
        return current if len(current) > len(best) else best

    def _detect_weeks(self, matrix: WorksheetMatrix) -> Tuple[Optional[int], List[int], float]:
        sheet = matrix.worksheet
        best = (0.0, None, [])
        for row in range(1, min(sheet.max_row, 100) + 1):
            values, bonus = [], 0
            for col in range(1, sheet.max_column + 1):
                raw = matrix.value(row, col)
                bonus = 18 if "недел" in normalize_text(raw).lower() else bonus
                number = value_as_int(raw)
                if number is not None and 1 <= number <= 60:
                    values.append((col, number))
            sequence = self._longest_sequence(values)
            if sequence:
                span = sequence[-1][0] - sequence[0][0] + 1
                score = len(sequence) * 3.2 + len(sequence) / max(1, span) * 5 + bonus
                if score > best[0]:
                    best = (score, row, [col for col, _ in sequence])
        if best[1] is None:
            return None, [], 0.0
        return best[1], best[2], min(1.0, len(best[2]) / 12 + (0.25 if best[0] >= 25 else 0))

    def _detect_months(self, matrix: WorksheetMatrix, weeks_row: int, cols: Sequence[int]) -> Tuple[Optional[int], float]:
        sheet = matrix.worksheet
        found = []
        for row in range(max(1, weeks_row - 3), min(sheet.max_row, weeks_row + 4) + 1):
            hits = sum(
                any(normalize_text(matrix.value(row, col)).lower().startswith(prefix) for prefix in MONTH_PREFIXES)
                for col in range(max(1, cols[0] - 2), min(sheet.max_column, cols[-1] + 2) + 1)
            )
            if hits:
                found.append((hits * 10 + (2 if row > weeks_row else 0), row))
        if not found:
            return None, 0.0
        score, row = max(found)
        return row, min(1.0, score / 30)

    def _detect_legend(self, matrix: WorksheetMatrix) -> Dict[str, Any]:
        sheet = matrix.worksheet
        best: Dict[str, Any] = {"score": 0.0, "raw": 0.0, "start_row": None}
        for row in range(1, sheet.max_row + 1):
            columns: Dict[str, int] = {}
            score = 0.0
            for col in range(1, sheet.max_column + 1):
                text = normalize_text(matrix.value(row, col)).lower()
                if "обозн" in text or text in {"код", "шифр"}:
                    columns.setdefault("code_col", col); score += 2.5
                if "дисцип" in text or "наименован" in text:
                    columns.setdefault("subject_col", col); score += 2
                if "лектор" in text or "лекци" in text:
                    columns.setdefault("lecturer_col", col); score += 2
                if any(token in text for token in ("другие", "практик", "семинар", "лаборатор", "преподав")):
                    columns.setdefault("other_col", col); score += 1.8
            if score > best["raw"]:
                best = {"score": min(1.0, score / 7), "raw": score, "start_row": row, **columns}
        start = best.get("start_row")
        if not start:
            best.pop("raw", None); return best
        if not best.get("lecturer_col"):
            best["lecturer_col"] = best.get("other_col")
        if not best.get("other_col"):
            best["other_col"] = best.get("lecturer_col")
        best["code_col"] = best.get("code_col") or 1
        teacher_cols = [col for col in (best.get("lecturer_col"), best.get("other_col")) if col]
        best["data_start_offset"] = 1
        for offset in range(1, 8):
            row = start + offset
            if row > sheet.max_row:
                break
            code = normalize_text(matrix.value(row, best["code_col"]))
            teacher = " ".join(normalize_text(matrix.value(row, col)) for col in teacher_cols)
            if code and (teacher or best.get("subject_col")):
                best["data_start_offset"] = offset; break
        last, blanks = start + best["data_start_offset"], 0
        for row in range(last, sheet.max_row + 1):
            cols = [best.get(key) for key in ("code_col", "subject_col", "lecturer_col", "other_col") if best.get(key)]
            if any(normalize_text(matrix.value(row, col)) for col in cols):
                last, blanks = row, 0
            else:
                blanks += 1
                if blanks >= 3:
                    break
        best["end_row"] = last
        best.pop("raw", None)
        return best

    def _code_rows(self, matrix: WorksheetMatrix, weeks_row: int, week_cols: Sequence[int], legend: Optional[int]) -> Tuple[List[int], float]:
        end = min(matrix.worksheet.max_row, (legend - 1) if legend else matrix.worksheet.max_row)
        hits = []
        for row in range(weeks_row + 1, end + 1):
            count = sum(bool(LESSON_CODE_RE.search(normalize_text(matrix.value(row, col)))) for col in range(week_cols[0], week_cols[-1] + 1))
            if count:
                hits.append((row, count))
        return [row for row, _ in hits], min(1.0, sum(count for _, count in hits) / max(4, len(week_cols))) if hits else 0.0

    def _day_rows(self, matrix: WorksheetMatrix, weeks_row: int, legend: Optional[int]) -> List[Tuple[int, str]]:
        end = min(matrix.worksheet.max_row, (legend - 1) if legend else matrix.worksheet.max_row)
        result: Dict[int, str] = {}
        for row in range(weeks_row + 1, end + 1):
            for col in range(1, min(matrix.worksheet.max_column, 8) + 1):
                text = normalize_text(matrix.value(row, col))
                for day, pattern in DAY_PATTERNS.items():
                    if pattern.fullmatch(text):
                        result.setdefault(row, day)
        return sorted(result.items())

    @staticmethod
    def _median(values: Sequence[int], default: int) -> int:
        return max(1, int(round(statistics.median(values)))) if values else default

    def analyze(self, file_path: str, preferred_sheet: Optional[str] = None) -> AnalysisResult:
        workbook = load_workbook(file_path, data_only=True, read_only=False)
        if not workbook.sheetnames:
            raise ValueError("В книге нет листов.")
        selected = self._select_sheet(workbook, preferred_sheet)
        sheet = workbook[selected]
        matrix = WorksheetMatrix(sheet)
        diagnostics: List[Diagnostic] = []
        weeks_row, week_cols, week_score = self._detect_weeks(matrix)
        if weeks_row is None or not week_cols:
            weeks_row, week_cols = 1, [1]
            diagnostics.append(Diagnostic("error", "weeks_not_found", "Не удалось надёжно определить строку учебных недель. Укажите её вручную."))
        step = self._median([b - a for a, b in zip(week_cols, week_cols[1:]) if b > a], 1)
        months_row, month_score = self._detect_months(matrix, weeks_row, week_cols)
        legend = self._detect_legend(matrix)
        code_rows, code_score = self._code_rows(matrix, weeks_row, week_cols, legend.get("start_row"))
        day_rows = self._day_rows(matrix, weeks_row, legend.get("start_row"))
        stride = self._median([b - a for a, b in zip(code_rows, code_rows[1:]) if 1 <= b - a <= 6], 3)
        day_gaps = [b[0] - a[0] for a, b in zip(day_rows, day_rows[1:]) if b[0] > a[0]]
        if day_gaps:
            day_block = self._median(day_gaps, 13)
            pairs = max(1, min(10, day_block // stride))
        else:
            runs, current = [], 1
            for previous, current_row in zip(code_rows, code_rows[1:]):
                if current_row - previous == stride:
                    current += 1
                else:
                    runs.append(current); current = 1
            if code_rows:
                runs.append(current)
            counts = Counter(length for length in runs if 1 <= length <= 10)
            pairs = max((length for length, frequency in counts.items() if frequency == max(counts.values())), default=4)
            day_block = stride * pairs + 1
        grid_start = code_rows[0] if code_rows else weeks_row + 3
        subject_scores, room_scores = Counter(), Counter()
        for offset in range(1, 5):
            for row in code_rows[:20]:
                for col in week_cols:
                    text = normalize_text(matrix.value(row + offset, col))
                    if not text or LESSON_CODE_RE.search(text):
                        continue
                    if re.search(r"(?:ауд\.?|каб\.?|спорт|зал|\b\d{2,4}[а-яa-z]?\b)", text, re.I):
                        room_scores[offset] += 1
                    else:
                        subject_scores[offset] += 1
        subject_offset = max(subject_scores, key=subject_scores.get, default=1)
        room_offset = max({k: v for k, v in room_scores.items() if k != subject_offset}, key=lambda key: room_scores[key], default=subject_offset + 1)
        date_scores = Counter()
        for offset in range(-3, 2):
            for day_index in range(6):
                row = grid_start + day_index * day_block + offset
                if not 1 <= row <= sheet.max_row:
                    continue
                for col in week_cols:
                    value = matrix.value(row, col)
                    if isinstance(value, (date, datetime)):
                        date_scores[offset] += 2
                    elif re.fullmatch(r"\d{1,2}(?:[./-]\d{1,2})?", normalize_text(value)):
                        date_scores[offset] += 1
        date_offset = max(date_scores, key=date_scores.get, default=-1)
        grid_end = (legend.get("start_row") - 1) if legend.get("start_row") else (code_rows[-1] + room_offset if code_rows else sheet.max_row)
        if not code_rows:
            diagnostics.append(Diagnostic("warning", "lesson_rows_uncertain", "Строки занятий не распознаны по содержимому; применена геометрическая оценка."))
        if not legend.get("start_row"):
            diagnostics.append(Diagnostic("warning", "legend_not_found", "Блок дисциплин и преподавателей не найден. Укажите его вручную."))
        if not day_rows:
            diagnostics.append(Diagnostic("info", "day_labels_not_found", "Подписи дней недели не найдены; используется повторяющийся блок строк."))
        layout = ScheduleLayout(
            sheet_name=selected, weeks_row=weeks_row, first_week_col=week_cols[0], last_week_col=week_cols[-1],
            week_col_step=step, months_row=months_row, grid_start_row=grid_start, grid_end_row=max(grid_start, grid_end),
            day_block_rows=day_block, pairs_per_day=pairs, pair_row_stride=stride, date_row_offset=date_offset,
            subject_row_offset=subject_offset, room_row_offset=room_offset, legend_start_row=legend.get("start_row"),
            legend_end_row=legend.get("end_row"), legend_data_start_offset=legend.get("data_start_offset", 1),
            legend_code_col=legend.get("code_col"), legend_subject_col=legend.get("subject_col"),
            legend_lecturer_col=legend.get("lecturer_col"), legend_other_col=legend.get("other_col"),
        )
        confidence = min(1.0, 0.36 * week_score + 0.27 * code_score + 0.24 * legend.get("score", 0) + 0.08 * month_score + 0.05 * bool(day_rows))
        if confidence < 0.55:
            diagnostics.insert(0, Diagnostic("warning", "low_confidence", "Автоматическая разметка имеет низкую уверенность. Перед обработкой проверьте все границы."))
        schedule_preview = {
            "row_start": max(1, min(weeks_row, grid_start) - 2), "row_end": min(sheet.max_row, max(layout.grid_end_row or grid_start, grid_start) + 2),
            "col_start": max(1, week_cols[0] - 4), "col_end": min(sheet.max_column, week_cols[-1] + 2),
        }
        legend_start = legend.get("start_row") or min(sheet.max_row, (layout.grid_end_row or 1) + 1)
        legend_end = legend.get("end_row") or min(sheet.max_row, legend_start + 15)
        legend_cols = [value for value in (legend.get("code_col"), legend.get("subject_col"), legend.get("lecturer_col"), legend.get("other_col")) if value]
        legend_preview = {
            "row_start": max(1, legend_start - 2), "row_end": min(sheet.max_row, legend_end + 2),
            "col_start": max(1, min(legend_cols or [1]) - 1), "col_end": min(sheet.max_column, max(legend_cols or [min(sheet.max_column, 12)]) + 2),
        }
        return AnalysisResult(workbook.sheetnames, selected, sheet.max_row, sheet.max_column, confidence, layout, diagnostics, schedule_preview, legend_preview)

    def preview(self, file_path: str, sheet_name: str, row_start: int, row_end: int, col_start: int, col_end: int, max_rows: int = 140, max_columns: int = 60) -> Dict[str, Any]:
        workbook = load_workbook(file_path, data_only=True, read_only=False)
        if sheet_name not in workbook.sheetnames:
            raise ValueError(f"Лист «{sheet_name}» не найден.")
        sheet = workbook[sheet_name]
        matrix = WorksheetMatrix(sheet)
        row_start = max(1, min(row_start, sheet.max_row)); row_end = max(row_start, min(row_end, sheet.max_row, row_start + max_rows - 1))
        col_start = max(1, min(col_start, sheet.max_column)); col_end = max(col_start, min(col_end, sheet.max_column, col_start + max_columns - 1))
        columns = [{"index": col, "label": get_column_letter(col), "width": sheet.column_dimensions[get_column_letter(col)].width or 10} for col in range(col_start, col_end + 1)]
        rows = []
        for row in range(row_start, row_end + 1):
            cells = []
            for col in range(col_start, col_end + 1):
                cell = sheet.cell(row, col)
                anchor_row, anchor_col = matrix.merged_anchor(row, col)
                color = cell.fill.fgColor.rgb if cell.fill and cell.fill.fill_type and cell.fill.fgColor.type == "rgb" else None
                cells.append({
                    "column": col, "value": excel_display(matrix.value(row, col)), "merged": matrix.is_merged(row, col),
                    "anchor_row": anchor_row, "anchor_column": anchor_col, "bold": bool(cell.font and cell.font.bold),
                    "fill": color, "alignment": cell.alignment.horizontal if cell.alignment else None,
                })
            rows.append({"index": row, "height": sheet.row_dimensions[row].height or 15, "cells": cells})
        return {"sheet_name": sheet_name, "row_start": row_start, "row_end": row_end, "col_start": col_start, "col_end": col_end, "columns": columns, "rows": rows}
