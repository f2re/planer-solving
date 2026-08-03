from src.template_learning import (
    fingerprint_from_analysis,
    fingerprint_similarity,
    layout_candidates,
    layout_diff,
)


def analysis(sheet_names, rows, columns, weeks_row=7):
    return {
        "sheet_names": sheet_names,
        "max_row": rows,
        "max_column": columns,
        "layout": {
            "sheet_name": sheet_names[0],
            "weeks_row": weeks_row,
            "first_week_col": 5,
            "last_week_col": 25,
            "week_col_step": 1,
            "day_block_rows": 13,
            "pairs_per_day": 4,
            "cell_mode": "row_layers",
            "teacher_source": "both",
            "legend_start_row": 100,
        },
        "diagnostics": [{"code": "legend_found"}],
    }


def test_fingerprint_similarity_prefers_structurally_similar_workbook():
    baseline = fingerprint_from_analysis(analysis(["Расписание"], 180, 30))
    similar = fingerprint_from_analysis(analysis(["Расписание осень"], 185, 31))
    different = fingerprint_from_analysis({
        **analysis(["Другое"], 50, 8),
        "layout": {
            "sheet_name": "Другое",
            "weeks_row": 1,
            "first_week_col": 1,
            "last_week_col": 2,
            "week_col_step": 3,
            "day_block_rows": 5,
            "pairs_per_day": 2,
            "cell_mode": "combined_cell",
            "teacher_source": "schedule",
        },
    })
    assert fingerprint_similarity(baseline, similar) > 0.75
    assert fingerprint_similarity(baseline, different) < 0.55


def test_composite_template_selects_rules_by_sheet_name():
    template = {
        "layout": {"sheet_name": "Основной", "weeks_row": 7},
        "composite": [
            {
                "id": "part-time",
                "name": "Заочная форма",
                "sheet_pattern": "заоч",
                "layout": {"sheet_name": "", "weeks_row": 12},
            },
            {
                "id": "unused",
                "name": "Магистратура",
                "sheet_pattern": "магистр",
                "layout": {"sheet_name": "", "weeks_row": 20},
            },
        ],
    }
    candidates = layout_candidates(template, ["Очная", "Заочное отделение"])
    assert [item["rule_id"] for item in candidates] == ["primary", "part-time"]
    assert candidates[1]["layout"]["sheet_name"] == "Заочное отделение"
    assert layout_diff({"weeks_row": 7}, {"weeks_row": 12}) == [
        {"field": "weeks_row", "before": 7, "after": 12}
    ]
