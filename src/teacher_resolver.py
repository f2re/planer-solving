"""Teacher matching, workload balancing and lesson-type normalization."""
from __future__ import annotations

import json
import logging
from pathlib import Path
import re
from typing import Any, Dict, List, Mapping, Sequence, Tuple

from .schedule_analyzer import WorksheetMatrix, normalize_text
from .schedule_period import canonical_month, extract_date_parts

logger = logging.getLogger(__name__)


class TeacherResolver:
    NON_LESSON_SUBJECTS = {
        "вых", "выходной", "отп", "отпуск", "экзс", "эпр", "ср", "упр",
        "пв", "умо", "овп", "н", "зис",
    }

    def __init__(self, teachers_config_path: str):
        try:
            data = json.loads(Path(teachers_config_path).read_text(encoding="utf-8"))
            self.teachers_config = data if isinstance(data, list) else []
        except Exception as exc:
            logger.error("Cannot load teachers config %s: %s", teachers_config_path, exc)
            self.teachers_config = []
        self.occupancy: Dict[Tuple[int, str, int, str], str] = {}
        self.subject_counters: Dict[Tuple[str, str], int] = {}
        self.warnings: List[str] = []
        self.last_report: Dict[str, Any] = {}
        self.loaded_periods: List[Tuple[str, Dict[str, Any]]] = []
        self.teachers_by_surname: Dict[str, List[Dict[str, Any]]] = {}
        self.teacher_aliases: Dict[str, str] = {}
        self.teacher_overrides: Dict[str, str] = {}
        self._index_teachers()

    @staticmethod
    def _teacher_key(value: Any) -> str:
        return re.sub(r"\s+", " ", normalize_text(value).lower().replace("ё", "е")).strip()

    def _index_teachers(self) -> None:
        for teacher in self.teachers_config:
            full = normalize_text(teacher.get("full_name"))
            short = normalize_text(teacher.get("short_name")) or full
            parts = (full or short).split()
            if not parts:
                continue
            for alias in (short, full):
                key = self._teacher_key(alias)
                if key:
                    self.teacher_aliases[key] = short
            surname = parts[0].lower().replace("ё", "е")
            patterns = []
            if len(parts) >= 3 and parts[1] and parts[2]:
                s, first, middle = re.escape(parts[0]), re.escape(parts[1][0]), re.escape(parts[2][0])
                patterns = [
                    re.compile(rf"{s}\s+{first}\.?\s*{middle}\.?", re.I),
                    re.compile(rf"{first}\.?\s*{middle}\.?\s+{s}", re.I),
                    re.compile(rf"{s}\s+{first}\.?{middle}\.?", re.I),
                ]
            self.teachers_by_surname.setdefault(surname, []).append({"short": short, "patterns": patterns})

    def set_teacher_overrides(self, values: Mapping[str, Any] | None) -> Dict[str, str]:
        """Set per-file subject assignments, accepting only workspace teachers."""

        normalized: Dict[str, str] = {}
        for raw_subject, raw_teacher in dict(values or {}).items():
            subject_key = self._subject_key(raw_subject)
            teacher_key = self._teacher_key(raw_teacher)
            if not subject_key or not teacher_key:
                continue
            teacher = self.teacher_aliases.get(teacher_key)
            if not teacher:
                self.warnings.append(
                    f"Ручное назначение для «{normalize_text(raw_subject)}» пропущено: "
                    f"преподаватель «{normalize_text(raw_teacher)}» не найден в пространстве."
                )
                continue
            normalized[subject_key] = teacher
        self.teacher_overrides = normalized
        return dict(normalized)

    def _extract_teachers(self, value: Any) -> List[str]:
        text = normalize_text(value)
        searchable = text.lower().replace("ё", "е")
        found: List[str] = []
        for surname, variants in self.teachers_by_surname.items():
            if not re.search(rf"(?<![\w-]){re.escape(surname)}(?![\w-])", searchable, re.I):
                continue
            precise = [item["short"] for item in variants if any(pattern.search(text) for pattern in item["patterns"])]
            if precise:
                found.extend(precise)
            elif len(variants) == 1:
                found.append(variants[0]["short"])
        return list(dict.fromkeys(found))

    def _assign_teacher(self, week: int, day: str, pair: int, subject: str, lesson_type: str, candidates: Sequence[str]) -> str:
        manual = self.teacher_overrides.get(self._subject_key(subject))
        if manual:
            key = (week, day, pair, manual)
            occupied = self.occupancy.get(key)
            if occupied and occupied != subject:
                self.warnings.append(
                    f"Ручное назначение: {manual} уже занят на {occupied} "
                    f"(неделя {week}, {day}, {pair} пара); также назначено {subject}."
                )
            else:
                self.occupancy[key] = subject
            return manual

        teachers = list(dict.fromkeys(normalize_text(item) for item in candidates if normalize_text(item)))
        if not teachers:
            return "Unknown"
        for teacher in teachers:
            if self.occupancy.get((week, day, pair, teacher)) == subject:
                return teacher
        counter_key = (subject, lesson_type)
        start = self.subject_counters.get(counter_key, 0)
        for shift in range(len(teachers)):
            index = (start + shift) % len(teachers)
            teacher = teachers[index]
            key = (week, day, pair, teacher)
            if key not in self.occupancy:
                self.occupancy[key] = subject
                self.subject_counters[counter_key] = (index + 1) % len(teachers)
                return teacher
        teacher = teachers[start % len(teachers)]
        occupied = self.occupancy.get((week, day, pair, teacher), "другая дисциплина")
        self.subject_counters[counter_key] = (start + 1) % len(teachers)
        message = f"Конфликт: {teacher} уже занят на {occupied} (неделя {week}, {day}, {pair} пара); добавлено {subject} ({lesson_type})."
        self.warnings.append(message)
        return teacher

    @staticmethod
    def _subject_key(value: Any) -> str:
        return re.sub(r"[^0-9a-zа-я]+", "", normalize_text(value).lower().replace("ё", "е"))

    @staticmethod
    def _day_number(value: Any) -> int:
        return int(extract_date_parts(value).get("day") or 0)

    _parse_day_of_month = _day_number

    @staticmethod
    def _month(value: Any, previous: str = "Unknown") -> str:
        return canonical_month(value) or previous

    @staticmethod
    def _lesson_type(code: str) -> str:
        text = normalize_text(code).upper().replace(" ", "")
        match = re.match(
            r"^(ЭКЗАМЕН|КОНС|ЗАЧ|ИКС|ПЗ|ПР|ЛР|ЛТ|ЗЧ|ЗО|ЭКЗ|КР|КП|ГЗ|ПП|"
            r"ГУ|Л|П|С|У|Э)",
            text,
        )
        if not match:
            return "П"
        value = match.group(1)
        return {
            "ГУ": "У",
            "ЗАЧ": "ЗО",
            "КОНС": "П",
            "ПЗ": "П",
            "ПР": "П",
            "ЛТ": "Л",
            "ИКС": "П",
            "ЭКЗ": "Э",
            "ЭКЗАМЕН": "Э",
        }.get(value, value)

    @classmethod
    def _teacher_role(cls, code: str) -> str:
        lesson_type = cls._lesson_type(code)
        return "lecturer" if lesson_type == "Л" else "other"
