"""Workbook fingerprints, composite layouts and explainable template learning."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
import re
from typing import Any, Dict, Iterable, List, Mapping, Sequence


def _normalized_words(values: Iterable[Any]) -> List[str]:
    words: set[str] = set()
    for value in values:
        for token in re.findall(r"[0-9a-zа-я]+", str(value or "").casefold().replace("ё", "е")):
            if len(token) >= 2:
                words.add(token)
    return sorted(words)


def fingerprint_from_analysis(analysis: Mapping[str, Any]) -> Dict[str, Any]:
    layout = dict(analysis.get("layout") or {})
    diagnostics = analysis.get("diagnostics") or []
    sheet_names = [str(item) for item in analysis.get("sheet_names") or []]
    features = {
        "sheet_count": len(sheet_names),
        "sheet_words": _normalized_words(sheet_names),
        "max_row_bucket": int(math.ceil(int(analysis.get("max_row") or 0) / 25)),
        "max_column_bucket": int(math.ceil(int(analysis.get("max_column") or 0) / 5)),
        "week_span": max(
            0,
            int(layout.get("last_week_col") or 0) - int(layout.get("first_week_col") or 0),
        ),
        "week_step": int(layout.get("week_col_step") or 0),
        "day_block_rows": int(layout.get("day_block_rows") or 0),
        "pairs_per_day": int(layout.get("pairs_per_day") or 0),
        "cell_mode": str(layout.get("cell_mode") or ""),
        "teacher_source": str(layout.get("teacher_source") or ""),
        "has_legend": bool(layout.get("legend_start_row")),
        "diagnostic_codes": sorted({
            str(item.get("code"))
            for item in diagnostics
            if isinstance(item, Mapping) and item.get("code")
        }),
    }
    canonical = json.dumps(features, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
        "hash": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "features": features,
    }


def fingerprint_similarity(left: Mapping[str, Any] | None, right: Mapping[str, Any] | None) -> float:
    if not left or not right:
        return 0.0
    a = dict(left.get("features") or left)
    b = dict(right.get("features") or right)
    score = 0.0
    weight = 0.0

    for field, field_weight in (
        ("cell_mode", 1.5),
        ("teacher_source", 1.0),
        ("has_legend", 1.0),
        ("week_step", 1.0),
        ("day_block_rows", 1.0),
        ("pairs_per_day", 1.0),
    ):
        weight += field_weight
        if a.get(field) == b.get(field):
            score += field_weight

    for field, tolerance, field_weight in (
        ("sheet_count", 2, 0.8),
        ("max_row_bucket", 6, 1.0),
        ("max_column_bucket", 4, 1.0),
        ("week_span", 12, 1.0),
    ):
        weight += field_weight
        av, bv = float(a.get(field) or 0), float(b.get(field) or 0)
        score += field_weight * max(0.0, 1.0 - abs(av - bv) / max(1.0, tolerance))

    for field, field_weight in (("sheet_words", 1.0), ("diagnostic_codes", 0.5)):
        weight += field_weight
        aset, bset = set(a.get(field) or []), set(b.get(field) or [])
        if not aset and not bset:
            score += field_weight
        elif aset or bset:
            score += field_weight * len(aset & bset) / max(1, len(aset | bset))

    return round(score / max(weight, 1.0), 4)


def layout_candidates(template: Mapping[str, Any], sheet_names: Sequence[str]) -> List[Dict[str, Any]]:
    """Return primary and matching composite sheet layouts for one template."""

    candidates: List[Dict[str, Any]] = []
    primary = template.get("layout")
    if isinstance(primary, Mapping):
        candidates.append({
            "rule_id": "primary",
            "rule_name": "Основная разметка",
            "layout": deepcopy(dict(primary)),
        })
    for index, rule in enumerate(template.get("composite") or []):
        if not isinstance(rule, Mapping) or not isinstance(rule.get("layout"), Mapping):
            continue
        pattern = str(rule.get("sheet_pattern") or "").strip()
        matched_sheet = None
        if not pattern:
            matched_sheet = next(iter(sheet_names), None)
        else:
            try:
                expression = re.compile(pattern, re.I)
                matched_sheet = next((name for name in sheet_names if expression.search(name)), None)
            except re.error:
                matched_sheet = next(
                    (name for name in sheet_names if pattern.casefold() in name.casefold()),
                    None,
                )
        if not matched_sheet:
            continue
        layout = deepcopy(dict(rule["layout"]))
        layout["sheet_name"] = matched_sheet
        candidates.append({
            "rule_id": str(rule.get("id") or f"rule-{index + 1}"),
            "rule_name": str(rule.get("name") or f"Правило {index + 1}"),
            "layout": layout,
        })
    return candidates


def best_template_layout(
    evaluated: Sequence[Mapping[str, Any]],
    template_similarity: float,
) -> Dict[str, Any]:
    if not evaluated:
        raise ValueError("У шаблона нет пригодных правил разметки.")
    ranked = sorted(
        (dict(item) for item in evaluated),
        key=lambda item: (
            float(item.get("score", -100000)),
            int(item.get("quality_percent", 0)),
        ),
        reverse=True,
    )
    selected = ranked[0]
    selected["fingerprint_similarity"] = template_similarity
    selected["score"] = round(float(selected.get("score", 0)) + template_similarity * 25.0, 3)
    selected["evaluated_rules"] = len(ranked)
    return selected


def layout_diff(before: Mapping[str, Any], after: Mapping[str, Any]) -> List[Dict[str, Any]]:
    keys = sorted(set(before) | set(after))
    changes = []
    for key in keys:
        old, new = before.get(key), after.get(key)
        if old != new:
            changes.append({"field": key, "before": old, "after": new})
    return changes


def normalize_composite_rules(rules: Any) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    for index, raw in enumerate(rules or []):
        if not isinstance(raw, Mapping) or not isinstance(raw.get("layout"), Mapping):
            continue
        result.append({
            "id": str(raw.get("id") or f"rule-{index + 1}"),
            "name": str(raw.get("name") or f"Правило {index + 1}").strip()[:160],
            "sheet_pattern": str(raw.get("sheet_pattern") or "").strip()[:240],
            "layout": deepcopy(dict(raw["layout"])),
        })
    return result
