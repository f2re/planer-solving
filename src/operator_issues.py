"""Human-facing, non-blocking issue and resolution contract for schedule processing."""
from __future__ import annotations

import hashlib
from typing import Any, Dict, Iterable, List, Mapping, Sequence


def _code(prefix: str, message: str) -> str:
    digest = hashlib.sha1(message.encode("utf-8"), usedforsecurity=False).hexdigest()[:10]
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
) -> Dict[str, Any]:
    normalized_actions = _actions(actions)
    return {
        "code": code,
        "scope": scope,
        "severity": severity,
        "message": message,
        "default_decision": default_decision,
        "impact": impact,
        "resolved": bool(resolved),
        "resolution": resolution,
        "actions": normalized_actions,
        # Compatibility with the existing recovery panel.
        "action": normalized_actions[0] if normalized_actions else {},
        "blocking": False,
        "source": source,
    }


def _warning_scope(message: str) -> str:
    lowered = message.casefold()
    if "преподавател" in lowered or "не назначен" in lowered:
        return "teacher"
    if "недел" in lowered or "столбц" in lowered or "сетк" in lowered or "размет" in lowered:
        return "range"
    if "месяц" in lowered or "дат" in lowered or "семестр" in lowered or "год" in lowered:
        return "calendar"
    if "лист" in lowered:
        return "sheet"
    return "file"


def _warning_decision(message: str, scope: str) -> tuple[str, str]:
    lowered = message.casefold()
    if scope == "teacher":
        return (
            "Занятие сохраняется в разделе «Не назначен».",
            "Занятие не теряется и может быть назначено преподавателю позже.",
        )
    if "занятия не найдены" in lowered or "недели пока не распознаны" in lowered:
        return (
            "Файл сохраняется в диагностическом результате без блокировки остальных книг.",
            "Из этого файла занятия пока не добавляются; исходник остаётся доступным для правки.",
        )
    if scope == "calendar":
        return (
            "Используется последовательность точных дат, соседних месяцев или период рабочего пространства.",
            "Календарь восстанавливается без остановки формирования и фиксируется в отчёте.",
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


def build_operator_issues(report: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Convert parser details into a stable operator decision model.

    Every returned item is non-blocking and explicitly states the default
    decision. An operator action is an override, not a prerequisite for output.
    """

    result: List[Dict[str, Any]] = []
    used_messages: set[str] = set()
    report_actions = _actions(report.get("actions") or [])

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
            severity="info" if str(raw.get("severity")) == "info" else "attention",
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
        field = str(raw.get("field") or raw.get("type") or "layout")
        result.append(_issue(
            code=f"auto_repair_{field}",
            scope="calendar" if "period" in field else "range",
            severity="info",
            message=reason,
            default_decision="Исправление уже применено к рабочей разметке.",
            impact="Результат рассчитывается по исправленному безопасному варианту.",
            resolution="auto",
            actions=[],
            source="auto_repair",
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
            "file": set(),
        }[scope]
        actions = [action for action in report_actions if not action_types or action.get("type") in action_types]
        result.append(_issue(
            code=(
                "unknown_teacher_mapping"
                if scope == "teacher"
                else _code(scope, message)
            ),
            scope=scope,
            severity="attention",
            message=message,
            default_decision=default_decision,
            impact=impact,
            resolution="default_with_override",
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
    return deduplicated


def attach_operator_issues(report: Dict[str, Any]) -> Dict[str, Any]:
    issues = build_operator_issues(report)
    report["issues"] = issues
    report["resolution_summary"] = {
        "total": len(issues),
        "automatic": sum(item["resolution"] == "auto" for item in issues),
        "attention": sum(item["severity"] == "attention" for item in issues),
        "technical": sum(item["severity"] == "technical" for item in issues),
        "operator_actions": sum(bool(item.get("actions")) for item in issues),
        "blocking": 0,
    }
    report["generation_allowed"] = True
    report["blocking"] = False
    return report
