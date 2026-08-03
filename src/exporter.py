"""Fault-tolerant Excel exporters for summary and teacher schedules."""
from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any, Dict, List, Mapping, Sequence

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side


UNASSIGNED_TEACHER = "Не назначен"
INVALID_SHEET_CHARS = re.compile(r"[\\/*?:\[\]]")


def _get_fills() -> Dict[str, PatternFill]:
    return {
        "Л": PatternFill(start_color="FFFFE0", end_color="FFFFE0", fill_type="solid"),
        "П": PatternFill(start_color="E0FFFF", end_color="E0FFFF", fill_type="solid"),
        "С": PatternFill(start_color="E0FFFF", end_color="E0FFFF", fill_type="solid"),
        "ЛР": PatternFill(start_color="E0FFE0", end_color="E0FFE0", fill_type="solid"),
        "Экз": PatternFill(start_color="FFE0E0", end_color="FFE0E0", fill_type="solid"),
    }


def _teacher_value(item: Mapping[str, Any], key: str, fallback: str = "") -> str:
    value = str(item.get(key) or "").strip()
    return value or fallback


def _teacher_short_name(item: Mapping[str, Any]) -> str:
    return _teacher_value(item, "short_name", _teacher_value(item, "full_name", UNASSIGNED_TEACHER))


def _teacher_full_name(item: Mapping[str, Any]) -> str:
    return _teacher_value(item, "full_name", _teacher_short_name(item))


def _unique_sheet_title(workbook: openpyxl.Workbook, desired: str) -> str:
    base = INVALID_SHEET_CHARS.sub(" ", str(desired or UNASSIGNED_TEACHER)).strip() or UNASSIGNED_TEACHER
    base = re.sub(r"\s+", " ", base)[:31]
    existing = {sheet.title.casefold() for sheet in workbook.worksheets}
    if base.casefold() not in existing:
        return base
    for number in range(2, 10_000):
        suffix = f" ({number})"
        candidate = f"{base[:31 - len(suffix)]}{suffix}"
        if candidate.casefold() not in existing:
            return candidate
    return f"Лист {len(workbook.worksheets) + 1}"[:31]


def _teacher_sheet_title(item: Mapping[str, Any]) -> str:
    parts = _teacher_full_name(item).split()
    if len(parts) >= 3:
        return f"{parts[0]} {parts[1][0]}.{parts[2][0]}."
    if len(parts) == 2:
        return f"{parts[0]} {parts[1][0]}."
    return parts[0] if parts else UNASSIGNED_TEACHER


def _apply_summary_header(
    worksheet: Any,
    transformed_data: Mapping[str, Any],
    dates: Sequence[Sequence[Any]],
) -> None:
    header_font = Font(name="Times New Roman", size=8, bold=True)
    header_alignment = Alignment(horizontal="center", vertical="center")
    end_column = max(5, 5 + len(dates))
    worksheet.merge_cells(start_row=1, start_column=1, end_row=1, end_column=end_column)

    semester_part = str(transformed_data.get("semester_info") or "На семестр").strip()
    if "расписание учебных занятий" in semester_part.lower():
        semester_part = semester_part.lower().replace("расписание учебных занятий", "").strip().capitalize()
    if "на " not in semester_part.lower() and semester_part:
        semester_part = f"На {semester_part.lower()}"
    year_part = str(transformed_data.get("year_info") or "").strip()
    title_cell = worksheet.cell(row=1, column=1, value=f"{semester_part} {year_part}".strip())
    title_cell.font = header_font
    title_cell.alignment = Alignment(horizontal="left", vertical="center")

    columns = ["№ п/п", "Должность", "Звание", "Фамилия, имя, отчество", "Месяц"]
    for index, column_name in enumerate(columns, start=1):
        cell = worksheet.cell(row=2, column=index, value=column_name)
        cell.font = header_font
        cell.alignment = header_alignment
        if column_name != "Месяц":
            worksheet.merge_cells(start_row=2, start_column=index, end_row=4, end_column=index)

    worksheet.cell(row=3, column=5, value="№ недели").font = header_font
    worksheet.cell(row=3, column=5).alignment = header_alignment
    worksheet.cell(row=4, column=5, value="№ часа").font = header_font
    worksheet.cell(row=4, column=5).alignment = header_alignment
    for letter, width in {"A": 8.57, "B": 16.43, "C": 15.86, "D": 24.71, "E": 5.71}.items():
        worksheet.column_dimensions[letter].width = width

    current_column = 6
    last_month: str | None = None
    month_start_column = current_column
    for raw in dates:
        month, day, week_number = (list(raw) + ["", "", ""])[:3]
        week_cell = worksheet.cell(row=3, column=current_column, value=week_number)
        week_cell.font = header_font
        week_cell.alignment = header_alignment
        day_cell = worksheet.cell(row=4, column=current_column, value=day)
        day_cell.font = header_font
        day_cell.alignment = header_alignment
        worksheet.column_dimensions[openpyxl.utils.get_column_letter(current_column)].width = 13.0

        month_name = str(month or "Не определён")
        if month_name != last_month:
            if last_month is not None and current_column - 1 >= month_start_column:
                worksheet.merge_cells(
                    start_row=2,
                    start_column=month_start_column,
                    end_row=2,
                    end_column=current_column - 1,
                )
                month_cell = worksheet.cell(row=2, column=month_start_column, value=last_month.upper())
                month_cell.font = header_font
                month_cell.alignment = header_alignment
            last_month = month_name
            month_start_column = current_column
        current_column += 1

    if last_month is not None and current_column - 1 >= month_start_column:
        worksheet.merge_cells(
            start_row=2,
            start_column=month_start_column,
            end_row=2,
            end_column=current_column - 1,
        )
        month_cell = worksheet.cell(row=2, column=month_start_column, value=last_month.upper())
        month_cell.font = header_font
        month_cell.alignment = header_alignment


def _fill_summary_rows(
    worksheet: Any,
    start_row: int,
    teachers: Sequence[Mapping[str, Any]],
    transformed_data: Mapping[str, Any],
) -> None:
    dates = list(transformed_data.get("dates") or [])
    grid = transformed_data.get("grid") or {}
    data_font = Font(name="Calibri", size=11)
    header_font = Font(name="Times New Roman", size=8, bold=True)
    header_alignment = Alignment(horizontal="center", vertical="center")
    thin_side = Side(style="thin")
    border = Border(left=thin_side, right=thin_side, top=thin_side, bottom=thin_side)
    fills = _get_fills()

    current_row = start_row
    for index, teacher_info in enumerate(teachers, start=1):
        teacher_name = _teacher_short_name(teacher_info)
        values = [
            index,
            _teacher_value(teacher_info, "position"),
            _teacher_value(teacher_info, "rank", "—"),
            _teacher_full_name(teacher_info),
        ]
        for column, value in enumerate(values, start=1):
            cell = worksheet.cell(row=current_row, column=column, value=value)
            cell.font = data_font
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            worksheet.merge_cells(
                start_row=current_row,
                start_column=column,
                end_row=current_row + 3,
                end_column=column,
            )

        for pair_number in range(1, 5):
            pair_label = {1: "1-2", 2: "3-4", 3: "5-6", 4: "7-8"}[pair_number]
            pair_cell = worksheet.cell(row=current_row + pair_number - 1, column=5, value=pair_label)
            pair_cell.font = header_font
            pair_cell.alignment = header_alignment
            for date_index, raw in enumerate(dates):
                month, day = (list(raw) + ["", ""])[:2]
                item = grid.get((teacher_name, pair_number, month, day))
                cell = worksheet.cell(row=current_row + pair_number - 1, column=6 + date_index)
                if not item:
                    continue
                groups = ", ".join(map(str, item.get("groups") or []))
                item_type = str(item.get("type") or "")
                cell.value = "\n".join([
                    item_type,
                    str(item.get("subject") or ""),
                    str(item.get("room") or ""),
                    groups,
                ]).strip()
                cell.alignment = Alignment(
                    wrap_text=True,
                    horizontal="center",
                    vertical="center",
                    shrink_to_fit=True,
                )
                cell.font = Font(size=8)
                lesson_type = item_type.split("/")[0] if "/" in item_type else item_type
                if lesson_type in fills:
                    cell.fill = fills[lesson_type]
        current_row += 4

    max_row = max(4, current_row - 1)
    for row in worksheet.iter_rows(
        min_row=2,
        max_row=max_row,
        min_col=1,
        max_col=max(5, 5 + len(dates)),
    ):
        for cell in row:
            cell.border = border


def _fill_teacher_vertical(
    worksheet: Any,
    teacher_info: Mapping[str, Any],
    transformed_data: Mapping[str, Any],
) -> None:
    weeks = list(transformed_data.get("weeks") or [])
    grid = transformed_data.get("grid_vertical") or {}
    week_to_month = transformed_data.get("week_to_month") or {}
    week_day_to_date = transformed_data.get("week_day_to_date") or {}
    teacher_name = _teacher_short_name(teacher_info)
    header_font = Font(name="Times New Roman", size=10, bold=True)
    header_alignment = Alignment(horizontal="center", vertical="center")
    thin_side = Side(style="thin")
    border = Border(left=thin_side, right=thin_side, top=thin_side, bottom=thin_side)
    fills = _get_fills()

    worksheet.column_dimensions["A"].width = 15
    worksheet.column_dimensions["B"].width = 10
    worksheet.cell(row=1, column=1, value="Уч. недели").font = header_font
    worksheet.cell(row=2, column=1, value="Месяц").font = header_font

    last_month: str | None = None
    month_start_column = 3
    for index, week in enumerate(weeks):
        column = 3 + index
        week_cell = worksheet.cell(row=1, column=column, value=week)
        week_cell.font = header_font
        week_cell.alignment = header_alignment
        worksheet.column_dimensions[openpyxl.utils.get_column_letter(column)].width = 15
        month = str(week_to_month.get(week) or "Не определён")
        if month != last_month:
            if last_month is not None and column - 1 >= month_start_column:
                worksheet.merge_cells(
                    start_row=2,
                    start_column=month_start_column,
                    end_row=2,
                    end_column=column - 1,
                )
                month_cell = worksheet.cell(row=2, column=month_start_column, value=last_month.upper())
                month_cell.font = header_font
                month_cell.alignment = header_alignment
            last_month = month
            month_start_column = column
    if last_month and weeks:
        end_column = 2 + len(weeks)
        worksheet.merge_cells(
            start_row=2,
            start_column=month_start_column,
            end_row=2,
            end_column=end_column,
        )
        month_cell = worksheet.cell(row=2, column=month_start_column, value=last_month.upper())
        month_cell.font = header_font
        month_cell.alignment = header_alignment

    days = [
        ("Пн", "ПОНЕДЕЛЬНИК"),
        ("Вт", "ВТОРНИК"),
        ("Ср", "СРЕДА"),
        ("Чт", "ЧЕТВЕРГ"),
        ("Пт", "ПЯТНИЦА"),
        ("Сб", "СУББОТА"),
    ]
    current_row = 3
    for day_short, day_full in days:
        worksheet.cell(row=current_row, column=1, value="Даты").font = header_font
        worksheet.cell(row=current_row, column=1).alignment = header_alignment
        for index, week in enumerate(weeks):
            month_day = week_day_to_date.get((week, day_short))
            if month_day:
                cell = worksheet.cell(row=current_row, column=3 + index, value=month_day[1])
                cell.font = header_font
                cell.alignment = header_alignment
        current_row += 1

        day_start_row = current_row
        day_cell = worksheet.cell(row=current_row, column=1, value=day_full)
        day_cell.font = header_font
        day_cell.alignment = Alignment(text_rotation=90, vertical="center", horizontal="center")

        for pair_number in range(1, 5):
            pair_label = {1: "1-2", 2: "3-4", 3: "5-6", 4: "7-8"}[pair_number]
            time_label = {1: "9.00-10.35", 2: "10.55-12.30", 3: "12.50-14.25", 4: "15.25-17.00"}[pair_number]
            worksheet.cell(row=current_row, column=2, value=pair_label).font = Font(size=8, bold=True)
            worksheet.cell(row=current_row, column=2).alignment = header_alignment
            worksheet.cell(row=current_row + 1, column=2, value=time_label).font = Font(size=7)
            worksheet.cell(row=current_row + 1, column=2).alignment = header_alignment
            worksheet.merge_cells(
                start_row=current_row,
                start_column=2,
                end_row=current_row + 2,
                end_column=2,
            )

            for index, week in enumerate(weeks):
                item = grid.get((teacher_name, week, day_short, pair_number))
                if not item:
                    continue
                cells = [
                    worksheet.cell(row=current_row, column=3 + index, value=item.get("type") or ""),
                    worksheet.cell(row=current_row + 1, column=3 + index, value=item.get("subject") or ""),
                    worksheet.cell(
                        row=current_row + 2,
                        column=3 + index,
                        value=(
                            f"{item.get('room')} ({', '.join(map(str, item.get('groups') or []))})"
                            if item.get("room")
                            else ", ".join(map(str, item.get("groups") or []))
                        ),
                    ),
                ]
                for cell in cells:
                    cell.font = Font(size=8)
                    cell.alignment = Alignment(wrap_text=True, horizontal="center", vertical="center")
                item_type = str(item.get("type") or "")
                lesson_type = item_type.split("/")[0] if "/" in item_type else item_type
                if lesson_type in fills:
                    for row_offset in range(3):
                        worksheet.cell(row=current_row + row_offset, column=3 + index).fill = fills[lesson_type]
            current_row += 3

        worksheet.merge_cells(
            start_row=day_start_row,
            start_column=1,
            end_row=current_row - 1,
            end_column=1,
        )

    for row in range(1, current_row):
        for column in range(1, max(3, 3 + len(weeks))):
            worksheet.cell(row=row, column=column).border = border


def _fallback_workbook(
    transformed_data: Mapping[str, Any],
    teachers: Sequence[Mapping[str, Any]],
    error: BaseException,
) -> openpyxl.Workbook:
    """Preserve parsed data when the presentation exporter encounters a defect."""

    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    worksheet.title = "Восстановленный результат"
    worksheet.append(["Статус", "Основное оформление не создано; данные сохранены в плоской таблице."])
    worksheet.append(["Причина", f"{type(error).__name__}: {error}"])
    worksheet.append([])
    worksheet.append(["Преподаватель", "Пара", "Месяц", "Дата", "Группы", "Вид", "Дисциплина", "Аудитория"])
    grid = transformed_data.get("grid") or {}
    for raw_key, item in sorted(grid.items(), key=lambda entry: tuple(map(str, entry[0]))):
        try:
            teacher, pair_number, month, day = raw_key
        except (TypeError, ValueError):
            teacher, pair_number, month, day = str(raw_key), "", "", ""
        worksheet.append([
            teacher,
            pair_number,
            month,
            day,
            ", ".join(map(str, item.get("groups") or [])),
            item.get("type") or "",
            item.get("subject") or "",
            item.get("room") or "",
        ])
    if worksheet.max_row == 4:
        worksheet.append(["—", "—", "—", "—", "—", "—", "Данных занятий нет", "—"])
    worksheet.freeze_panes = "A5"
    widths = (30, 10, 16, 12, 26, 16, 45, 24)
    for index, width in enumerate(widths, start=1):
        worksheet.column_dimensions[openpyxl.utils.get_column_letter(index)].width = width
    for cell in worksheet[4]:
        cell.font = Font(bold=True)
    for row in worksheet.iter_rows():
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")

    report = workbook.create_sheet("Состав результата")
    report.append(["Преподаватель", "Полное имя", "Должность", "Звание"])
    for teacher in teachers:
        report.append([
            _teacher_short_name(teacher),
            _teacher_full_name(teacher),
            _teacher_value(teacher, "position"),
            _teacher_value(teacher, "rank"),
        ])
    report.append([])
    report.append([
        "Период",
        json.dumps(transformed_data.get("period_report") or {}, ensure_ascii=False, default=str),
    ])
    report.column_dimensions["A"].width = 34
    report.column_dimensions["B"].width = 70
    report.column_dimensions["C"].width = 28
    report.column_dimensions["D"].width = 22
    for row in report.iter_rows():
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    return workbook


def export_to_excel(
    transformed_data: Dict[str, Any],
    teachers_config: List[Dict[str, Any]],
    output_path: str,
) -> Dict[str, Any]:
    """Write the normal workbook or a data-preserving fallback workbook.

    Only an infrastructure failure while writing the final file is allowed to
    propagate. Formatting defects can no longer leave the operator without a
    downloadable result.
    """

    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    teachers = list(teachers_config or [])
    mode = "normal"
    formatting_error: str | None = None
    try:
        workbook = openpyxl.Workbook()
        summary = workbook.active
        summary.title = "Сводное расписание"
        _apply_summary_header(summary, transformed_data, list(transformed_data.get("dates") or []))
        _fill_summary_rows(summary, 5, teachers, transformed_data)
        for teacher_info in teachers:
            title = _unique_sheet_title(workbook, _teacher_sheet_title(teacher_info))
            worksheet = workbook.create_sheet(title=title)
            _fill_teacher_vertical(worksheet, teacher_info, transformed_data)
    except Exception as exc:  # pragma: no cover - exercised through injected exporter failures
        mode = "fallback"
        formatting_error = f"{type(exc).__name__}: {exc}"
        workbook = _fallback_workbook(transformed_data, teachers, exc)
    workbook.save(destination)
    return {
        "mode": mode,
        "path": str(destination),
        "formatting_error": formatting_error,
        "sheet_count": len(workbook.worksheets),
    }
