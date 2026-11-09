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


def parse_name_identity(value: Any) -> Tuple[str, str, str]:
    text = normalize_text(value)
    if not text:
        return "", "", ""
    text_clean = text.lower().replace("ё", "е")

    # 1) Initials at start with dots: 'И.И. Иванов', 'И. И. Иванов', 'И. Иванов', 'И.И Иванов'
    m = re.match(r"^([a-zа-я])\.\s*(?:([a-zа-я])\.?)?\s+([a-zа-я-]+)$", text_clean)
    if m:
        first = m.group(1)
        middle = m.group(2) if m.group(2) else ""
        surname = m.group(3)
        return surname, first, middle

    # 2) Initials at end with dots: 'Иванов И.И.', 'Иванов И. И.', 'Иванов И.', 'Иванов И.И'
    m = re.match(r"^([a-zа-я-]+)\s+([a-zа-я])\.\s*(?:([a-zа-я])\.?)?$", text_clean)
    if m:
        surname = m.group(1)
        first = m.group(2)
        middle = m.group(3) if m.group(3) else ""
        return surname, first, middle

    cleaned = re.sub(r"[.,;:()]+", " ", text_clean).strip()
    tokens = [t for t in cleaned.split() if t]
    if not tokens:
        return "", "", ""
    if len(tokens) == 1:
        return tokens[0], "", ""

    if len(tokens) == 2:
        t0, t1 = tokens[0], tokens[1]
        if len(t0) == 1 or (len(t0) == 2 and (len(t1) > 2 or len(t0) < len(t1))):
            surname = t1
            first = t0[0]
            middle = t0[1] if len(t0) > 1 else ""
            return surname, first, middle
        if len(t1) in (1, 2):
            surname = t0
            first = t1[0]
            middle = t1[1] if len(t1) > 1 else ""
            return surname, first, middle
        surname = t0
        first = t1[0]
        return surname, first, ""

    if len(tokens[0]) == 1 and len(tokens[1]) == 1:
        surname = tokens[-1]
        first = tokens[0][0]
        middle = tokens[1][0]
        return surname, first, middle
    if len(tokens[-2]) == 1 and len(tokens[-1]) == 1:
        surname = tokens[0]
        first = tokens[-2][0]
        middle = tokens[-1][0]
        return surname, first, middle

    surname = tokens[0]
    first = tokens[1][0]
    middle = tokens[2][0]
    return surname, first, middle


def _format_single_teacher_initials(raw: str) -> str:
    raw_str = re.sub(r"\s+", " ", str(raw or "").replace("\xa0", " ")).strip()
    if not raw_str:
        return ""
    surname, first, middle = parse_name_identity(raw_str)
    if not surname:
        return raw_str

    orig_tokens = [t for t in re.sub(r"[.,;:()]+", " ", raw_str).strip().split() if t]
    orig_surname = "-".join(part.capitalize() for part in surname.split("-"))
    for t in orig_tokens:
        if t.lower().replace("ё", "е") == surname:
            orig_surname = "-".join(part.capitalize() for part in t.split("-"))
            break

    inits = []
    if first:
        inits.append(f"{first.upper()}.")
    if middle:
        inits.append(f"{middle.upper()}.")
    init_str = "".join(inits)
    return f"{orig_surname} {init_str}".strip() if init_str else orig_surname


def format_teacher_initials(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        formatted = [_format_single_teacher_initials(str(item)) for item in value if str(item).strip()]
        return ", ".join(formatted)

    raw_str = str(value or "").strip()
    if not raw_str:
        return ""

    parts = [p.strip() for p in re.split(r"(?:[\n,;/\\\\]+|\s+[иИ]\s+)", raw_str) if p.strip()]
    if not parts:
        return ""
    formatted = [_format_single_teacher_initials(part) for part in parts]
    return ", ".join(formatted)


class TeacherLookup(Mapping[str, str]):
    def __init__(self, teachers_config: Sequence[Mapping[str, Any]] | None):
        self._exact: Dict[str, str] = {}
        self._by_surname: Dict[str, List[Dict[str, Any]]] = {}
        self._all_short: set[str] = set()
        for teacher in teachers_config or []:
            if not isinstance(teacher, Mapping):
                continue
            short = str(teacher.get("short_name") or teacher.get("full_name") or "").strip()
            full = str(teacher.get("full_name") or short or "").strip()
            if not short:
                continue
            self._all_short.add(short)
            for alias in (short, full):
                if alias:
                    self._exact[alias.casefold().replace("ё", "е")] = short
                    self._exact[TeacherResolver._teacher_key(alias)] = short
                    self._exact[alias.casefold()] = short
                    self._exact[alias.strip()] = short
            surname, first, middle = parse_name_identity(full or short)
            if surname:
                self._by_surname.setdefault(surname, []).append({
                    "short": short,
                    "first": first,
                    "middle": middle,
                })

    def _resolve_single(self, key: Any) -> str:
        raw = str(key or "").strip()
        if not raw:
            return ""
        if raw in self._exact:
            return self._exact[raw]
        raw_case = raw.casefold()
        if raw_case in self._exact:
            return self._exact[raw_case]
        normalized = raw_case.replace("ё", "е")
        if normalized in self._exact:
            return self._exact[normalized]
        teacher_k = TeacherResolver._teacher_key(raw)
        if teacher_k in self._exact:
            return self._exact[teacher_k]

        surname, first, middle = parse_name_identity(raw)
        if not surname:
            return ""
        variants = self._by_surname.get(surname, [])
        if not variants:
            parts = [p for p in re.sub(r"[.,;:()]+", " ", normalized).split() if p]
            if len(parts) == 2 and parts[1] in self._by_surname:
                surname = parts[1]
                first = parts[0][0]
                middle = ""
                variants = self._by_surname.get(surname, [])
        if not variants:
            return ""

        if first and middle:
            matches = [
                item["short"] for item in variants
                if item["first"] == first and (not item["middle"] or item["middle"] == middle)
            ]
            if len(matches) == 1:
                return matches[0]
            return ""
        if first and not middle:
            matches = [item["short"] for item in variants if item["first"] == first]
            if len(matches) == 1:
                return matches[0]
            return ""
        if not first:
            if len(variants) == 1:
                return variants[0]["short"]
            return ""
        return ""

    def resolve_all(self, value: Any) -> List[str]:
        if value is None:
            return []

        if isinstance(value, (list, tuple, set)):
            results: List[str] = []
            for item in value:
                for teacher in self.resolve_all(item):
                    if teacher not in results:
                        results.append(teacher)
            return results

        raw_str = str(value or "").strip()
        if not raw_str:
            return []

        delimiter_pattern = re.compile(r"(?:[\n,;/\\\\]+|\s+[иИ]\s+)")
        parts = [p.strip() for p in delimiter_pattern.split(raw_str) if p.strip()]
        if len(parts) > 1:
            results: List[str] = []
            for part in parts:
                resolved = self._resolve_single(part)
                if resolved and resolved not in results:
                    results.append(resolved)
            return results

        single = self._resolve_single(raw_str)
        if single:
            return [single]
        return []

    def get(self, key: Any, default: Any = "") -> Any:
        if isinstance(key, (list, tuple, set)):
            teachers = self.resolve_all(key)
            return ", ".join(teachers) if teachers else default
        raw_str = str(key or "").strip()
        if not raw_str:
            return default
        delimiter_pattern = re.compile(r"(?:[\n,;/\\\\]+|\s+[иИ]\s+)")
        if delimiter_pattern.search(raw_str):
            teachers = self.resolve_all(raw_str)
            return ", ".join(teachers) if teachers else default
        single = self._resolve_single(raw_str)
        if single:
            return single
        teachers = self.resolve_all(raw_str)
        if teachers:
            return ", ".join(teachers)
        return default

    def __getitem__(self, key: Any) -> str:
        res = self.get(key)
        if not res:
            raise KeyError(key)
        return res

    def __contains__(self, key: Any) -> bool:
        return bool(self.get(key))

    def __iter__(self):
        return iter(self._exact)

    def __len__(self):
        return len(self._exact)


class TeacherResolver:
    NON_LESSON_SUBJECTS = {
        "вых", "выходной", "отп", "отпуск", "экзс", "эпр", "ср", "упр",
        "пв", "умо", "овп", "н", "зис",
    }
    PREFERENCE_ROLES = {"lecturer", "other", "reserve"}

    def __init__(self, teachers_config_path: str):
        try:
            data = json.loads(Path(teachers_config_path).read_text(encoding="utf-8"))
            raw_list = data if isinstance(data, list) else []
            self.teachers_config = [
                item for item in raw_list
                if isinstance(item, dict) and any(str(v).strip() for v in item.values())
            ]
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
        self.teacher_assignment_preferences: Dict[str, Dict[str, List[str]]] = {}
        self._ambiguous_warnings: set[str] = set()
        self._index_teachers()

    @staticmethod
    def _teacher_key(value: Any) -> str:
        text = normalize_text(value).lower().replace("ё", "е")
        text = re.sub(r"[.,;:()]+", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    @classmethod
    def _name_identity(cls, value: Any) -> Tuple[str, str, str]:
        return parse_name_identity(value)

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
    def _single_initial_patterns(surname: str, first: str) -> List[re.Pattern[str]]:
        patterns: List[re.Pattern[str]] = []
        if surname and first:
            s = re.escape(surname)
            f = re.escape(first)
            patterns.extend([
                re.compile(rf"(?<![\w-]){s}\s+{f}(?:\.|\b)(?!\.?\s*[a-zа-я])", re.I),
                re.compile(rf"(?<!\b[a-zа-я]\.)(?<!\b[a-zа-я]\.\s)(?<![\w-]){f}(?:\.|\b)\s+{s}(?![\w-])", re.I),
            ])
        return patterns

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
                    re.compile(rf"(?<![\w-]){s}\s+{f}(?:\.|\b)(?!\.?\s*[a-zа-я])", re.I),
                    re.compile(rf"(?<!\b[a-zа-я]\.)(?<!\b[a-zа-я]\.\s)(?<![\w-]){f}(?:\.|\b)\s+{s}(?![\w-])", re.I),
                ])
        return patterns

    def _index_teachers(self) -> None:
        for teacher in self.teachers_config:
            if not isinstance(teacher, Mapping):
                continue
            full = str(teacher.get("full_name") or "").strip()
            short = str(teacher.get("short_name") or "").strip() or full
            if not full:
                full = short
            source = full or short
            surname, first, middle = self._name_identity(source)
            if not surname or not short:
                continue
            identity = f"{surname}|{first}|{middle}"
            for alias in (short, full):
                key = self._teacher_key(alias)
                self._append_unique(self.teacher_aliases, key, short)
                alias_norm = alias.casefold().replace("ё", "е")
                if alias_norm != key:
                    self._append_unique(self.teacher_aliases, alias_norm, short)
                alias_case = alias.casefold()
                if alias_case != key and alias_case != alias_norm:
                    self._append_unique(self.teacher_aliases, alias_case, short)
                alias_strip = alias.strip()
                if alias_strip != key and alias_strip != alias_norm and alias_strip != alias_case:
                    self._append_unique(self.teacher_aliases, alias_strip, short)
                identity_key = self._identity_key(alias)
                self._append_unique(self.teacher_identities, identity_key, short)
            self._append_unique(self.teacher_identities, identity, short)
            self.teachers_by_surname.setdefault(surname, []).append({
                "short": short,
                "full": full,
                "first": first,
                "middle": middle,
                "identity": identity,
                "initials": "".join([first, middle]),
                "patterns": self._name_patterns(surname, first, middle, full, short),
                "single_patterns": self._single_initial_patterns(surname, first),
            })

    def _ambiguous(self, label: str, variants: Sequence[str]) -> None:
        normalized = normalize_text(label)
        key = f"{self._teacher_key(normalized)}|{'|'.join(sorted(variants))}"
        if key in self._ambiguous_warnings:
            return
        self._ambiguous_warnings.add(key)
        variants_str = ", ".join(variants).rstrip(".")
        self.warnings.append(
            f"Преподаватель «{normalized}» неоднозначен: "
            f"{variants_str}. Укажите фамилию и инициалы."
        )

    def _resolve_teacher_alias(self, value: Any, *, warn: bool = False) -> str:
        raw = normalize_text(value)
        if not raw:
            return ""
        exact = self.teacher_aliases.get(self._teacher_key(raw), [])
        if not exact:
            exact = self.teacher_aliases.get(raw.casefold().replace("ё", "е"), [])
        if not exact:
            exact = self.teacher_aliases.get(raw.casefold(), [])
        if len(exact) == 1:
            return exact[0]
        if len(exact) > 1:
            if warn:
                self._ambiguous(raw, exact)
            return ""

        surname, first, middle = self._name_identity(raw)
        if not surname:
            return ""

        variants = self.teachers_by_surname.get(surname, [])
        if not variants:
            parts = [p for p in re.sub(r"[.,;:()]+", " ", raw.lower().replace("ё", "е")).split() if p]
            if len(parts) == 2 and parts[1] in self.teachers_by_surname:
                surname = parts[1]
                first = parts[0][0]
                middle = ""
                variants = self.teachers_by_surname.get(surname, [])

        if not variants:
            return ""

        if first and middle:
            matches = [
                item["short"] for item in variants
                if item["first"] == first and (not item["middle"] or item["middle"] == middle)
            ]
            if len(matches) == 1:
                return matches[0]
            if len(matches) > 1:
                if warn:
                    self._ambiguous(raw, matches)
                return ""

        if first and not middle:
            matches = [item["short"] for item in variants if item["first"] == first]
            if len(matches) == 1:
                return matches[0]
            if len(matches) > 1:
                if warn:
                    self._ambiguous(raw, matches)
                return ""
            return ""

        if not first:
            if len(variants) == 1:
                return variants[0]["short"]
            if len(variants) > 1:
                if warn:
                    self._ambiguous(raw, [item["short"] for item in variants])
                return ""

        return ""

    @staticmethod
    def _preference_key(value: Any) -> Tuple[str, str]:
        raw = normalize_text(value)
        if not raw.startswith("@") or "|" not in raw:
            return "", ""
        role, subject = raw[1:].split("|", 1)
        role = role.strip().lower()
        subject = subject.strip()
        if role not in TeacherResolver.PREFERENCE_ROLES or not subject:
            return "", ""
        return role, subject

    def _register_preference(self, role: str, subject: str, teacher: str) -> None:
        key = self._subject_key(subject)
        if not key or not teacher:
            return
        preference = self.teacher_assignment_preferences.setdefault(
            key,
            {"lecturer": [], "other": [], "reserve": []},
        )
        bucket = preference[role]
        if teacher not in bucket:
            bucket.append(teacher)
        self._register_subject_candidates(
            subject,
            lecturers=[teacher] if role == "lecturer" else (),
            others=[teacher] if role == "other" else (),
            reserves=[teacher] if role == "reserve" else (),
            prepend=True,
        )

    def _resolve_teacher_list(self, value: Any, *, warn: bool = False) -> List[str]:
        if value is None:
            return []

        if isinstance(value, (list, tuple, set)):
            results: List[str] = []
            for item in value:
                for teacher in self._resolve_teacher_list(item, warn=warn):
                    if teacher not in results:
                        results.append(teacher)
            return results

        raw_str = str(value or "").strip()
        if not raw_str:
            return []

        delimiter_pattern = re.compile(r"(?:[\n,;/\\\\]+|\s+[иИ]\s+)")
        parts = [p.strip() for p in delimiter_pattern.split(raw_str) if p.strip()]

        results: List[str] = []
        if len(parts) > 1:
            for part in parts:
                alias = self._resolve_teacher_alias(part, warn=warn)
                if alias:
                    if alias not in results:
                        results.append(alias)
                    continue

                extracted = self._extract_teachers(part)
                if extracted:
                    for t in extracted:
                        if t not in results:
                            results.append(t)
        else:
            single = self._resolve_teacher_alias(raw_str, warn=warn)
            if single:
                return [single]
            extracted = self._extract_teachers(raw_str)
            if extracted:
                for t in extracted:
                    if t not in results:
                        results.append(t)

        if not results:
            extracted = self._extract_teachers(raw_str)
            for t in extracted:
                if t not in results:
                    results.append(t)

        return results

    def set_teacher_overrides(self, values: Mapping[str, Any] | None) -> Dict[str, str]:
        """Apply hard assignments and role preferences from one compatible map.

        Ordinary keys remain hard, per-subject operator assignments. Keys in
        the form ``@lecturer|Subject``, ``@other|Subject`` and
        ``@reserve|Subject`` are preferences used by the global graph. This
        preserves the existing request schema and old saved sessions.
        """

        normalized: Dict[str, str] = {}
        for raw_subject, raw_teacher in dict(values or {}).items():
            role, preference_subject = self._preference_key(raw_subject)
            if role:
                teachers = self._resolve_teacher_list(raw_teacher, warn=True)
                if teachers:
                    key = self._subject_key(preference_subject)
                    if key:
                        pref = self.teacher_assignment_preferences.setdefault(
                            key, {"lecturer": [], "other": [], "reserve": []}
                        )
                        for t in teachers:
                            if t not in pref[role]:
                                pref[role].append(t)
                    self._register_subject_candidates(
                        preference_subject,
                        lecturers=teachers if role == "lecturer" else (),
                        others=teachers if role == "other" else (),
                        reserves=teachers if role == "reserve" else (),
                        prepend=True,
                    )
                elif normalize_text(raw_teacher):
                    self.warnings.append(
                        f"Настройка для «{preference_subject}» пропущена: "
                        f"преподаватель «{normalize_text(raw_teacher)}» не найден однозначно."
                    )
                continue

            subject_key = self._subject_key(raw_subject)
            if not subject_key or not normalize_text(raw_teacher):
                continue
            teachers = self._resolve_teacher_list(raw_teacher, warn=True)
            if not teachers:
                raw_text = str(raw_teacher or "")
                tokens = [t.strip() for t in re.split(r"(?:[\n,;/\\\\]|\s+[иИ]\s+)", raw_text) if t.strip()]
                has_known_surname = False
                for tok in tokens:
                    s, _, _ = self._name_identity(tok)
                    if s and self.teachers_by_surname.get(s):
                        has_known_surname = True
                        break
                if not has_known_surname:
                    self.warnings.append(
                        f"Ручное назначение для «{normalize_text(raw_subject)}» пропущено: "
                        f"преподаватель «{normalize_text(raw_teacher)}» не найден в пространстве."
                    )
                continue
            normalized[subject_key] = ", ".join(teachers)
            self._register_subject_candidates(
                raw_subject,
                lecturers=teachers,
                others=teachers,
                prepend=True,
            )
        self.teacher_overrides = normalized
        return dict(normalized)

    def _extract_teachers(self, value: Any) -> List[str]:
        text = normalize_text(value)
        if not text:
            return []
        searchable = text.lower().replace("ё", "е")
        found_with_pos: List[Tuple[int, str]] = []
        ambiguous: List[Tuple[str, List[str]]] = []
        for surname, variants in self.teachers_by_surname.items():
            if not re.search(rf"(?<![\w-]){re.escape(surname)}(?![\w-])", searchable, re.I):
                continue

            precise_items: List[Tuple[int, str]] = []
            for item in variants:
                best_p = -1
                for pattern in item["patterns"]:
                    m = pattern.search(text)
                    if m and (best_p == -1 or m.start() < best_p):
                        best_p = m.start()
                if best_p != -1:
                    precise_items.append((best_p, item["short"]))

            precise_dedup: Dict[str, int] = {}
            for pos, short in sorted(precise_items, key=lambda x: x[0]):
                if short not in precise_dedup:
                    precise_dedup[short] = pos
            precise = list(precise_dedup.keys())

            if precise:
                if len(precise) == 1:
                    found_with_pos.append((precise_dedup[precise[0]], precise[0]))
                else:
                    occurrences = len(re.findall(rf"(?<![\w-]){re.escape(surname)}(?![\w-])", searchable, re.I))
                    if occurrences >= len(precise):
                        for short in precise:
                            found_with_pos.append((precise_dedup[short], short))
                    else:
                        ambiguous.append((surname, precise))
                continue

            single_items: List[Tuple[int, str]] = []
            for item in variants:
                best_p = -1
                for p in item.get("single_patterns", []):
                    m = p.search(text)
                    if m and (best_p == -1 or m.start() < best_p):
                        best_p = m.start()
                if best_p != -1:
                    single_items.append((best_p, item["short"]))

            single_dedup: Dict[str, int] = {}
            for pos, short in sorted(single_items, key=lambda x: x[0]):
                if short not in single_dedup:
                    single_dedup[short] = pos
            single_matches = list(single_dedup.keys())

            if single_matches:
                if len(single_matches) == 1:
                    found_with_pos.append((single_dedup[single_matches[0]], single_matches[0]))
                else:
                    occurrences = len(re.findall(rf"(?<![\w-]){re.escape(surname)}(?![\w-])", searchable, re.I))
                    if occurrences >= len(single_matches):
                        for short in single_matches:
                            found_with_pos.append((single_dedup[short], short))
                    else:
                        ambiguous.append((surname, single_matches))
                continue

            if len(variants) == 1:
                m = re.search(rf"(?<![\w-]){re.escape(surname)}(?![\w-])", searchable, re.I)
                pos = m.start() if m else len(text)
                found_with_pos.append((pos, variants[0]["short"]))
            else:
                ambiguous.append((surname, [item["short"] for item in variants]))

        for surname, variants in ambiguous:
            self._ambiguous(surname, variants)

        found_with_pos.sort(key=lambda x: x[0])
        return list(dict.fromkeys(t for _, t in found_with_pos))

    @staticmethod
    def _put_candidate(bucket: List[str], teacher: str, *, prepend: bool) -> None:
        if teacher in bucket:
            if prepend and bucket[0] != teacher:
                bucket.remove(teacher)
                bucket.insert(0, teacher)
            return
        if prepend:
            bucket.insert(0, teacher)
        else:
            bucket.append(teacher)

    def _register_subject_candidates(
        self,
        subject: Any,
        *,
        lecturers: Sequence[str] = (),
        others: Sequence[str] = (),
        reserves: Sequence[str] = (),
        prepend: bool = False,
    ) -> None:
        key = self._subject_key(subject)
        if not key:
            return
        entry = self.teacher_candidate_catalog.setdefault(
            key,
            {"lecturer": [], "other": [], "reserve": [], "all": []},
        )
        for role, values in (
            ("lecturer", lecturers),
            ("other", others),
            ("reserve", reserves),
        ):
            ordered = list(reversed(values)) if prepend else list(values)
            for raw in ordered:
                teacher = self._resolve_teacher_alias(raw) or normalize_text(raw)
                if not teacher:
                    continue
                self._put_candidate(entry[role], teacher, prepend=prepend)
                self._put_candidate(entry["all"], teacher, prepend=False)

    def _record_report_subject(self, subject: str) -> None:
        report = self.last_report
        if not isinstance(report, dict):
            return
        normalized = normalize_text(subject)
        if not normalized:
            return
        subjects = report.setdefault("subjects", [])
        if normalized not in subjects:
            subjects.append(normalized)
        key = self._subject_key(normalized)
        entry = self.teacher_candidate_catalog.get(key, {})
        report.setdefault("teacher_candidates", {})[normalized] = {
            "lecturer": list(entry.get("lecturer") or []),
            "practice": list(entry.get("other") or []),
            "reserve": list(entry.get("reserve") or []),
        }
        preference = self.teacher_assignment_preferences.get(key)
        if preference:
            report.setdefault("teacher_preferences", {})[normalized] = {
                "lecturer": list(preference.get("lecturer") or []),
                "practice": list(preference.get("other") or []),
                "reserve": list(preference.get("reserve") or []),
            }

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
        self._record_report_subject(subject)

        manual = self.teacher_overrides.get(self._subject_key(subject))
        if manual:
            manual_teachers = [t.strip() for t in manual.split(",") if t.strip()]
            if manual_teachers:
                if role == "lecturer":
                    for teacher in manual_teachers:
                        if self.occupancy.get((week, day, pair, teacher)) == subject:
                            return teacher
                counter_key = (subject, lesson_type)
                start = self.subject_counters.get(counter_key, 0)
                for shift in range(len(manual_teachers)):
                    index = (start + shift) % len(manual_teachers)
                    teacher = manual_teachers[index]
                    key = (week, day, pair, teacher)
                    if key not in self.occupancy:
                        self.occupancy[key] = subject
                        self.subject_counters[counter_key] = (index + 1) % len(manual_teachers)
                        return teacher
                teacher = manual_teachers[start % len(manual_teachers)]
                occupied = self.occupancy.get((week, day, pair, teacher), "другая дисциплина")
                self.subject_counters[counter_key] = (start + 1) % len(manual_teachers)
                self.warnings.append(
                    f"Ручное назначение: {teacher} уже занят на {occupied} "
                    f"(неделя {week}, {day}, {pair} пара); коллизия будет "
                    "перепроверена общим графом назначений."
                )
                return teacher

        entry = self.teacher_candidate_catalog.get(self._subject_key(subject), {})
        configured = entry.get(role, [])
        reserve = entry.get("reserve", [])
        teachers = list(dict.fromkeys(
            self._resolve_teacher_alias(item) or normalize_text(item)
            for item in [*configured, *candidates, *reserve]
            if normalize_text(item)
        ))
        if not teachers:
            return "Unknown"
        if role == "lecturer":
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
