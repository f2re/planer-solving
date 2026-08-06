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
        self.teacher_aliases: Dict[str, List[str]] = {}
        self.teacher_identities: Dict[str, List[str]] = {}
        self.teacher_overrides: Dict[str, str] = {}
        self.teacher_candidate_catalog: Dict[str, Dict[str, List[str]]] = {}
        self._ambiguous_warnings: set[str] = set()
        self._index_teachers()

    @staticmethod
    def _teacher_key(value: Any) -> str:
        text = normalize_text(value).lower().replace("ё", "е")
        text = re.sub(r"[.,;:()]+", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    @classmethod
    def _name_identity(cls, value: Any) -> Tuple[str, str, str]:
        tokens = re.findall(r"[0-9a-zа-я-]+", cls._teacher_key(value), flags=re.I)
        if not tokens:
            return "", "", ""
        if len(tokens) == 1:
            return tokens[0], "", ""
        if len(tokens[0].replace("-", "")) == 1:
            surname = tokens[-1]
            initials = tokens[:-1]
        else:
            surname = tokens[0]
            initials = tokens[1:]
        first = initials[0][0] if initials and initials[0] else ""
        middle = initials[1][0] if len(initials) > 1 and initials[1] else ""
        return surname, first, middle

    @classmethod
    def _identity_key(cls, value: Any) -> str:
        surname, first, middle = cls._name_identity(value)
        return f"{surname}|{first}|{middle}" if surname else ""

    @staticmethod
    def _append_unique(mapping: Dict[str, List[str]], key: str, value: str) -> None:
        if not key or not value:
            return
        bucket = mapping.setdefault(key, [])
        if value not in bucket:
            bucket.append(value)

    @staticmethod
    def _name_patterns(surname: str, first: str, middle: str, full: str, short: str) -> List[re.Pattern[str]]:
        patterns: List[re.Pattern[str]] = []
        for alias in (full, short):
            alias = normalize_text(alias)
            if alias:
                escaped = re.escape(alias).replace(r"\ ", r"\s+")
                escaped = escaped.replace(r"\.", r"\.?\s*")
                patterns.append(re.compile(rf"(?<![\w-]){escaped}(?![\w-])", re.I))
        if surname and first:
            s = re.escape(surname)
            f = re.escape(first)
            if middle:
                m = re.escape(middle)
                patterns.extend([
                    re.compile(rf"(?<![\w-]){s}\s+{f}\.?\s*{m}\.?(?![\w-])", re.I),
                    re.compile(rf"(?<![\w-]){f}\.?\s*{m}\.?\s+{s}(?![\w-])", re.I),
                ])
            else:
                patterns.extend([
                    re.compile(rf"(?<![\w-]){s}\s+{f}\.?(?![\w-])", re.I),
                    re.compile(rf"(?<![\w-]){f}\.?\s+{s}(?![\w-])", re.I),
                ])
        return patterns

    def _index_teachers(self) -> None:
        for teacher in self.teachers_config:
            full = normalize_text(teacher.get("full_name"))
            short = normalize_text(teacher.get("short_name")) or full
            source = full or short
            surname, first, middle = self._name_identity(source)
            if not surname or not short:
                continue
            identity = f"{surname}|{first}|{middle}"
            for alias in (short, full):
                key = self._teacher_key(alias)
                self._append_unique(self.teacher_aliases, key, short)
                identity_key = self._identity_key(alias)
                self._append_unique(self.teacher_identities, identity_key, short)
            self._append_unique(self.teacher_identities, identity, short)
            self.teachers_by_surname.setdefault(surname, []).append({
                "short": short,
                "full": full,
                "identity": identity,
                "initials": "".join([first, middle]),
                "patterns": self._name_patterns(surname, first, middle, full, short),
            })

    def _ambiguous(self, label: str, variants: Sequence[str]) -> None:
        normalized = normalize_text(label)
        key = f"{self._teacher_key(normalized)}|{'|'.join(sorted(variants))}"
        if key in self._ambiguous_warnings:
            return
        self._ambiguous_warnings.add(key)
        self.warnings.append(
            f"Преподаватель «{normalized}» неоднозначен: "
            f"{', '.join(variants)}. Укажите фамилию и инициалы."
        )

    def _resolve_teacher_alias(self, value: Any, *, warn: bool = False) -> str:
        raw = normalize_text(value)
        if not raw:
            return ""
        exact = self.teacher_aliases.get(self._teacher_key(raw), [])
        if len(exact) == 1:
            return exact[0]
        if len(exact) > 1:
            if warn:
                self._ambiguous(raw, exact)
            return ""

        identity = self._identity_key(raw)
        matches = self.teacher_identities.get(identity, [])
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            if warn:
                self._ambiguous(raw, matches)
            return ""

        surname, first, middle = self._name_identity(raw)
        variants = [item["short"] for item in self.teachers_by_surname.get(surname, [])]
        if not first and len(variants) == 1:
            return variants[0]
        if warn and variants:
            self._ambiguous(raw, variants)
        return ""

    def set_teacher_overrides(self, values: Mapping[str, Any] | None) -> Dict[str, str]:
        """Set per-file subject assignments, accepting only unambiguous teachers."""

        normalized: Dict[str, str] = {}
        for raw_subject, raw_teacher in dict(values or {}).items():
            subject_key = self._subject_key(raw_subject)
            if not subject_key or not normalize_text(raw_teacher):
                continue
            teacher = self._resolve_teacher_alias(raw_teacher, warn=True)
            if not teacher:
                if not self.teachers_by_surname.get(self._name_identity(raw_teacher)[0]):
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
        if not text:
            return []
        searchable = text.lower().replace("ё", "е")
        found: List[str] = []
        ambiguous: List[Tuple[str, List[str]]] = []
        for surname, variants in self.teachers_by_surname.items():
            if not re.search(rf"(?<![\w-]){re.escape(surname)}(?![\w-])", searchable, re.I):
                continue
            precise = [
                item["short"]
                for item in variants
                if any(pattern.search(text) for pattern in item["patterns"])
            ]
            precise = list(dict.fromkeys(precise))
            if len(precise) == 1:
                found.extend(precise)
            elif len(precise) > 1:
                ambiguous.append((surname, precise))
            elif len(variants) == 1:
                found.append(variants[0]["short"])
            else:
                ambiguous.append((surname, [item["short"] for item in variants]))
        for surname, variants in ambiguous:
            self._ambiguous(surname, variants)
        return list(dict.fromkeys(found))

    def _register_subject_candidates(
        self,
        subject: Any,
        *,
        lecturers: Sequence[str] = (),
        others: Sequence[str] = (),
    ) -> None:
        key = self._subject_key(subject)
        if not key:
            return
        entry = self.teacher_candidate_catalog.setdefault(
            key,
            {"lecturer": [], "other": [], "all": []},
        )
        for role, values in (("lecturer", lecturers), ("other", others)):
            for raw in values:
                teacher = self._resolve_teacher_alias(raw) or normalize_text(raw)
                if not teacher:
                    continue
                if teacher not in entry[role]:
                    entry[role].append(teacher)
                if teacher not in entry["all"]:
                    entry["all"].append(teacher)

    def _assign_teacher(
        self,
        week: int,
        day: str,
        pair: int,
        subject: str,
        lesson_type: str,
        candidates: Sequence[str],
    ) -> str:
        role = self._teacher_role(lesson_type)
        self._register_subject_candidates(
            subject,
            lecturers=candidates if role == "lecturer" else (),
            others=candidates if role != "lecturer" else (),
        )

        manual = self.teacher_overrides.get(self._subject_key(subject))
        if manual:
            key = (week, day, pair, manual)
            occupied = self.occupancy.get(key)
            if occupied and occupied != subject:
                self.warnings.append(
                    f"Ручное назначение: {manual} уже занят на {occupied} "
                    f"(неделя {week}, {day}, {pair} пара); коллизия будет "
                    "перепроверена общим графом назначений."
                )
            else:
                self.occupancy[key] = subject
            return manual

        teachers = list(dict.fromkeys(
            self._resolve_teacher_alias(item) or normalize_text(item)
            for item in candidates
            if normalize_text(item)
        ))
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
        self.warnings.append(
            f"Предварительная коллизия: {teacher} уже занят на {occupied} "
            f"(неделя {week}, {day}, {pair} пара); {subject} ({lesson_type}) "
            "будет перераспределено общим графом."
        )
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
