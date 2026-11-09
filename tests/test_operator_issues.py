from src.operator_issues import attach_operator_issues, build_operator_issues
from web.backend.schemas import ScheduleUploadResponse, ValidateLayoutResponse


def test_every_operator_issue_has_default_resolution() -> None:
    report = {
        "file": "group.xlsx",
        "warnings": [
            "Для 3 занятий преподаватель не определён; они попадут в раздел «Не назначен».",
            "По текущей разметке занятия не найдены.",
        ],
        "errors": ["Не удалось открыть дополнительный лист."],
        "actions": [
            {"type": "open_teacher_mapping", "label": "Уточнить преподавателей"},
            {"type": "edit_layout", "label": "Указать сетку занятий"},
            {"type": "replace_file", "label": "Заменить файл"},
        ],
        "period": {
            "issues": [{
                "severity": "info",
                "code": "week_month_transition",
                "message": "Неделя переходит из января в февраль; даты приняты автоматически.",
                "resolution": "auto",
                "action": {},
            }]
        },
        "auto_repairs": [{
            "type": "layout_patch",
            "field": "sheet_name",
            "reason": "Выбран существующий лист книги.",
        }],
    }

    issues = build_operator_issues(report)

    assert issues
    assert all(issue["blocking"] is False for issue in issues)
    assert all(issue["default_decision"] for issue in issues)
    assert all(issue["impact"] for issue in issues)
    assert all(issue["resolution"] for issue in issues)
    assert any(issue["code"] == "unknown_teacher_mapping" for issue in issues)
    assert any(issue["severity"] == "technical" for issue in issues)
    transition = next(issue for issue in issues if issue["code"] == "week_month_transition")
    assert transition["resolution"] == "auto"
    assert transition["severity"] == "info"


def test_attached_summary_is_explicitly_nonblocking() -> None:
    report = attach_operator_issues({
        "warnings": ["Месяцы не распознаны."],
        "errors": [],
        "actions": [{"type": "calendar_policy", "label": "Использовать период пространства"}],
        "period": {},
        "auto_repairs": [],
    })

    assert report["generation_allowed"] is True
    assert report["blocking"] is False
    assert report["resolution_summary"]["blocking"] == 0
    assert report["resolution_summary"]["total"] == len(report["issues"])


def test_api_response_models_attach_issue_contract() -> None:
    validation = ValidateLayoutResponse(
        status="warning",
        report={
            "warnings": ["Для занятия преподаватель не определён."],
            "errors": [],
            "actions": [{"type": "open_teacher_mapping", "label": "Уточнить преподавателя"}],
            "period": {},
            "auto_repairs": [],
        },
    )
    assert validation.report["issues"][0]["default_decision"]
    assert validation.report["generation_allowed"] is True

    generated = ScheduleUploadResponse(
        status="warning",
        message="Результат создан.",
        reports=[{
            "warnings": ["По текущей разметке занятия не найдены."],
            "errors": [],
            "actions": [{"type": "edit_layout", "label": "Указать сетку"}],
            "period": {},
            "auto_repairs": [],
        }],
    )
    assert generated.reports[0]["issues"]
    assert generated.reports[0]["blocking"] is False


def test_teacher_issue_inherits_unknown_subjects_and_candidates() -> None:
    report = {
        "file": "test.xlsx",
        "unknown_teacher_lessons": 3,
        "unknown_subjects": ["Физика"],
        "teacher_candidates": {
            "Физика": {"lecturer": ["Сидоров С.С."], "practice": ["Петров П.П."], "reserve": []}
        },
        "warnings": [
            "Для 3 занятий преподаватель не определён; они попадут в раздел «Не назначен»."
        ],
        "actions": [
            {
                "type": "open_teacher_mapping",
                "label": "Уточнить преподавателей",
            }
        ],
    }
    issues = build_operator_issues(report)
    teacher_issues = [i for i in issues if i["code"] == "unknown_teacher_mapping" or i["scope"] == "teacher"]
    assert teacher_issues, "Expected unknown_teacher_mapping issue"
    issue = teacher_issues[0]

    # Primary action must inherit subject, unknown_subjects, candidates
    action = issue["action"]
    assert action["type"] == "open_teacher_mapping"
    assert action["subject"] == "Физика"
    assert action["unknown_subjects"] == ["Физика"]
    assert action["candidates"] == {
        "Физика": {"lecturer": ["Сидоров С.С."], "practice": ["Петров П.П."], "reserve": []}
    }
    assert action["blocking"] is False

    # Actions list should include both general and discipline-specific action
    actions = issue["actions"]
    assert len(actions) >= 2
    disc_action = next((a for a in actions if a["label"] == "Уточнить: Физика"), None)
    assert disc_action is not None
    assert disc_action["subject"] == "Физика"
    assert disc_action["candidates"] == {
        "Физика": {"lecturer": ["Сидоров С.С."], "practice": ["Петров П.П."], "reserve": []}
    }


def test_teacher_issue_multiple_unknown_subjects_generates_discipline_actions() -> None:
    report = {
        "file": "multi.xlsx",
        "unknown_teacher_lessons": 5,
        "unknown_subjects": ["Алгебра", "Геометрия"],
        "teacher_candidates": {
            "Алгебра": {"lecturer": ["Иванов И.И."]},
            "Геометрия": {"lecturer": ["Кузнецов К.К."]},
        },
        "warnings": [
            "Для 5 занятий преподаватель не определён; они попадут в раздел «Не назначен»."
        ],
    }
    issues = build_operator_issues(report)
    issue = next(i for i in issues if i["code"] == "unknown_teacher_mapping")

    # Main action has empty subject because multiple disciplines are unknown
    main_action = issue["actions"][0]
    assert main_action["subject"] == ""
    assert main_action["unknown_subjects"] == ["Алгебра", "Геометрия"]
    assert "Уточнить преподавателей (5 не назначено)" in main_action["label"]
    assert "Алгебра" in main_action["candidates"]
    assert "Геометрия" in main_action["candidates"]

    # Must have specific actions for each discipline
    labels = [a["label"] for a in issue["actions"]]
    assert "Уточнить: Алгебра" in labels
    assert "Уточнить: Геометрия" in labels

    algebra_action = next(a for a in issue["actions"] if a["subject"] == "Алгебра")
    assert algebra_action["candidates"] == {"Алгебра": {"lecturer": ["Иванов И.И."]}}
    assert algebra_action["unknown_subjects"] == ["Алгебра"]

    geometry_action = next(a for a in issue["actions"] if a["subject"] == "Геометрия")
    assert geometry_action["candidates"] == {"Геометрия": {"lecturer": ["Кузнецов К.К."]}}
    assert geometry_action["unknown_subjects"] == ["Геометрия"]
