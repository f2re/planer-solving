"""Human-facing issue, priority and resolution contract for schedule processing."""
from __future__ import annotations

import hashlib
from typing import Any, Dict, Iterable, List, Mapping, Sequence


GROUP_META = {
    "conflict": {
        "title": "Конфликты занятий",
        "priority": 100,
        "summary": "Коллизии преподавателей или занятий требуют первоочередной проверки.",
    },
    "technical": {
        "title": "Технические сбои",
        "priority": 90,
        "summary": "Система сохранила пригодные данные и изолировала технический отказ.",
    },
    "teacher": {
        "title": "Преподаватели",
        "priority": 80,
        "summary": "Назначения преподавателей можно уточнить без повторной загрузки.",
    },
    "layout": {
        "title": "Разметка",
        "priority": 60,
        "summary": "Координаты и области листа восстановлены либо требуют уточнения.",
    },
    "file": {
        "title": "Исходные файлы",
        "priority": 50,
        "summary": "Замечания относятся к отдельным книгам или листам.",
    },
    "export": {
        "title": "Формирование файлов",
        "priority": 40,
        "summary": "Основной результат сохранён; дополнительный формат может требовать внимания.",
    },
    "calendar": {
        "title": "Даты и календарь",
        "priority": 20,
        "summary": "Последовательные даты и смена месяца являются нормальными автоматическими решениями.",
    },
    "information": {
        "title": "Автоматические решения",
        "priority": 10,
        "summary": "Система уже применила безопасные решения; действий не требуется.",
    },
}


def _code(prefix: str, message: str) -> str:
    digest = hashlib.sha1(message.encode("utf-8")).hexdigest()[:10]
    return f"{prefix}_{digest}"


def _actions(values: Iterable[Any]) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    for value in values:
        if not isinstance(value, Mapping) or not value:
            continue
        action = dict(value)
        action["blocking"] = False
        if action not in result:
            result.append(action)
    return result


def _category(scope: str, message: str, source: str = "", code: str = "") -> str:
    lowered = f"{message} {source} {code}".casefold()
    if "конфликт" in lowered or "коллиз" in lowered or "двойн" in lowered:
        return "conflict"
    if source == "teacher_assignment" and "resolved" not in code:
        return "conflict"
    if scope == "teacher":
        return "teacher"
    if scope == "calendar":
        return "calendar"
    if scope == "range":
        return "layout"
    if scope in {"sheet", "file"}:
        return "file"
    if scope == "export":
        return "export"
    if "техничес" in lowered or "не удалось открыть" in lowered:
        return "technical"
    return "information"


def _priority(category: str, severity: str) -> int:
    base = int(GROUP_META.get(category, GROUP_META["information"])["priority"])
    return base + {
        "problem": 20,
        "technical": 15,
        "attention": 5,
        "warning": 5,
        "info": 0,
    }.get(str(severity), 0)


def _issue(
    *,
    code: str,
    scope: str,
    severity: str,
    message: str,
    default_decision: str,
    impact: str,
    resolution: str,
    actions: Sequence[Mapping[str, Any]] = (),
    resolved: bool = True,
    source: str = "parser",
    category: str | None = None,
    priority: int | None = None,
    items: Sequence[Mapping[str, Any]] = (),
) -> Dict[str, Any]:
    normalized_actions = _actions(actions)
    normalized_category = category or _category(scope, message, source, code)
    normalized_priority = int(
        priority if priority is not None else _priority(normalized_category, severity)
    )
    return {
        "code": code,
        "scope": scope,
        "category": normalized_category,
        "severity": severity,
        "priority": normalized_priority,
        "message": message,
        "default_decision": default_decision,
        "impact": impact,
        "resolved": bool(resolved),
        "resolution": resolution,
        "actions": normalized_actions,
        "action": normalized_actions[0] if normalized_actions else {},
        "blocking": False,
        "source": source,
        "items": [dict(item) for item in items],
    }


def _warning_scope(message: str) -> str:
    lowered = message.casefold()
    if "конфликт" in lowered or "коллиз" in lowered:
        return "teacher"
    if "преподавател" in lowered or "не назначен" in lowered:
        return "teacher"
    if "недел" in lowered or "столбц" in lowered or "сетк" in lowered or "размет" in lowered:
        return "range"
    if "месяц" in lowered or "дат" in lowered or "семестр" in lowered or "год" in lowered:
        return "calendar"
    if "лист" in lowered:
        return "sheet"
    if "экспорт" in lowered or "файл не сформирован" in lowered:
        return "export"
    return "file"


def _warning_decision(message: str, scope: str) -> tuple[str, str]:
    lowered = message.casefold()
    if "предварительная коллизия" in lowered:
        return (
            "Коллизия передана общему графу назначений.",
            "Окончательный преподаватель определяется после разбора всех файлов.",
        )
    if scope == "teacher":
        return (
            "Занятие сохраняется в разделе «Не назначен» только когда свободного допустимого преподавателя нет.",
            "Занятие не теряется и не скрывается под двойной занятостью.",
        )
    if "занятия не найдены" in lowered or "недели пока не распознаны" in lowered:
        return (
            "Файл сохраняется в диагностическом результате без блокировки остальных книг.",
            "Из этого файла занятия пока не добавляются; исходник остаётся доступным для правки.",
        )
    if scope == "calendar":
        return (
            "Используется фактическая последовательность дат, включая нормальную смену месяца.",
            "Календарь восстанавливается без остановки формирования и фиксируется как информационное решение.",
        )
    if scope in {"range", "sheet"}:
        return (
            "Используется безопасная нормализованная разметка.",
            "Пригодные занятия включаются; сомнительные области остаются доступными для уточнения.",
        )
    return (
        "Система продолжает обработку пригодных данных.",
        "Замечание записывается в отчёт и не блокирует остальные файлы.",
    )


def normalize_operator_issue(raw: Mapping[str, Any]) -> Dict[str, Any]:
    """Normalize externally produced issues, including assignment-graph output."""

    message = str(raw.get("message") or "").strip()
    scope = str(raw.get("scope") or "file")
    severity = str(raw.get("severity") or "attention")
    code = str(raw.get("code") or _code(scope, message))
    source = str(raw.get("source") or "parser")
    category = str(raw.get("category") or _category(scope, message, source, code))
    return _issue(
        code=code,
        scope=scope,
        category=category,
        severity=severity,
        priority=int(raw.get("priority") or _priority(category, severity)),
        message=message,
        default_decision=str(raw.get("default_decision") or "Применено безопасное решение."),
        impact=str(raw.get("impact") or "Формирование не блокируется."),
        resolution=str(raw.get("resolution") or "default_with_override"),
        actions=raw.get("actions") or ([raw.get("action")] if raw.get("action") else []),
        resolved=bool(raw.get("resolved", True)),
        source=source,
        items=raw.get("items") or [],
    )


def group_operator_issues(issues: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Group repeated notices by business meaning and order real problems first."""

    buckets: Dict[str, Dict[str, Any]] = {}
    fingerprints: Dict[str, set[tuple[str, str]]] = {}
    for raw in issues:
        if not isinstance(raw, Mapping) or not str(raw.get("message") or "").strip():
            continue
        item = normalize_operator_issue(raw)
        category = item["category"]
        meta = GROUP_META.get(category, GROUP_META["information"])
        group = buckets.setdefault(category, {
            "id": category,
            "category": category,
            "title": meta["title"],
            "summary": meta["summary"],
            "priority": int(meta["priority"]),
            "severity": "info",
            "count": 0,
            "requires_action": False,
            "items": [],
        })
        fingerprint = (item["code"], item["message"])
        seen = fingerprints.setdefault(category, set())
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        group["items"].append(item)
        group["count"] += 1
        group["priority"] = max(group["priority"], int(item["priority"]))
        group["requires_action"] = bool(
            group["requires_action"]
            or not item["resolved"]
            or item["severity"] in {"problem", "technical"}
            or item.get("actions")
        )
        severity_order = {"info": 0, "attention": 1, "warning": 1, "technical": 2, "problem": 3}
        if severity_order.get(item["severity"], 1) > severity_order.get(group["severity"], 0):
            group["severity"] = item["severity"]

    for group in buckets.values():
        group["items"].sort(
            key=lambda item: (-int(item["priority"]), item["message"].casefold())
        )
        if group["count"] > 1:
            group["label"] = f"{group['title']} — {group['count']}"
        else:
            group["label"] = group["title"]
    return sorted(
        buckets.values(),
        key=lambda group: (-int(group["priority"]), group["title"].casefold()),
    )


def build_operator_issues(report: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Convert parser details into a stable, non-blocking decision model."""

    result: List[Dict[str, Any]] = []
    used_messages: set[str] = set()
    report_actions = _actions(report.get("actions") or [])

    for raw in report.get("assignment_issues") or []:
        if isinstance(raw, Mapping) and raw.get("message"):
            item = normalize_operator_issue(raw)
            result.append(item)
            used_messages.add(item["message"])

    for raw in (report.get("period") or {}).get("issues") or []:
        if not isinstance(raw, Mapping):
            continue
        message = str(raw.get("message") or "").strip()
        if not message:
            continue
        raw_resolution = str(raw.get("resolution") or "review")
        automatic = raw_resolution == "auto"
        action = raw.get("action") if isinstance(raw.get("action"), Mapping) else None
        result.append(_issue(
            code=str(raw.get("code") or _code("calendar", message)),
            scope="calendar",
            category="calendar",
            severity="info" if automatic or str(raw.get("severity")) == "info" else "attention",
            message=message,
            default_decision=(
                "Календарное решение уже принято автоматически по фактической последовательности дат."
                if automatic
                else "До ручного уточнения используется безопасная календарная последовательность."
            ),
            impact="Формирование не блокируется; выбранный календарь записывается в отчёт.",
            resolution="auto" if automatic else "default_with_override",
            actions=[action] if action else [],
            source="calendar",
        ))
        used_messages.add(message)

    for raw in report.get("auto_repairs") or []:
        if not isinstance(raw, Mapping):
            continue
        reason = str(raw.get("reason") or "Координаты нормализованы автоматически.").strip()
        repair_type = str(raw.get("type") or "layout")
        field = str(raw.get("field") or repair_type)
        operator_decision = repair_type == "teacher_override"
        scope = (
            "teacher" if operator_decision
            else "calendar" if "period" in field
            else "range"
        )
        result.append(_issue(
            code=f"{'operator' if operator_decision else 'auto_repair'}_{field}",
            scope=scope,
            severity="info",
            message=reason,
            default_decision=(
                "Ручное назначение оператора применено."
                if operator_decision
                else "Исправление уже применено к рабочей разметке."
            ),
            impact=(
                "Занятия дисциплины попадут в расписание выбранного преподавателя; решение сохранится в истории."
                if operator_decision
                else "Результат рассчитывается по исправленному безопасному варианту."
            ),
            resolution="operator" if operator_decision else "auto",
            actions=[],
            source="operator" if operator_decision else "auto_repair",
        ))

    for message_value in report.get("errors") or []:
        message = str(message_value).strip()
        if not message or message in used_messages:
            continue
        actions = [
            action for action in report_actions
            if action.get("type") in {"replace_file", "edit_layout", "retry", "download_diagnostics"}
        ] or report_actions[:1]
        result.append(_issue(
            code=_code("technical", message),
            scope="file",
            category="technical",
            severity="technical",
            message=message,
            default_decision="Этот файл или фрагмент исключается; остальные исходники продолжают обрабатываться.",
            impact="Доступные данные попадут в результат, а отказ будет сохранён в диагностике.",
            resolution="skipped_with_override",
            actions=actions,
            source="technical",
        ))
        used_messages.add(message)

    for message_value in report.get("warnings") or []:
        message = str(message_value).strip()
        if not message or message in used_messages:
            continue
        scope = _warning_scope(message)
        default_decision, impact = _warning_decision(message, scope)
        action_types = {
            "teacher": {"open_teacher_mapping"},
            "calendar": {"edit_period", "calendar_policy"},
            "range": {"edit_layout", "layout_patch"},
            "sheet": {"edit_layout", "layout_patch", "replace_file"},
            "export": set(),
            "file": set(),
        }[scope]
        actions = [action for action in report_actions if not action_types or action.get("type") in action_types]
        category = _category(scope, message)
        severity = (
            "info"
            if category == "calendar" or "предварительная коллизия" in message.casefold()
            else "attention"
        )
        result.append(_issue(
            code=(
                "unknown_teacher_mapping"
                if scope == "teacher" and category != "conflict"
                else _code(category, message)
            ),
            scope=scope,
            category=category,
            severity=severity,
            message=message,
            default_decision=default_decision,
            impact=impact,
            resolution="auto" if severity == "info" else "default_with_override",
            actions=actions[:2],
            source="parser",
        ))
        used_messages.add(message)

    represented_actions = {
        str(action.get("type"))
        for issue in result
        for action in issue.get("actions") or []
    }
    for action in report_actions:
        action_type = str(action.get("type") or "operator_action")
        if action_type in represented_actions:
            continue
        label = str(action.get("label") or "Уточнить решение")
        result.append(_issue(
            code=f"action_{action_type}",
            scope="teacher" if action_type == "open_teacher_mapping" else "file",
            severity="attention",
            message=label,
            default_decision="Система уже использует безопасный вариант; это действие позволяет его изменить.",
            impact="Без ручного действия результат всё равно формируется и содержит принятое решение.",
            resolution="default_with_override",
            actions=[action],
            source="operator_action",
        ))

    deduplicated: List[Dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in result:
        key = (str(item["code"]), str(item["message"]))
        if key in seen:
            continue
        seen.add(key)
        deduplicated.append(item)
    deduplicated.sort(key=lambda item: (-int(item["priority"]), item["message"].casefold()))
    return deduplicated


def attach_operator_issues(report: Dict[str, Any]) -> Dict[str, Any]:
    issues = build_operator_issues(report)
    report["issues"] = issues
    report["issue_groups"] = group_operator_issues(issues)
    report["resolution_summary"] = {
        "total": len(issues),
        "automatic": sum(item["resolution"] == "auto" for item in issues),
        "operator": sum(item["resolution"] == "operator" for item in issues),
        "attention": sum(item["severity"] in {"attention", "warning"} for item in issues),
        "problems": sum(item["severity"] in {"problem", "technical"} for item in issues),
        "technical": sum(item["severity"] == "technical" for item in issues),
        "operator_actions": sum(bool(item.get("actions")) for item in issues),
        "groups": len(report["issue_groups"]),
        "blocking": 0,
    }
    report["generation_allowed"] = True
    report["blocking"] = False
    return report
