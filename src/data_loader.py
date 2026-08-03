"""Excel schedule parser driven by an operator-confirmed exact layout."""
from __future__ import annotations

from collections import defaultdict
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from openpyxl import load_workbook

from .schedule_analyzer import LESSON_CODE_RE, ScheduleAnalyzer, ScheduleLayout, WorksheetMatrix, normalize_text
from .schedule_parser_geometry import ScheduleParserGeometry
from .schedule_period import (
    build_file_period_report,
    canonical_month,
    compare_file_periods,
    extract_date_parts,
    next_month,
)
from .teacher_resolver import TeacherResolver

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
    date_year: int = 0


class DataLoader(TeacherResolver, ScheduleParserGeometry):
    @staticmethod
    def _date_rollover(previous_day: int, current_day: int) -> bool:
        return bool(
            previous_day
            and current_day
            and (
                previous_day - current_day >= 15
                or (previous_day >= 25 and current_day <= 7)
            )
        )

    def _source_period(
        self,
        matrix: WorksheetMatrix,
        layout: ScheduleLayout,
        weeks: List[Tuple[int, int, int]],
        semester: str,
        year: str,
        report: Dict[str, Any],
    ) -> Dict[Tuple[int, str], Dict[str, Any]]:
        """Read the source month/date scale before parsing individual lessons."""

        header_months: Dict[int, str] = {}
        current_header_month: Optional[str] = None
        for week, header_col, _ in weeks:
            parsed = (
                canonical_month(matrix.value(layout.months_row, header_col))
                if layout.months_row
                else None
            )
            if parsed:
                current_header_month = parsed
            if current_header_month:
                header_months[week] = current_header_month

        day_rows = layout.resolved_day_rows()
        day_names = layout.day_names[: len(day_rows)]
        raw_slots: List[Dict[str, Any]] = []
        for week, _, data_col in weeks:
            for day_name, day_start in zip(day_names, day_rows):
                date_row = day_start + layout.date_row_offset
                raw_value = (
                    matrix.value(date_row, data_col)
                    if 1 <= date_row <= matrix.worksheet.max_row
                    else None
                )
                raw_slots.append({
                    "week": week,
                    "day_name": day_name,
                    "header_month": header_months.get(week),
                    "parts": extract_date_parts(raw_value),
                })

        week_day_dates: Dict[Tuple[int, str], Dict[str, Any]] = {}
        previous_day = 0
        previous_month: Optional[str] = None
        for slot in raw_slots:
            parts = slot["parts"]
            day = int(parts.get("day") or 0)
            if not day:
                continue
            explicit_month = canonical_month(parts.get("month"))
            header_month = canonical_month(slot.get("header_month"))
            inferred_month = explicit_month

            if not inferred_month:
                inferred_month = previous_month or header_month
                if previous_month and self._date_rollover(previous_day, day):
                    inferred_month = next_month(previous_month)
                elif (
                    previous_month
                    and header_month
                    and header_month != previous_month
                    and header_month == next_month(previous_month)
                    and day <= 15
                ):
                    # A missing day near the month boundary can hide the
                    # numerical rollover. The source month row is the anchor.
                    inferred_month = header_month

            if not inferred_month:
                continue
            week_day_dates[(slot["week"], slot["day_name"])] = {
                "day": day,
                "month": inferred_month,
                "year": int(parts.get("year") or 0),
            }
            previous_day = day
            previous_month = inferred_month

        date_months_by_week: Dict[int, List[str]] = defaultdict(list)
        for (week, _), item in week_day_dates.items():
            month = canonical_month(item.get("month"))
            if month and month not in date_months_by_week[week]:
                date_months_by_week[week].append(month)

        week_months: Dict[int, str] = {}
        for week, _, _ in weeks:
            month = header_months.get(week)
            if not month and date_months_by_week.get(week):
                month = date_months_by_week[week][0]
            if month:
                week_months[week] = month

        period, period_warnings, period_errors = build_file_period_report(
            week_numbers=[week for week, _, _ in weeks],
            week_months=week_months,
            week_day_dates=week_day_dates,
            semester_info=semester,
            year_info=year,
        )
        period["source_file"] = report["file"]
        period["source_group"] = report["group"]

        for previous_label, previous_period in self.loaded_periods:
            period["issues"].extend(compare_file_periods(
                previous_period,
                period,
                reference_label=previous_label,
                current_label=report["file"],
            ))
        period_warnings.extend(
            item["message"]
            for item in period["issues"]
            if item["severity"] == "warning" and item["message"] not in period_warnings
        )
        period_errors.extend(
            item["message"]
            for item in period["issues"]
            if item["severity"] == "error" and item["message"] not in period_errors
        )

        report["period"] = period
        report["warnings"].extend(
            message for message in period_warnings if message not in report["warnings"]
        )
        report["errors"].extend(
            message for message in period_errors if message not in report["errors"]
        )
        # Keep even a conflicting period available to the batch validator, but
        # use only successful periods as the next comparison reference.
        if not period_errors:
            self.loaded_periods.append((report["file"], period))
        return week_day_dates

    def load_group_schedule(
        self,
        file_path: str,
        group_name: Optional[str] = None,
        layout: Optional[Union[ScheduleLayout, Dict[str, Any]]] = None,
    ) -> List[Lesson]:
        path = Path(file_path)
        group_name = normalize_text(group_name) or path.stem
        report: Dict[str, Any] = {
            "file": path.name,
            "group": group_name,
            "lesson_count": 0,
            "mapped_lessons": 0,
            "unknown_teacher_lessons": 0,
            "unknown_subjects": [],
            "legend_entries": 0,
            "empty_week_columns": [],
            "skipped_non_lesson_cells": 0,
            "warnings": [],
            "errors": [],
            "samples": [],
            "period": {},
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
        weeks = self._weeks(matrix, selected, report)
        if not weeks:
            return []
        source_dates = self._source_period(
            matrix,
            selected,
            weeks,
            semester,
            year,
            report,
        )
        if report["errors"]:
            return []

        legend = self._legend(matrix, selected, report)
        lessons: List[Lesson] = []
        unknown: Set[str] = set()
        grid_end = selected.grid_end_row or sheet.max_row
        day_rows = selected.resolved_day_rows()
        pair_offsets = selected.resolved_pair_offsets()
        day_names = selected.day_names[: len(day_rows)]
        for day_name, day_start in zip(day_names, day_rows):
            if day_start > grid_end or day_start > sheet.max_row:
                continue
            for pair_index, pair_offset in enumerate(pair_offsets):
                pair = pair_index + 1
                base = day_start + pair_offset
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
                    if not LESSON_CODE_RE.search(code):
                        report["skipped_non_lesson_cells"] += 1
                        continue
                    if not subject:
                        parsed_code, parsed_subject, parsed_room, parsed_teachers = self._combined(code)
                        if parsed_subject:
                            code, subject, room = parsed_code, parsed_subject, room or parsed_room
                            schedule_teachers.extend(parsed_teachers)
                    if not subject or self._subject_key(subject) in self.NON_LESSON_SUBJECTS:
                        report["skipped_non_lesson_cells"] += 1
                        continue
                    lesson_type = self._lesson_type(code)
                    role = self._teacher_role(code)
                    entry = legend.get(self._subject_key(subject), {})
                    legend_teachers = entry.get(role, [])
                    if selected.teacher_source == "schedule":
                        candidates = schedule_teachers
                    elif selected.teacher_source == "both":
                        candidates = list(dict.fromkeys([*schedule_teachers, *legend_teachers]))
                    else:
                        candidates = legend_teachers
                    teacher = self._assign_teacher(week, day_name, pair, subject, lesson_type, candidates)
                    if teacher == "Unknown":
                        report["unknown_teacher_lessons"] += 1
                        unknown.add(subject)
                    else:
                        report["mapped_lessons"] += 1
                    source_date = source_dates.get((week, day_name), {})
                    lesson = Lesson(
                        group=group_name,
                        subject=subject,
                        lesson_type_code=code,
                        room=room,
                        week=week,
                        day_of_week=day_name,
                        pair_num=pair,
                        teacher=teacher,
                        date_day=int(source_date.get("day") or 0),
                        month=str(source_date.get("month") or "Unknown"),
                        semester_info=semester,
                        year_info=year,
                        date_year=int(source_date.get("year") or 0),
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
