"""Excel schedule parser driven by an operator-editable exact layout."""
from __future__ import annotations

from collections import defaultdict
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Set, Tuple, Union

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

    @staticmethod
    def _parse_override_slot(value: Any) -> Optional[Tuple[int, str]]:
        try:
            raw_week, day_name = str(value).split(":", 1)
            week = int(raw_week)
        except (TypeError, ValueError):
            return None
        return week, day_name

    @staticmethod
    def _override_date_parts(value: Any) -> Dict[str, Any]:
        if isinstance(value, Mapping):
            return {
                "day": int(value.get("day") or 0),
                "month": canonical_month(value.get("month")),
                "year": int(value.get("year") or 0),
            }
        return extract_date_parts(value)

    def _source_period(
        self,
        matrix: WorksheetMatrix,
        layout: ScheduleLayout,
        weeks: List[Tuple[int, int, int]],
        semester: str,
        year: str,
        report: Dict[str, Any],
        period_overrides: Optional[Mapping[str, Any]] = None,
    ) -> Dict[Tuple[int, str], Dict[str, Any]]:
        """Read and gently reconcile the source month/date scale."""

        period_overrides = dict(period_overrides or {})
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

        for raw_slot, raw_value in (period_overrides.get("week_day_dates") or {}).items():
            slot = self._parse_override_slot(raw_slot)
            parts = self._override_date_parts(raw_value)
            if not slot or not parts.get("month") or not 1 <= int(parts.get("day") or 0) <= 31:
                continue
            week_day_dates[slot] = {
                "day": int(parts["day"]),
                "month": str(parts["month"]),
                "year": int(parts.get("year") or 0),
            }
            report["auto_repairs"].append({
                "type": "period_override",
                "slot": f"{slot[0]}:{slot[1]}",
                "after": dict(week_day_dates[slot]),
                "reason": "Применена ручная правка оператора.",
                "blocking": False,
            })

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
        for raw_week, raw_month in (period_overrides.get("week_months") or {}).items():
            try:
                week = int(raw_week)
            except (TypeError, ValueError):
                continue
            month = canonical_month(raw_month)
            if month:
                week_months[week] = month

        period, period_warnings, _period_errors = build_file_period_report(
            week_numbers=[week for week, _, _ in weeks],
            week_months=week_months,
            week_day_dates=week_day_dates,
            semester_info=period_overrides.get("semester_info") or semester,
            year_info=period_overrides.get("year_info") or year,
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
        period["operator_actions"] = [
            item.get("action") for item in period["issues"] if item.get("action")
        ]
        period_warnings.extend(
            item["message"]
            for item in period["issues"]
            if item.get("severity") == "warning" and item["message"] not in period_warnings
        )

        report["period"] = period
        report["warnings"].extend(
            message for message in period_warnings if message not in report["warnings"]
        )
        report["actions"].extend(period.get("operator_actions") or [])
        self.loaded_periods.append((report["file"], period))
        return week_day_dates

    def load_group_schedule(
        self,
        file_path: str,
        group_name: Optional[str] = None,
        layout: Optional[Union[ScheduleLayout, Dict[str, Any]]] = None,
        period_overrides: Optional[Mapping[str, Any]] = None,
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
            "actions": [],
            "auto_repairs": [],
            "layout_used": {},
            "blocking": False,
        }
        self.last_report = report
        try:
            workbook = load_workbook(path, data_only=True, read_only=False)
        except Exception as exc:
            report["errors"].append(f"Не удалось открыть Excel-файл: {exc}")
            report["actions"].append({
                "type": "replace_file",
                "label": "Выбрать другой файл",
                "blocking": False,
            })
            report["status"] = "skipped"
            return []

        if layout is None:
            analysis = ScheduleAnalyzer().analyze(str(path))
            selected = analysis.layout
            report["warnings"].extend(item.message for item in analysis.diagnostics if item.severity != "info")
        else:
            selected = layout if isinstance(layout, ScheduleLayout) else ScheduleLayout.from_dict(layout)

        if selected.sheet_name not in workbook.sheetnames:
            replacement = workbook.sheetnames[0]
            report["warnings"].append(
                f"Лист «{selected.sheet_name}» не найден; автоматически выбран «{replacement}»."
            )
            report["auto_repairs"].append({
                "type": "layout_patch",
                "field": "sheet_name",
                "before": selected.sheet_name,
                "after": replacement,
                "reason": "Выбран существующий лист книги.",
                "blocking": False,
            })
            selected.sheet_name = replacement

        sheet = workbook[selected.sheet_name]
        selected, repairs = selected.repaired(sheet)
        report["auto_repairs"].extend(repairs)
        report["layout_used"] = selected.to_dict()
        matrix = WorksheetMatrix(sheet)
        validation = selected.validate(sheet)
        report["warnings"].extend(item.message for item in validation)

        semester, year = self._metadata(matrix)
        weeks = self._weeks(matrix, selected, report)
        if not weeks:
            report["warnings"].append(
                "Учебные недели пока не распознаны. Исправьте строку или столбцы недель прямо в редакторе."
            )
            report["actions"].append({
                "type": "edit_layout",
                "field": "weeks_row",
                "selection_mode": "weeks",
                "label": "Указать строку и столбцы недель",
                "blocking": False,
            })
            report["status"] = "needs_operator"
            return []

        source_dates = self._source_period(
            matrix,
            selected,
            weeks,
            semester,
            year,
            report,
            period_overrides=period_overrides,
        )
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
            report["warnings"].append(
                "По текущей разметке занятия не найдены. Файл сохранён в сеансе: поправьте слои или границы на этом же экране."
            )
            report["actions"].append({
                "type": "edit_layout",
                "field": "grid_start_row",
                "selection_mode": "grid",
                "label": "Указать сетку занятий",
                "blocking": False,
            })
            report["status"] = "needs_operator"
        elif report["unknown_teacher_lessons"]:
            report["warnings"].append(
                f"Для {report['unknown_teacher_lessons']} занятий преподаватель не определён; они попадут в раздел «Не назначен».")
            report["actions"].append({
                "type": "open_teacher_mapping",
                "label": "Уточнить преподавателей",
                "blocking": False,
            })
            report["status"] = "ready_with_warnings"
        else:
            report["status"] = "ready_with_warnings" if report["warnings"] else "ready"
        return lessons
