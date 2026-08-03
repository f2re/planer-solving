import json
from pathlib import Path

from src.schedule_analyzer import ScheduleAnalyzer
from src.template_definition import diff_values, normalize_definition
from src.template_matcher import evaluate_layout
from src.workbook_fingerprint import build_workbook_fingerprint, selected_sheet_fingerprint
from tests.test_schedule_analyzer import build_layered_schedule


def test_composite_template_selects_working_component_by_parser_and_fingerprint(tmp_path: Path) -> None:
    workbook = tmp_path / "schedule.xlsx"
    build_layered_schedule(workbook)
    analysis = ScheduleAnalyzer().analyze(str(workbook))
    fingerprint = build_workbook_fingerprint(workbook)
    sheet_fingerprint = selected_sheet_fingerprint(fingerprint, analysis.selected_sheet)
    good_layout = analysis.layout.to_dict()
    bad_layout = {**good_layout, "weeks_row": 1, "grid_start_row": 2}
    definition = normalize_definition({
        "definition_version": 2,
        "components": [
            {
                "id": "bad",
                "label": "Старый формат",
                "selector": {"sheet_name": analysis.selected_sheet},
                "fingerprint": {"title": "Несуществующий", "max_row": 10},
                "layout": bad_layout,
            },
            {
                "id": "good",
                "label": "Актуальный формат",
                "selector": {"sheet_name": analysis.selected_sheet},
                "fingerprint": sheet_fingerprint,
                "layout": good_layout,
            },
        ],
    })
    teachers = tmp_path / "teachers.json"
    teachers.write_text(json.dumps([{
        "id": 1,
        "short_name": "Иванов И.И.",
        "full_name": "Иванов Иван Иванович",
    }], ensure_ascii=False), encoding="utf-8")

    result = evaluate_layout(
        file_path=workbook,
        teachers_path=teachers,
        group_name="522",
        layout=definition,
        source="template",
        name="Составной",
        template_id="template-1",
        available_sheets=analysis.sheet_names,
        fallback_sheet=analysis.selected_sheet,
        workbook_fingerprint=fingerprint,
    )

    assert result["component_id"] == "good"
    assert result["usable"] is True
    assert result["metrics"]["unique_lessons"] > 0
    assert result["fingerprint_similarity"] > 90
    assert len(result["component_results"]) == 2


def test_revision_diff_reports_coordinate_changes() -> None:
    changes = diff_values(
        {"components": [{"layout": {"weeks_row": 7, "first_week_col": 5}}]},
        {"components": [{"layout": {"weeks_row": 8, "first_week_col": 6}}]},
    )
    paths = {item["path"] for item in changes}
    assert "components[0].layout.weeks_row" in paths
    assert "components[0].layout.first_week_col" in paths
