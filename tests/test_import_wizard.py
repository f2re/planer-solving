from src.import_wizard import (
    classify_teachers,
    parse_rows,
    suggest_teacher_mapping,
)


def test_csv_preview_detects_headers_mapping_and_conflicts():
    payload = (
        "Служебная строка;;;;\n"
        "Полное ФИО;Краткое имя;Должность;Звание;Степень\n"
        "Иванов Иван Иванович;Иванов И.И.;Профессор;;д.т.н.\n"
        "Петров Петр Петрович;Петров П.П.;Доцент;;к.т.н.\n"
        "Петров Петр Петрович;Петров П.П.;Доцент;;к.т.н.\n"
    ).encode("utf-8")
    source = parse_rows(payload, "teachers.csv")
    mapping = suggest_teacher_mapping(source["headers"])
    preview = classify_teachers(
        source["rows"],
        mapping,
        [{
            "id": 1,
            "short_name": "Иванов И.И.",
            "full_name": "Иванов Иван Иванович",
            "position": "Доцент",
            "rank": "",
            "academic_degree": "к.т.н.",
        }],
    )

    assert source["header_row"] == 2
    assert mapping["full_name"] == "Полное ФИО"
    assert preview["counts"] == {
        "add": 1,
        "update": 1,
        "duplicate": 0,
        "conflict": 1,
        "invalid": 0,
    }
    assert preview["rows"][0]["decision"] == "merge"
    assert preview["rows"][1]["decision"] == "add"
    assert preview["rows"][2]["decision"] == "skip"


def test_json_preview_accepts_nonstandard_columns_after_manual_mapping():
    payload = b'''[
      {"person": "Sidorov Sidor Sidorovich", "job": "Engineer"}
    ]'''
    source = parse_rows(payload, "teachers.json")
    preview = classify_teachers(
        source["rows"],
        {"full_name": "person", "position": "job"},
        [],
    )
    assert preview["counts"]["add"] == 1
    assert preview["rows"][0]["teacher"]["short_name"].startswith("Sidorov")
