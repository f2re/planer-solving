from src.operator_issues import attach_operator_issues, group_operator_issues


def test_conflicts_are_grouped_before_normal_calendar_decisions() -> None:
    groups = group_operator_issues([
        {
            "code": "calendar_month_transition",
            "scope": "calendar",
            "category": "calendar",
            "severity": "info",
            "message": "Неделя последовательно переходит с августа на сентябрь.",
            "default_decision": "Переход принят автоматически.",
            "impact": "Формирование продолжается.",
            "resolution": "auto",
            "resolved": True,
            "source": "calendar",
        },
        {
            "code": "teacher_conflicts_unresolved",
            "scope": "teacher",
            "category": "conflict",
            "severity": "problem",
            "priority": 100,
            "message": "Один преподаватель назначен на два разных занятия.",
            "default_decision": "Одно занятие оставлено без назначения.",
            "impact": "Двойная занятость не скрывается.",
            "resolution": "unresolved",
            "resolved": False,
            "source": "teacher_assignment",
        },
    ])

    assert [group["category"] for group in groups] == ["conflict", "calendar"]
    assert groups[0]["requires_action"] is True
    assert groups[1]["requires_action"] is False


def test_duplicate_notices_are_collapsed_inside_semantic_group() -> None:
    issue = {
        "code": "calendar_month_transition",
        "scope": "calendar",
        "category": "calendar",
        "severity": "info",
        "message": "Последовательная смена месяца принята автоматически.",
        "default_decision": "Использовать фактическую последовательность дат.",
        "impact": "Формирование не блокируется.",
        "resolution": "auto",
        "resolved": True,
        "source": "calendar",
    }

    groups = group_operator_issues([issue, dict(issue)])

    assert len(groups) == 1
    assert groups[0]["count"] == 1
    assert len(groups[0]["items"]) == 1


def test_report_contains_stable_groups_and_no_blocking_flag() -> None:
    report = attach_operator_issues({
        "warnings": ["Преподаватель «Иванов» неоднозначен: Иванов И.И., Иванов П.П."],
        "errors": [],
        "actions": [{
            "type": "open_teacher_mapping",
            "label": "Уточнить преподавателя",
        }],
    })

    assert report["generation_allowed"] is True
    assert report["blocking"] is False
    assert report["issue_groups"]
    assert report["issue_groups"][0]["category"] == "teacher"
