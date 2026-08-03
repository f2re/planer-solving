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
