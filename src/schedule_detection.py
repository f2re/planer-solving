"""Structural detection helpers for schedule workbooks."""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime
import math
import re
import statistics
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .schedule_layout import (
    DAY_NAMES, DAY_PATTERNS, LESSON_CODE_RE, MONTH_PREFIXES, PAIR_LABEL_RE,
    is_legend_record, normalize_text, value_as_int,
)
from .worksheet_matrix import WorksheetMatrix


class ScheduleStructureDetector:

    @staticmethod
    def _median(values: Sequence[int], default: int) -> int:
        return max(1, int(round(statistics.median(values)))) if values else default

    @staticmethod
    def _day_name(value: Any) -> Optional[str]:
        text = normalize_text(value)
        return next((name for name, pattern in DAY_PATTERNS.items() if pattern.fullmatch(text)), None)

    @staticmethod
    def _month_name(value: Any) -> Optional[str]:
        text = normalize_text(value).casefold()
        return next((name for prefix, name in MONTH_PREFIXES.items() if text.startswith(prefix)), None)

    def _week_sequence(self, matrix: WorksheetMatrix, row: int) -> List[Tuple[int, int]]:
        numeric = []
        for col, value in matrix.anchor_values(row):
            number = value_as_int(value)
            if number is not None and 0 <= number <= 60:
                numeric.append((col, number))
        best: List[Tuple[int, int]] = []
        current: List[Tuple[int, int]] = []
        for item in numeric:
            if not current or item[1] == current[-1][1] + 1:
                current.append(item)
            else:
                if len(current) > len(best):
                    best = current
                current = [item]
        if len(current) > len(best):
            best = current
        return best

    def _detect_weeks(self, matrix: WorksheetMatrix) -> Tuple[Optional[int], List[int], List[int], float]:
        sheet = matrix.worksheet
        best: Tuple[float, Optional[int], List[Tuple[int, int]]] = (-1.0, None, [])
        for row in range(1, min(sheet.max_row, 120) + 1):
            anchors = matrix.anchor_values(row)
            texts = [normalize_text(value).casefold() for _, value in anchors]
            keyword = any("недел" in text for text in texts)
            sequence = self._week_sequence(matrix, row)
            if not sequence:
                continue
            month_support = 0
            for nearby in range(max(1, row - 2), min(sheet.max_row, row + 3) + 1):
                month_support = max(
                    month_support,
                    sum(bool(self._month_name(matrix.value(nearby, col))) for col, _ in sequence),
                )
            service_limit = max(1, sequence[0][0] - 1)
            day_support = 0
            for nearby in range(row + 1, min(sheet.max_row, row + 90) + 1):
                if any(self._day_name(matrix.value(nearby, col)) for col in range(1, service_limit + 1)):
                    day_support += 1
            score = (
                (120 if keyword else 0)
                + len(sequence) * 5
                + max(0, len(sequence) - 1) * 3
                + min(month_support, 8) * 2
                + min(day_support, 6) * 4
                - row * 0.03
            )
            if score > best[0]:
                best = (score, row, sequence)
        if best[1] is None:
            return None, [], [], 0.0
        sequence = best[2]
        confidence = min(1.0, 0.35 + len(sequence) / 30 + (0.25 if best[0] >= 150 else 0))
        return best[1], [col for col, _ in sequence], [number for _, number in sequence], confidence

    def _detect_months(self, matrix: WorksheetMatrix, weeks_row: int, week_cols: Sequence[int]) -> Tuple[Optional[int], float]:
        sheet = matrix.worksheet
        best: Tuple[float, Optional[int]] = (0.0, None)
        for row in range(max(1, weeks_row - 3), min(sheet.max_row, weeks_row + 4) + 1):
            hits = sum(bool(self._month_name(matrix.value(row, col))) for col in week_cols)
            label = " ".join(normalize_text(value).casefold() for _, value in matrix.anchor_values(row, 1, max(week_cols)))
            score = hits * 10 + (8 if "месяц" in label else 0) + (3 if row == weeks_row + 1 else 0)
            if score > best[0]:
                best = (score, row)
        return best[1], min(1.0, best[0] / 35) if best[1] else 0.0

    def _detect_day_rows(self, matrix: WorksheetMatrix, weeks_row: int, first_week_col: int) -> List[Tuple[int, str]]:
        sheet = matrix.worksheet
        found: List[Tuple[int, str]] = []
        seen = set()
        for row in range(weeks_row + 1, min(sheet.max_row, weeks_row + 100) + 1):
            for col in range(1, max(2, first_week_col)):
                if not matrix.is_anchor(row, col):
                    continue
                day = self._day_name(matrix.value(row, col))
                if day and day not in seen:
                    found.append((row, day))
                    seen.add(day)
                    break
        ordered = []
        last = weeks_row
        for expected in DAY_NAMES:
            candidate = next(((row, day) for row, day in found if day == expected and row > last), None)
            if candidate:
                ordered.append(candidate)
                last = candidate[0]
        return ordered

    def _detect_pair_offsets(
        self,
        matrix: WorksheetMatrix,
        first_day_row: int,
        next_day_row: Optional[int],
        first_week_col: int,
    ) -> List[int]:
        end = (next_day_row - 1) if next_day_row else min(matrix.worksheet.max_row, first_day_row + 16)
        offsets = []
        for row in range(first_day_row, end + 1):
            for col in range(1, max(2, first_week_col)):
                if not matrix.is_anchor(row, col):
                    continue
                match = PAIR_LABEL_RE.fullmatch(normalize_text(matrix.value(row, col)))
                if match and max(int(match.group(1)), int(match.group(2))) <= 12:
                    offsets.append(row - first_day_row)
                    break
        return list(dict.fromkeys(offsets)) or [0, 3, 6, 9]

    def _row_kind_scores(
        self,
        matrix: WorksheetMatrix,
        rows: Iterable[int],
        week_cols: Sequence[int],
    ) -> Tuple[Counter, Counter, Counter]:
        code_scores, subject_scores, room_scores = Counter(), Counter(), Counter()
        for base in rows:
            for offset in range(0, 5):
                row = base + offset
                if row > matrix.worksheet.max_row:
                    continue
                for col in week_cols:
                    text = normalize_text(matrix.value(row, col))
                    if not text:
                        continue
                    if LESSON_CODE_RE.search(text):
                        code_scores[offset] += 3
                    elif re.search(r"(?:ауд\.?|каб\.?|спорт|зал|плац|клуб|\b\d{2,4}(?:[-/][0-9а-яa-z]+)?\b)", text, re.I):
                        room_scores[offset] += 2
                    elif text.casefold() not in {"вых", "отп", "экзс", "эпр", "ср", "упр", "пв", "умо"}:
                        subject_scores[offset] += 1
        return code_scores, subject_scores, room_scores

    @staticmethod
    def _week_candidate_columns(
        matrix: WorksheetMatrix,
        weeks_row: int,
        week_cols: Sequence[int],
    ) -> List[int]:
        result: List[int] = []
        for col in week_cols:
            _, min_col, _, max_col = matrix.merged_bounds(weeks_row, col)
            result.extend(range(min_col, max_col + 1))
        return list(dict.fromkeys(result))

    def _detect_week_data_columns(
        self,
        matrix: WorksheetMatrix,
        weeks_row: int,
        week_cols: Sequence[int],
        day_rows: Sequence[Tuple[int, str]],
        pair_offsets: Sequence[int],
        code_offset: int,
        subject_offset: int,
    ) -> List[int]:
        sample_days = [row for row, _ in day_rows[:3]] or [weeks_row + 3]
        result: List[int] = []
        for header_col in week_cols:
            _, min_col, _, max_col = matrix.merged_bounds(weeks_row, header_col)
            candidates = list(range(min_col, max_col + 1)) or [header_col]
            ranked = []
            for candidate in candidates:
                score = 0
                for day_row in sample_days:
                    for pair_offset in pair_offsets:
                        base = day_row + pair_offset
                        code = normalize_text(matrix.value(base + code_offset, candidate))
                        subject = normalize_text(matrix.value(base + subject_offset, candidate))
                        if LESSON_CODE_RE.search(code):
                            score += 12
                        elif code:
                            score -= 1
                        if subject:
                            score += 2
                ranked.append((score, 1 if candidate == header_col else 0, candidate))
            result.append(max(ranked)[2])
        return result

    def _detect_legend(self, matrix: WorksheetMatrix, start_row: int) -> Dict[str, Any]:
        sheet = matrix.worksheet
        best: Dict[str, Any] = {"score": 0.0, "row": None, "columns": {}}
        for row in range(max(1, start_row), sheet.max_row + 1):
            columns: Dict[str, int] = {}
            score = 0.0
            for col, value in matrix.anchor_values(row):
                text = normalize_text(value).casefold()
                if "обозн" in text or text in {"код", "шифр"}:
                    columns.setdefault("code", col); score += 5.0
                if "дисцип" in text or "наименован" in text:
                    columns.setdefault("subject", col); score += 4.5
                if "лектор" in text or "лекци" in text or "летор" in text:
                    columns.setdefault("lecturer", col); score += 4.0
                if any(token in text for token in ("другие", "практик", "семинар", "лаборатор")):
                    columns.setdefault("other", col); score += 3.5
                if "каф" in text:
                    score += 1.5
                if "кол-во" in text or "час" in text:
                    score += 1.0
            if len(columns) >= 3 and score > best["score"]:
                best = {"score": score, "row": row, "columns": columns}
        header = best.get("row")
        if not header:
            return {"score": 0.0, "start_row": None}
        columns = best["columns"]
        data_start = None
        for row in range(header + 1, min(sheet.max_row, header + 12) + 1):
            code = normalize_text(matrix.row_value(row, columns.get("code")))
            subject = normalize_text(matrix.row_value(row, columns.get("subject")))
            lecturer = normalize_text(matrix.row_value(row, columns.get("lecturer")))
            other = normalize_text(matrix.row_value(row, columns.get("other")))
            if is_legend_record(code, subject, lecturer, other):
                data_start = row
                break
        if data_start is None:
            data_start = header + 1
        last = data_start - 1
        blanks = 0
        for row in range(data_start, sheet.max_row + 1):
            code = normalize_text(matrix.row_value(row, columns.get("code")))
            subject = normalize_text(matrix.row_value(row, columns.get("subject")))
            lecturer = normalize_text(matrix.row_value(row, columns.get("lecturer")))
            other = normalize_text(matrix.row_value(row, columns.get("other")))
            if is_legend_record(code, subject, lecturer, other):
                last = row
                blanks = 0
            else:
                blanks += 1
                if blanks >= 2:
                    break
        return {
            "score": min(1.0, best["score"] / 18.0),
            "start_row": header,
            "end_row": max(last, data_start),
            "data_start_row": data_start,
            "data_start_offset": data_start - header,
            "code_col": columns.get("code"),
            "subject_col": columns.get("subject"),
            "lecturer_col": columns.get("lecturer"),
            "other_col": columns.get("other"),
        }

    def _select_sheet(self, workbook: Any, preferred: Optional[str]) -> str:
        if preferred in workbook.sheetnames:
            return preferred
        scored = []
        for sheet in workbook.worksheets:
            matrix = WorksheetMatrix(sheet)
            weeks_row, week_cols, _, week_score = self._detect_weeks(matrix)
            day_rows = self._detect_day_rows(matrix, weeks_row or 1, week_cols[0] if week_cols else 8)
            legend = self._detect_legend(matrix, (weeks_row or 1) + 10)
            nonempty = sum(1 for row in sheet.iter_rows() for cell in row if normalize_text(cell.value))
            score = week_score * 120 + len(day_rows) * 15 + legend.get("score", 0) * 40 + math.log1p(nonempty)
            scored.append((score, sheet.title))
        return max(scored)[1]
