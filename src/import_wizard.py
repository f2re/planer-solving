"""Preview, map and evaluate imports without changing persistent data."""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path
import re
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from .template_definition import definition_summary, normalize_definition
from .workspace_domain import WorkspaceError, normalize_teacher, teacher_key

TEACHER_FIELDS = (
    "short_name",
    "full_name",
    "position",
    "rank",
    "academic_degree",
)
TEACHER_FIELD_LABELS = {
    "short_name": "Краткое имя",
    "full_name": "Полное ФИО",
    "position": "Должность",
    "rank": "Звание",
    "academic_degree": "Степень",
}
ALIASES = {
    "short_name": {
        "short_name", "short name", "краткое имя", "фио кратко", "краткое фио",
        "сокращение", "инициалы", "фио сокр", "преподаватель кратко",
    },
    "full_name": {
        "full_name", "full name", "полное фио", "фио", "полное имя", "преподаватель",
        "фамилия имя отчество", "фио преподавателя",
    },
    "position": {"position", "должность", "должн", "позиция"},
    "rank": {"rank", "звание", "ученое звание", "учёное звание"},
    "academic_degree": {
        "academic_degree", "степень", "ученая степень", "учёная степень", "научная степень",
    },
}


def normalize_header(value: Any) -> str:
    return re.sub(
        r"[^0-9a-zа-я]+",
        " ",
        str(value or "").strip().casefold().replace("ё", "е"),
    ).strip()


def clean_cell(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\xa0", " ")).strip()


def decode_bytes(payload: bytes) -> tuple[str, str]:
    for encoding in ("utf-8-sig", "utf-8", "cp1251", "koi8-r"):
        try:
            return payload.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    raise WorkspaceError("Не удалось определить кодировку файла.")


def _unique_columns(values: Sequence[str]) -> List[str]:
    result: List[str] = []
    counts: Dict[str, int] = {}
    for index, raw in enumerate(values, 1):
        base = clean_cell(raw) or f"Столбец {index}"
        key = base.casefold()
        counts[key] = counts.get(key, 0) + 1
        result.append(base if counts[key] == 1 else f"{base} ({counts[key]})")
    return result


def _header_score(row: Sequence[str]) -> int:
    score = 0
    for cell in row:
        normalized = normalize_header(cell)
        if not normalized:
            continue
        if any(normalized in aliases for aliases in ALIASES.values()):
            score += 8
        elif any(alias in normalized or normalized in alias for aliases in ALIASES.values() for alias in aliases):
            score += 3
        elif len(normalized) <= 40:
            score += 1
    return score


def _suggest_mapping(columns: Sequence[str]) -> Dict[str, str]:
    normalized_columns = {column: normalize_header(column) for column in columns}
    mapping: Dict[str, str] = {}
    used: set[str] = set()
    for target, aliases in ALIASES.items():
        exact = next(
            (
                column for column, normalized in normalized_columns.items()
                if column not in used and normalized in aliases
            ),
            None,
        )
        if exact:
            mapping[target] = exact
            used.add(exact)
            continue
        fuzzy = next(
            (
                column for column, normalized in normalized_columns.items()
                if column not in used
                and any(alias in normalized or normalized in alias for alias in aliases)
            ),
            None,
        )
        if fuzzy:
            mapping[target] = fuzzy
            used.add(fuzzy)
    return mapping


def parse_teacher_source(payload: bytes, filename: str) -> Dict[str, Any]:
    suffix = Path(filename).suffix.lower()
    decoded, encoding = decode_bytes(payload)
    if suffix == ".json":
        try:
            raw = json.loads(decoded)
        except json.JSONDecodeError as exc:
            raise WorkspaceError(f"Некорректный JSON: {exc}") from exc
        data = raw.get("teachers", raw.get("items", [])) if isinstance(raw, dict) else raw
        if not isinstance(data, list):
            raise WorkspaceError("JSON должен содержать список преподавателей.")
        rows = [dict(item) for item in data if isinstance(item, dict)]
        columns = _unique_columns(
            list(dict.fromkeys(str(key) for row in rows for key in row.keys()))
        )
        mapping = _suggest_mapping(columns)
        return {
            "format": "json",
            "encoding": encoding,
            "delimiter": None,
            "header_row": 1,
            "columns": columns,
            "rows": [
                {column: clean_cell(row.get(column, "")) for column in columns}
                for row in rows
            ],
            "suggested_mapping": mapping,
        }

    if suffix not in {".csv", ".txt"}:
        raise WorkspaceError("Для преподавателей поддерживаются CSV, TXT и JSON.")
    try:
        dialect = csv.Sniffer().sniff(decoded[:8192], delimiters=";,\t|")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = ";"
    raw_rows = list(csv.reader(io.StringIO(decoded), delimiter=delimiter))
    raw_rows = [[clean_cell(cell) for cell in row] for row in raw_rows]
    raw_rows = [row for row in raw_rows if any(row)]
    if not raw_rows:
        raise WorkspaceError("Файл не содержит строк данных.")
    candidate_limit = min(12, len(raw_rows))
    header_index = max(range(candidate_limit), key=lambda index: _header_score(raw_rows[index]))
    columns = _unique_columns(raw_rows[header_index])
    width = len(columns)
    rows: List[Dict[str, str]] = []
    for raw_row in raw_rows[header_index + 1:]:
        padded = list(raw_row[:width]) + [""] * max(0, width - len(raw_row))
        record = {columns[index]: padded[index] for index in range(width)}
        if any(record.values()):
            rows.append(record)
    return {
        "format": "csv",
        "encoding": encoding,
        "delimiter": delimiter,
        "header_row": header_index + 1,
        "columns": columns,
        "rows": rows,
        "suggested_mapping": _suggest_mapping(columns),
    }


def short_name_from_full_name(value: str) -> str:
    parts = clean_cell(value).split()
    if not parts:
        return ""
    surname = parts[0]
    initials = "".join(f"{item[0].upper()}." for item in parts[1:3] if item)
    return f"{surname} {initials}".strip()


def normalize_teacher_rows(
    source_rows: Sequence[Mapping[str, Any]],
    mapping: Mapping[str, str],
) -> List[Dict[str, Any]]:
    result = []
    for index, source in enumerate(source_rows):
        record = {
            field: clean_cell(source.get(mapping.get(field, ""), ""))
            for field in TEACHER_FIELDS
        }
        if not record["full_name"] and record["short_name"]:
            record["full_name"] = record["short_name"]
        if not record["short_name"] and record["full_name"]:
            record["short_name"] = short_name_from_full_name(record["full_name"])
        result.append({"row_index": index, "source": dict(source), "record": record})
    return result


def evaluate_teacher_rows(
    source_rows: Sequence[Mapping[str, Any]],
    mapping: Mapping[str, str],
    existing_teachers: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    normalized = normalize_teacher_rows(source_rows, mapping)
    existing = {teacher_key(dict(item)): dict(item) for item in existing_teachers}
    seen: Dict[str, int] = {}
    rows = []
    summary = {"add": 0, "update": 0, "conflict": 0, "skip": 0, "error": 0}
    for item in normalized:
        row_index = int(item["row_index"])
        record = dict(item["record"])
        try:
            teacher = normalize_teacher(record, row_index + 1)
        except WorkspaceError as exc:
            action = "error"
            message = str(exc)
            key = ""
            existing_item = None
        else:
            key = teacher_key(teacher)
            existing_item = existing.get(key)
            if not key:
                action, message = "error", "Не удалось определить ФИО."
            elif key in seen:
                action = "conflict"
                message = f"Дубликат строки {seen[key] + 1} внутри файла."
            elif existing_item:
                changed = any(
                    clean_cell(teacher.get(field))
                    and clean_cell(teacher.get(field)) != clean_cell(existing_item.get(field))
                    for field in TEACHER_FIELDS
                )
                action = "update" if changed else "skip"
                message = "Запись существует; поля отличаются." if changed else "Полное совпадение."
            else:
                action, message = "add", "Новая запись."
            seen[key] = row_index
        summary[action] += 1
        rows.append({
            **item,
            "normalized_key": key,
            "existing": existing_item,
            "suggested_action": action,
            "message": message,
        })
    return {
        "kind": "teachers",
        "mapping": dict(mapping),
        "summary": summary,
        "rows": rows,
        "total_rows": len(rows),
    }


def parse_template_source(payload: bytes, filename: str) -> Dict[str, Any]:
    if Path(filename).suffix.lower() != ".json":
        raise WorkspaceError("Шаблоны импортируются из JSON.")
    decoded, encoding = decode_bytes(payload)
    try:
        raw = json.loads(decoded)
    except json.JSONDecodeError as exc:
        raise WorkspaceError(f"Некорректный JSON: {exc}") from exc
    data = raw.get("templates", raw.get("items", [])) if isinstance(raw, dict) else raw
    if not isinstance(data, list):
        raise WorkspaceError("JSON должен содержать список шаблонов.")
    rows = [dict(item) for item in data if isinstance(item, dict)]
    return {
        "format": "json",
        "encoding": encoding,
        "columns": ["name", "description", "layout"],
        "rows": rows,
        "suggested_mapping": {},
    }


def evaluate_template_rows(
    source_rows: Sequence[Mapping[str, Any]],
    existing_templates: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    existing = {
        str(item.get("name") or "").strip().casefold(): dict(item)
        for item in existing_templates
    }
    rows = []
    summary = {"add": 0, "update": 0, "conflict": 0, "skip": 0, "error": 0}
    seen: set[str] = set()
    for index, source in enumerate(source_rows):
        try:
            template = {
                "name": clean_cell(source.get("name")),
                "description": clean_cell(source.get("description")),
                "layout": normalize_definition(source.get("layout") or {}),
            }
            if not template["name"]:
                raise WorkspaceError("Не задано название шаблона.")
            key = template["name"].casefold()
            current = existing.get(key)
            if key in seen:
                action, message = "conflict", "Повтор названия внутри файла."
            elif current:
                current_layout = normalize_definition(current.get("layout") or {})
                action = "skip" if current_layout == template["layout"] else "update"
                message = "Полное совпадение." if action == "skip" else "Шаблон существует; разметка отличается."
            else:
                action, message = "add", "Новый шаблон."
            seen.add(key)
        except (WorkspaceError, ValueError) as exc:
            template = {"name": clean_cell(source.get("name")), "description": "", "layout": {}}
            current = None
            action, message = "error", str(exc)
        summary[action] += 1
        rows.append({
            "row_index": index,
            "source": dict(source),
            "record": template,
            "existing": current,
            "suggested_action": action,
            "message": message,
            "summary": definition_summary(template["layout"]) if template["layout"] else None,
        })
    return {
        "kind": "templates",
        "mapping": {},
        "summary": summary,
        "rows": rows,
        "total_rows": len(rows),
    }


def parse_workspace_source(payload: bytes, filename: str) -> Dict[str, Any]:
    if Path(filename).suffix.lower() != ".json":
        raise WorkspaceError("Пространство импортируется из JSON.")
    decoded, encoding = decode_bytes(payload)
    try:
        raw = json.loads(decoded)
    except json.JSONDecodeError as exc:
        raise WorkspaceError(f"Некорректный JSON: {exc}") from exc
    source = raw.get("workspace") if isinstance(raw, dict) and isinstance(raw.get("workspace"), dict) else raw
    if not isinstance(source, dict):
        raise WorkspaceError("JSON не содержит рабочего пространства.")
    teachers = source.get("teachers") if isinstance(source.get("teachers"), list) else []
    templates = source.get("templates") if isinstance(source.get("templates"), list) else []
    return {
        "format": "json",
        "encoding": encoding,
        "columns": [],
        "rows": [source],
        "suggested_mapping": {},
        "workspace_summary": {
            "name": clean_cell(source.get("name")) or "Импортированное пространство",
            "description": clean_cell(source.get("description")),
            "teacher_count": len(teachers),
            "template_count": len(templates),
            "settings": source.get("settings") or {},
        },
    }
