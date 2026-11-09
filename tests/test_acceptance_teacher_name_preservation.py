"""Acceptance tests for teacher name preservation ('е' vs 'ё') and full schedule generation."""
import json
from pathlib import Path
import openpyxl
import pytest

from src.data_loader import DataLoader, Lesson
from src.schedule_analyzer import ScheduleAnalyzer
from src.transformer import transform_to_teacher_grid
from src.exporter import export_to_excel
from src.weekly_exporter import generate_weekly_semester_schedule
from src.teacher_assignment import resolve_teacher_collisions


@pytest.mark.skipif(not Path("obrazec/11161.xlsx").exists(), reason="obrazec samples required for acceptance test")
def test_acceptance_db_has_yo_schedule_has_e(tmp_path: Path):
    """Scenario 1: Database has 'ё' (Соловьёв), schedule sample file has 'е' (Соловьев)."""
    with open("teachers.json", encoding="utf-8") as f:
        teachers_raw = json.load(f)

    teachers_yo = []
    for t in teachers_raw:
        item = dict(t)
        if "Соловьев" in item["short_name"]:
            item["short_name"] = item["short_name"].replace("Соловьев", "Соловьёв")
            item["full_name"] = item["full_name"].replace("Соловьев", "Соловьёв")
        teachers_yo.append(item)

    teachers_yo_file = tmp_path / "teachers_yo.json"
    teachers_yo_file.write_text(json.dumps(teachers_yo, ensure_ascii=False, indent=2), encoding="utf-8")

    source_path = "obrazec/11161.xlsx"
    analysis = ScheduleAnalyzer().analyze(source_path)
    loader = DataLoader(str(teachers_yo_file))
    lessons = loader.load_group_schedule(source_path, "11161", analysis.layout)

    # All 22 lessons must be canonicalized to 'Соловьёв'
    solovyov_lessons = [l for l in lessons if l.teacher == "Соловьёв"]
    assert len(solovyov_lessons) == 22
    assert not any(l.teacher == "Соловьев" for l in lessons)

    start_date = "2026-05-18"
    end_date = "2026-06-21"
    grid_data = transform_to_teacher_grid(
        lessons,
        teachers_yo,
        start_date_str=start_date,
        end_date_str=end_date,
    )

    out_excel = tmp_path / "schedule_11161_yo.xlsx"
    export_result = export_to_excel(grid_data, teachers_yo, str(out_excel))
    assert export_result["mode"] == "normal"

    wb = openpyxl.load_workbook(out_excel)
    assert "Соловьёв А.П." in wb.sheetnames

    # Check individual sheet has lessons
    ws_solovyov = wb["Соловьёв А.П."]
    cell_contents = [
        c for r in ws_solovyov.iter_rows(values_only=True)
        for c in r if c and isinstance(c, str) and ("11161" in c or "Л" in c or "П" in c)
    ]
    assert len(cell_contents) > 0

    # Check summary sheet has canonical 'Соловьёв Алексей Павлович'
    summary_name = "Сводное расписание" if "Сводное расписание" in wb.sheetnames else "Сводная таблица"
    ws_summary = wb[summary_name]
    solovyov_rows = [
        r for r in range(1, ws_summary.max_row + 1)
        if ws_summary.cell(row=r, column=4).value and "Соловьёв" in str(ws_summary.cell(row=r, column=4).value)
    ]
    assert len(solovyov_rows) > 0
    sol_row = solovyov_rows[0]
    assert "Соловьёв Алексей Павлович" in str(ws_summary.cell(row=sol_row, column=4).value)

    # Check weekly schedule export
    template_weekly = "obrazec/Недельное.xlsx"
    out_weekly = tmp_path / "weekly_11161_yo.xlsx"
    generate_weekly_semester_schedule(
        teachers_config=teachers_yo,
        lessons=lessons,
        template_path=template_weekly,
        output_path=str(out_weekly),
        start_date_str=start_date,
        end_date_str=end_date,
    )

    wb_weekly = openpyxl.load_workbook(out_weekly)
    assert len(wb_weekly.sheetnames) > 0
    weekly_solovyov_lessons = 0
    for sheet_name in wb_weekly.sheetnames:
        ws_week = wb_weekly[sheet_name]
        for r in range(13, ws_week.max_row + 1):
            t_val = ws_week.cell(row=r, column=3).value
            if t_val and "Соловьёв" in str(t_val):
                for pr in range(r, r + 4):
                    for c in range(5, 11):
                        if ws_week.cell(row=pr, column=c).value:
                            weekly_solovyov_lessons += 1
    assert weekly_solovyov_lessons == 22


@pytest.mark.skipif(not Path("obrazec/11161.xlsx").exists(), reason="obrazec samples required for acceptance test")
def test_acceptance_db_has_e_schedule_has_yo(tmp_path: Path):
    """Scenario 2: Database has 'е' (Соловьев), schedule file has 'ё' (Соловьёв)."""
    with open("teachers.json", encoding="utf-8") as f:
        teachers_e = json.load(f)

    teachers_e_file = tmp_path / "teachers_e.json"
    teachers_e_file.write_text(json.dumps(teachers_e, ensure_ascii=False, indent=2), encoding="utf-8")

    # Create schedule file with 'ё'
    wb_source = openpyxl.load_workbook("obrazec/11161.xlsx")
    ws_src = wb_source.active
    for row in ws_src.iter_rows():
        for cell in row:
            if cell.value and isinstance(cell.value, str) and "Соловьев" in cell.value:
                cell.value = cell.value.replace("Соловьев", "Соловьёв")
    schedule_yo_file = tmp_path / "11161_yo.xlsx"
    wb_source.save(schedule_yo_file)

    analysis_e = ScheduleAnalyzer().analyze(str(schedule_yo_file))
    loader_e = DataLoader(str(teachers_e_file))
    lessons_e = loader_e.load_group_schedule(str(schedule_yo_file), "11161", analysis_e.layout)

    solovyov_e = [l for l in lessons_e if l.teacher == "Соловьев"]
    assert len(solovyov_e) == 22
    assert not any(l.teacher == "Соловьёв" for l in lessons_e)

    start_date = "2026-05-18"
    end_date = "2026-06-21"
    grid_data_e = transform_to_teacher_grid(
        lessons_e,
        teachers_e,
        start_date_str=start_date,
        end_date_str=end_date,
    )
    out_excel_e = tmp_path / "schedule_11161_e.xlsx"
    export_to_excel(grid_data_e, teachers_e, str(out_excel_e))

    wb_e = openpyxl.load_workbook(out_excel_e)
    assert "Соловьев А.П." in wb_e.sheetnames
    ws_sol_e = wb_e["Соловьев А.П."]
    cell_contents_e = [
        c for r in ws_sol_e.iter_rows(values_only=True)
        for c in r if c and isinstance(c, str) and "11161" in c
    ]
    assert len(cell_contents_e) > 0


@pytest.mark.skipif(not Path("obrazec/Недельное.xlsx").exists(), reason="obrazec/Недельное.xlsx required for acceptance test")
def test_acceptance_multiple_teachers_with_yo(tmp_path: Path):
    """Scenario 3: Multiple teachers with 'ё' (Королёв, Фёдоров, Соловьёв)."""
    teachers_multi = [
        {"id": 1, "short_name": "Королёв И.И.", "full_name": "Королёв Иван Иванович", "rank": "доцент", "position": "Доцент"},
        {"id": 2, "short_name": "Фёдоров Ф.Ф.", "full_name": "Фёдоров Фёдор Фёдорович", "rank": "профессор", "position": "Профессор"},
        {"id": 3, "short_name": "Соловьёв А.П.", "full_name": "Соловьёв Алексей Павлович", "rank": "-", "position": "Старший преподаватель"},
    ]

    lessons_multi = [
        Lesson(group="301", subject="Физика", lesson_type_code="Л", room="101", week=1, day_of_week="Пн", pair_num=1, teacher="Королев И.И.", date_day=2, month="Февраль"),
        Lesson(group="301", subject="Математика", lesson_type_code="П", room="102", week=1, day_of_week="Вт", pair_num=2, teacher="Федоров Ф.Ф.", date_day=3, month="Февраль"),
        Lesson(group="302", subject="Химия", lesson_type_code="Л", room="103", week=1, day_of_week="Ср", pair_num=3, teacher="Соловьев А.П.", date_day=4, month="Февраль"),
        Lesson(group="303", subject="Астрономия", lesson_type_code="Л", room="104", week=1, day_of_week="Чт", pair_num=1, teacher="Королев", date_day=5, month="Февраль"),
    ]

    resolve_teacher_collisions(
        lessons_multi,
        teachers_multi,
        candidate_catalog={
            "Физика": {"lecturer": ["Королев И.И."]},
            "Математика": {"other": ["Федоров Ф.Ф."]},
            "Химия": {"lecturer": ["Соловьев А.П."]},
            "Астрономия": {"lecturer": ["Королев И.И."]},
        }
    )

    for l in lessons_multi:
        assert "ё" in l.teacher
        assert l.teacher in ["Королёв И.И.", "Фёдоров Ф.Ф.", "Соловьёв А.П."]

    grid_multi = transform_to_teacher_grid(
        lessons_multi,
        teachers_multi,
        start_date_str="2026-02-02",
        end_date_str="2026-02-08",
    )
    out_excel_multi = tmp_path / "schedule_multi_yo.xlsx"
    export_to_excel(grid_multi, teachers_multi, str(out_excel_multi))

    wb_multi = openpyxl.load_workbook(out_excel_multi)
    assert "Королёв И.И." in wb_multi.sheetnames
    assert "Фёдоров Ф.Ф." in wb_multi.sheetnames
    assert "Соловьёв А.П." in wb_multi.sheetnames

    template_weekly = "obrazec/Недельное.xlsx"
    out_weekly_multi = tmp_path / "weekly_multi_yo.xlsx"
    generate_weekly_semester_schedule(
        teachers_config=teachers_multi,
        lessons=lessons_multi,
        template_path=template_weekly,
        output_path=str(out_weekly_multi),
        start_date_str="2026-02-02",
        end_date_str="2026-02-08",
    )
    wb_w_multi = openpyxl.load_workbook(out_weekly_multi)
    ws_w1 = wb_w_multi["Неделя 1"]
    t_col3 = [ws_w1.cell(row=r, column=3).value for r in range(13, ws_w1.max_row + 1) if ws_w1.cell(row=r, column=3).value]
    assert "Королёв И.И." in t_col3
    assert "Фёдоров Ф.Ф." in t_col3
    assert "Соловьёв А.П." in t_col3

    weekly_lessons_found = sum(
        1 for r in range(13, ws_w1.max_row + 1)
        for c in range(5, 11)
        if ws_w1.cell(row=r, column=c).value
    )
    assert weekly_lessons_found == 4
