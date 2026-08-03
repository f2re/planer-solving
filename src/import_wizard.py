"""Preview, map and classify imports before any persistent write."""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path
import re
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from .workspace_domain import normalize_teacher, teacher_key, text

TEACHER_FIELDS = (
    "short_name",
    "full_name",
    "position",
    "rank",
    "academic_degree",
)
TEACHER_LABELS = {
    "short_name": "Краткое имя",
    "full_name": "Полное ФИО",
    "position": "Должность",
    "rank": "Звание",
    "academic_degree": "Степень",
}
TEACHER_ALIASES = {
    "short_name": {
        "short_name", "краткое имя", "фио кратко", "краткое фио", "сокращение",
        "преподаватель кратко", "фио сокращенное", "фио сокращённое",
    },
    "full_name": {
        "full_name", "полное фио", "фио", "полное имя", "преподаватель",
        "фамилия имя отчество", "ф.и.о.",
    },
    "position": {"position", "должность", "положение", "штатная должность"},
    "rank": {"rank", "звание", "ученое звание", "учёное звание"},
    "academic_degree": {
        "academic_degree", "степень", "ученая степень", "учёная степень",
    },
}


def decode_text(payload: bytes) -> tuple[str, str]:
    for encoding in ("utf-8-sig", "utf-8", "cp1251", "cp866"):
        try:
            return payload.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    raise ValueError("Не удалось определить кодировку файла.")


def normalize_header(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().casefold().replace("ё", "е"))


def parse_rows(payload: bytes, filename: str) -> Dict[str, Any]:
    suffix = Path(filename).suffix.lower()
    decoded, encoding = decode_text(payload)
    if suffix == ".json":
        try:
            document = json.loads(decoded)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Некорректный JSON: {exc}") from exc
        if isinstance(document, dict):
            rows = document.get("teachers", document.get("templates", document.get("items", [])))
        else:
            rows = document
        if not isinstance(rows, list):
            raise ValueError("JSON должен содержать список записей.")
        normalized_rows = [dict(item) for item in rows if isinstance(item, Mapping)]
        headers: List[str] = []
        for row in normalized_rows:
            for key in row:
                if str(key) not in headers:
                    headers.append(str(key))
        return {
            "headers": headers,
            "rows": normalized_rows,
            "encoding": encoding,
            "delimiter": None,
            "source_type": "json",
        }

    if suffix not in {".csv", ".txt", ".tsv"}:
        raise ValueError("Поддерживаются CSV, TSV, TXT и JSON.")
    sample = decoded[:32_768]
    delimiter = "\t" if suffix == ".tsv" else ";"
    try:
        delimiter = csv.Sniffer().sniff(sample, delimiters=";,\t|").delimiter
    except csv.Error:
        pass
    reader = csv.reader(io.StringIO(decoded), delimiter=delimiter)
    raw = [row for row in reader if any(str(cell).strip() for cell in row)]
    if not raw:
        raise ValueError("Файл не содержит строк с данными.")

    header_index = 0
    best_score = -1
    for index, row in enumerate(raw[:20]):
        score = sum(
            1
            for cell in row
            if any(normalize_header(cell) in aliases for aliases in TEACHER_ALIASES.values())
        )
        score += len({normalize_header(cell) for cell in row if normalize_header(cell)}) / 100
        if score > best_score:
            best_score = score
            header_index = index
    headers = [str(cell).strip() or f"Столбец {index + 1}" for index, cell in enumerate(raw[header_index])]
    rows = []
    for source in raw[header_index + 1:]:
        padded = list(source) + [""] * max(0, len(headers) - len(source))
        rows.append({headers[index]: padded[index] for index in range(len(headers))})
    return {
        "headers": headers,
        "rows": rows,
        "encoding": encoding,
        "delimiter": delimiter,
        "source_type": "table",
        "header_row": header_index + 1,
    }


def suggest_teacher_mapping(headers: Sequence[str]) -> Dict[str, str]:
    normalized = {normalize_header(header): header for header in headers}
    mapping: Dict[str, str] = {}
    for target, aliases in TEACHER_ALIASES.items():
        exact = next((normalized[alias] for alias in aliases if alias in normalized), None)
        if exact:
            mapping[target] = exact
            continue
        candidate = next(
            (
                original
                for normalized_name, original in normalized.items()
                if any(alias in normalized_name or normalized_name in alias for alias in aliases)
            ),
            None,
        )
        if candidate:
            mapping[target] = candidate
    return mapping


def _initials(full_name: str) -> str:
    parts = [part for part in re.split(r"\s+", full_name.strip()) if part]
    if not parts:
        return ""
    surname = parts[0]
    initials = "".join(f"{part[0].upper()}." for part in parts[1:3] if part)
    return f"{surname} {initials}".strip()


def teacher_from_row(row: Mapping[str, Any], mapping: Mapping[str, str], teacher_id: int) -> Dict[str, Any]:
    payload = {
        target: text(row.get(source), 240)
        for target, source in mapping.items()
        if target in TEACHER_FIELDS and source
    }
    if not payload.get("full_name") and payload.get("short_name"):
        payload["full_name"] = payload["short_name"]
    if not payload.get("short_name") and payload.get("full_name"):
        payload["short_name"] = _initials(payload["full_name"])
    return normalize_teacher(payload, teacher_id)


def _diff(existing: Mapping[str, Any], incoming: Mapping[str, Any]) -> Dict[str, Dict[str, str]]:
    result: Dict[str, Dict[str, str]] = {}
    for field in TEACHER_FIELDS:
        before = text(existing.get(field), 240)
        after = text(incoming.get(field), 240)
        if before != after and after:
            result[field] = {"before": before, "after": after}
    return result


def classify_teachers(
    rows: Sequence[Mapping[str, Any]],
    mapping: Mapping[str, str],
    existing: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    existing_by_key = {teacher_key(dict(item)): dict(item) for item in existing}
    seen: set[str] = set()
    preview: List[Dict[str, Any]] = []
    counts = {"add": 0, "update": 0, "duplicate": 0, "conflict": 0, "invalid": 0}
    next_id = max((int(item.get("id", 0)) for item in existing), default=0) + 1

    for row_index, row in enumerate(rows, 1):
        try:
            teacher = teacher_from_row(row, mapping, next_id)
        except Exception as exc:
            counts["invalid"] += 1
            preview.append({
                "row": row_index,
                "status": "invalid",
                "decision": "skip",
                "message": str(exc),
                "source": dict(row),
                "teacher": None,
                "changes": {},
            })
            continue
        key = teacher_key(teacher)
        if key in seen:
            counts["conflict"] += 1
            preview.append({
                "row": row_index,
                "status": "conflict",
                "decision": "skip",
                "message": "Повтор одной записи внутри импортируемого файла.",
                "source": dict(row),
                "teacher": teacher,
                "changes": {},
            })
            continue
        seen.add(key)
        current = existing_by_key.get(key)
        if not current:
            counts["add"] += 1
            preview.append({
                "row": row_index,
                "status": "add",
                "decision": "add",
                "message": "Новая запись.",
                "source": dict(row),
                "teacher": teacher,
                "changes": {},
            })
            next_id += 1
            continue
        changes = _diff(current, teacher)
        if not changes:
            counts["duplicate"] += 1
            preview.append({
                "row": row_index,
                "status": "duplicate",
                "decision": "skip",
                "message": "Полное совпадение с существующей записью.",
                "source": dict(row),
                "teacher": teacher,
                "existing": current,
                "changes": {},
            })
        else:
            counts["update"] += 1
            preview.append({
                "row": row_index,
                "status": "update",
                "decision": "merge",
                "message": "Найдена существующая запись с отличающимися полями.",
                "source": dict(row),
                "teacher": teacher,
                "existing": current,
                "changes": changes,
            })
    return {"counts": counts, "rows": preview, "total": len(rows)}


def apply_teacher_decision(
    current: Mapping[str, Any] | None,
    incoming: Mapping[str, Any],
    decision: str,
) -> Dict[str, Any] | None:
    if decision == "skip":
        return None
    if decision in {"add", "replace"} or current is None:
        return dict(incoming)
    if decision == "merge":
        merged = dict(current)
        for field in TEACHER_FIELDS:
            value = text(incoming.get(field), 240)
            if value:
                merged[field] = value
        return merged
    raise ValueError("Неизвестное решение по строке импорта.")


def template_from_row(row: Mapping[str, Any]) -> Dict[str, Any]:
    name = text(row.get("name") or row.get("Название"), 160)
    if not name:
        raise ValueError("У шаблона не задано название.")
    raw_layout = row.get("layout") or row.get("Разметка")
    if isinstance(raw_layout, str):
        try:
            raw_layout = json.loads(raw_layout)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Разметка шаблона не является JSON: {exc}") from exc
    if not isinstance(raw_layout, dict):
        raise ValueError("У шаблона отсутствует объект разметки.")
    composite = row.get("composite") or row.get("Составные правила") or []
    if isinstance(composite, str):
        try:
            composite = json.loads(composite)
        except json.JSONDecodeError:
            composite = []
    return {
        "name": name,
        "description": text(row.get("description") or row.get("Описание"), 1000),
        "layout": raw_layout,
        "composite": composite if isinstance(composite, list) else [],
    }


def classify_templates(
    rows: Sequence[Mapping[str, Any]],
    existing: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    existing_by_name = {str(item.get("name", "")).casefold(): dict(item) for item in existing}
    seen: set[str] = set()
    preview: List[Dict[str, Any]] = []
    counts = {"add": 0, "update": 0, "duplicate": 0, "conflict": 0, "invalid": 0}
    for row_index, row in enumerate(rows, 1):
        try:
            template = template_from_row(row)
        except Exception as exc:
            counts["invalid"] += 1
            preview.append({
                "row": row_index,
                "status": "invalid",
                "decision": "skip",
                "message": str(exc),
                "source": dict(row),
                "template": None,
            })
            continue
        key = template["name"].casefold()
        if key in seen:
            counts["conflict"] += 1
            preview.append({
                "row": row_index,
                "status": "conflict",
                "decision": "skip",
                "message": "Повтор шаблона внутри импортируемого файла.",
                "source": dict(row),
                "template": template,
            })
            continue
        seen.add(key)
        current = existing_by_name.get(key)
        if not current:
            counts["add"] += 1
            status, decision, message = "add", "add", "Новый шаблон."
        elif current.get("layout") == template["layout"] and current.get("description", "") == template["description"]:
            counts["duplicate"] += 1
            status, decision, message = "duplicate", "skip", "Шаблон полностью совпадает."
        else:
            counts["update"] += 1
            status, decision, message = "update", "replace", "Шаблон существует и будет сохранён новой ревизией."
        preview.append({
            "row": row_index,
            "status": status,
            "decision": decision,
            "message": message,
            "source": dict(row),
            "template": template,
            "existing": current,
        })
    return {"counts": counts, "rows": preview, "total": len(rows)}


def csv_report(rows: Iterable[Mapping[str, Any]]) -> str:
    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow(["Строка", "Статус", "Решение", "Сообщение", "Имя"])
    for item in rows:
        entity = item.get("teacher") or item.get("template") or {}
        writer.writerow([
            item.get("row", ""),
            item.get("status", ""),
            item.get("decision", ""),
            item.get("message", ""),
            entity.get("full_name") or entity.get("name") or entity.get("short_name") or "",
        ])
    return "\ufeff" + output.getvalue()
