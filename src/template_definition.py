"""Composite template definitions, fingerprints and revision comparison helpers."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re
from typing import Any, Dict, Iterable, List, Mapping, Sequence
import uuid

TEMPLATE_DEFINITION_VERSION = 2


def _normalized_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().casefold().replace("ё", "е"))


def stable_hash(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def is_composite_definition(value: Any) -> bool:
    return (
        isinstance(value, Mapping)
        and int(value.get("definition_version", 0) or 0) >= TEMPLATE_DEFINITION_VERSION
        and isinstance(value.get("components"), list)
    )


def wrap_layout(
    layout: Mapping[str, Any],
    *,
    label: str = "Основной формат",
    fingerprint: Mapping[str, Any] | None = None,
    selector: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    copied = deepcopy(dict(layout))
    sheet_name = str(copied.get("sheet_name") or "")
    return {
        "definition_version": TEMPLATE_DEFINITION_VERSION,
        "components": [{
            "id": str(uuid.uuid4()),
            "label": label,
            "selector": {
                "sheet_name": sheet_name,
                **deepcopy(dict(selector or {})),
            },
            "fingerprint": deepcopy(dict(fingerprint or {})),
            "layout": copied,
        }],
    }


def normalize_definition(value: Mapping[str, Any]) -> Dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("Определение шаблона должно быть объектом.")
    if not is_composite_definition(value):
        return wrap_layout(value)

    components: List[Dict[str, Any]] = []
    for index, raw in enumerate(value.get("components") or [], 1):
        if not isinstance(raw, Mapping) or not isinstance(raw.get("layout"), Mapping):
            continue
        layout = deepcopy(dict(raw["layout"]))
        selector = deepcopy(dict(raw.get("selector") or {}))
        selector.setdefault("sheet_name", str(layout.get("sheet_name") or ""))
        components.append({
            "id": str(raw.get("id") or uuid.uuid4()),
            "label": str(raw.get("label") or f"Формат {index}").strip()[:160],
            "selector": selector,
            "fingerprint": deepcopy(dict(raw.get("fingerprint") or {})),
            "layout": layout,
        })
    if not components:
        raise ValueError("Составной шаблон не содержит пригодных компонентов.")
    return {
        "definition_version": TEMPLATE_DEFINITION_VERSION,
        "components": components,
    }


def components(value: Mapping[str, Any]) -> List[Dict[str, Any]]:
    return deepcopy(normalize_definition(value)["components"])


def add_component(
    definition: Mapping[str, Any],
    *,
    layout: Mapping[str, Any],
    label: str,
    fingerprint: Mapping[str, Any] | None = None,
    selector: Mapping[str, Any] | None = None,
    replace_component_id: str | None = None,
) -> Dict[str, Any]:
    normalized = normalize_definition(definition)
    component = wrap_layout(
        layout,
        label=label,
        fingerprint=fingerprint,
        selector=selector,
    )["components"][0]
    if replace_component_id:
        replaced = False
        updated = []
        for current in normalized["components"]:
            if current["id"] == replace_component_id:
                component["id"] = replace_component_id
                updated.append(component)
                replaced = True
            else:
                updated.append(current)
        if not replaced:
            updated.append(component)
        normalized["components"] = updated
    else:
        normalized["components"].append(component)
    return normalized


def delete_component(definition: Mapping[str, Any], component_id: str) -> Dict[str, Any]:
    normalized = normalize_definition(definition)
    remaining = [
        component for component in normalized["components"]
        if component["id"] != component_id
    ]
    if not remaining:
        raise ValueError("Нельзя удалить последний компонент шаблона.")
    normalized["components"] = remaining
    return normalized


def _sheet_fingerprints(workbook_fingerprint: Mapping[str, Any] | None) -> List[Mapping[str, Any]]:
    if not isinstance(workbook_fingerprint, Mapping):
        return []
    return [
        item for item in workbook_fingerprint.get("sheets", [])
        if isinstance(item, Mapping)
    ]


def fingerprint_similarity(
    expected: Mapping[str, Any] | None,
    actual: Mapping[str, Any] | None,
) -> float:
    if not expected or not actual:
        return 0.0
    score = weight = 0.0

    expected_title = _normalized_text(expected.get("title"))
    actual_title = _normalized_text(actual.get("title"))
    if expected_title or actual_title:
        weight += 0.18
        if expected_title == actual_title:
            score += 0.18
        elif expected_title and actual_title and (
            expected_title in actual_title or actual_title in expected_title
        ):
            score += 0.12

    for key, item_weight, tolerance in (
        ("max_row", 0.12, 0.30),
        ("max_column", 0.12, 0.30),
        ("merged_count", 0.08, 0.60),
        ("week_count", 0.14, 0.50),
        ("keyword_count", 0.08, 0.70),
    ):
        expected_value = float(expected.get(key, 0) or 0)
        actual_value = float(actual.get(key, 0) or 0)
        weight += item_weight
        maximum = max(1.0, expected_value, actual_value)
        difference = abs(expected_value - actual_value) / maximum
        score += item_weight * max(0.0, 1.0 - difference / max(tolerance, 0.01))

    expected_tokens = {
        _normalized_text(item)
        for item in expected.get("header_tokens", []) or []
        if _normalized_text(item)
    }
    actual_tokens = {
        _normalized_text(item)
        for item in actual.get("header_tokens", []) or []
        if _normalized_text(item)
    }
    weight += 0.28
    if expected_tokens or actual_tokens:
        union = expected_tokens | actual_tokens
        score += 0.28 * (len(expected_tokens & actual_tokens) / max(1, len(union)))

    if weight <= 0:
        return 0.0
    return round(max(0.0, min(1.0, score / weight)) * 100, 2)


def component_candidates(
    definition: Mapping[str, Any],
    workbook_fingerprint: Mapping[str, Any] | None,
    available_sheets: Iterable[str],
    fallback_sheet: str,
) -> List[Dict[str, Any]]:
    sheets = _sheet_fingerprints(workbook_fingerprint)
    sheet_by_name = {
        str(item.get("title") or ""): item
        for item in sheets
    }
    available = list(dict.fromkeys(str(item) for item in available_sheets if str(item)))
    result: List[Dict[str, Any]] = []
    for component in components(definition):
        layout = deepcopy(component["layout"])
        selector = component.get("selector") or {}
        preferred = str(selector.get("sheet_name") or layout.get("sheet_name") or "")
        candidate_sheet_names = available or list(sheet_by_name)
        if preferred in candidate_sheet_names:
            chosen = preferred
        else:
            chosen = fallback_sheet or (candidate_sheet_names[0] if candidate_sheet_names else preferred)
        layout["sheet_name"] = chosen
        expected = component.get("fingerprint") or {}
        actual = sheet_by_name.get(chosen) or {}
        similarity = fingerprint_similarity(expected, actual)
        result.append({
            "component_id": component["id"],
            "component_label": component["label"],
            "layout": layout,
            "selector": deepcopy(selector),
            "fingerprint_similarity": similarity,
        })
    return result


def diff_values(before: Any, after: Any, prefix: str = "") -> List[Dict[str, Any]]:
    changes: List[Dict[str, Any]] = []
    if isinstance(before, Mapping) and isinstance(after, Mapping):
        keys = sorted(set(before) | set(after))
        for key in keys:
            path = f"{prefix}.{key}" if prefix else str(key)
            if key not in before:
                changes.append({"path": path, "before": None, "after": after[key], "kind": "added"})
            elif key not in after:
                changes.append({"path": path, "before": before[key], "after": None, "kind": "removed"})
            else:
                changes.extend(diff_values(before[key], after[key], path))
        return changes
    if isinstance(before, Sequence) and not isinstance(before, (str, bytes)) and isinstance(after, Sequence) and not isinstance(after, (str, bytes)):
        maximum = max(len(before), len(after))
        for index in range(maximum):
            path = f"{prefix}[{index}]"
            if index >= len(before):
                changes.append({"path": path, "before": None, "after": after[index], "kind": "added"})
            elif index >= len(after):
                changes.append({"path": path, "before": before[index], "after": None, "kind": "removed"})
            else:
                changes.extend(diff_values(before[index], after[index], path))
        return changes
    if before != after:
        changes.append({"path": prefix or "value", "before": before, "after": after, "kind": "changed"})
    return changes


def definition_summary(definition: Mapping[str, Any]) -> Dict[str, Any]:
    normalized = normalize_definition(definition)
    return {
        "definition_version": normalized["definition_version"],
        "component_count": len(normalized["components"]),
        "components": [{
            "id": item["id"],
            "label": item["label"],
            "sheet_name": item.get("selector", {}).get("sheet_name") or item["layout"].get("sheet_name"),
            "fingerprint_hash": stable_hash(item.get("fingerprint") or {}),
        } for item in normalized["components"]],
    }
