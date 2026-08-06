"""Global, deterministic teacher assignment and collision resolution."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
import re
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Sequence, Tuple

UNASSIGNED_TEACHER = "Не назначен"


def _text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _key(value: Any) -> str:
    return re.sub(r"[^0-9a-zа-я]+", "", _text(value).lower().replace("ё", "е"))


def _lesson_type(value: Any) -> str:
    text = _text(value).upper().replace(" ", "")
    match = re.match(
        r"^(ЭКЗАМЕН|КОНС|ЗАЧ|ИКС|ПЗ|ПР|ЛР|ЛТ|ЗЧ|ЗО|ЭКЗ|КР|КП|ГЗ|ПП|ГУ|Л|П|С|У|Э)",
        text,
    )
    if not match:
        return "П"
    code = match.group(1)
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
    }.get(code, code)


def _role(value: Any) -> str:
    return "lecturer" if _lesson_type(value) == "Л" else "other"


def _slot(lesson: Any) -> Tuple[int, str, int]:
    return (
        int(getattr(lesson, "week", 0) or 0),
        _text(getattr(lesson, "day_of_week", "")),
        int(getattr(lesson, "pair_num", 0) or 0),
    )


def _unit_signature(lesson: Any) -> Tuple[str, str, str]:
    """Parallel groups are one unit only for the same actual lesson."""

    return (
        _key(getattr(lesson, "subject", "")),
        _lesson_type(getattr(lesson, "lesson_type_code", "")),
        _key(getattr(lesson, "room", "")),
    )


def _unique(values: Iterable[Any], valid: Mapping[str, str]) -> List[str]:
    result: List[str] = []
    for value in values:
        raw = _text(value)
        canonical = valid.get(raw.casefold().replace("ё", "е"))
        if canonical and canonical not in result:
            result.append(canonical)
    return result


@dataclass
class AssignmentUnit:
    id: int
    slot: Tuple[int, str, int]
    signature: Tuple[str, str, str]
    lessons: List[Any] = field(default_factory=list)
    subject: str = ""
    subject_key: str = ""
    lesson_type: str = ""
    role: str = "other"
    room: str = ""
    current_teacher: str = ""
    manual_teacher: str = ""
    primary: List[str] = field(default_factory=list)
    fallback: List[str] = field(default_factory=list)
    assigned: str = ""
    used_fallback: bool = False

    @property
    def candidates(self) -> List[str]:
        if self.manual_teacher:
            return [self.manual_teacher]
        return [*self.primary, *[value for value in self.fallback if value not in self.primary]]


def _catalog_entry(
    catalog: Mapping[str, Any],
    subject_key: str,
) -> Mapping[str, Sequence[str]]:
    raw = catalog.get(subject_key) or {}
    return raw if isinstance(raw, Mapping) else {}


def _build_units(
    lessons: Sequence[Any],
    *,
    valid_teachers: Mapping[str, str],
    candidate_catalog: Mapping[str, Any],
    manual_overrides: Mapping[str, str],
) -> List[AssignmentUnit]:
    grouped: MutableMapping[Tuple[Tuple[int, str, int], Tuple[str, str, str]], List[Any]]
    grouped = defaultdict(list)
    for lesson in lessons:
        grouped[(_slot(lesson), _unit_signature(lesson))].append(lesson)

    units: List[AssignmentUnit] = []
    for index, ((slot, signature), unit_lessons) in enumerate(
        sorted(
            grouped.items(),
            key=lambda item: (
                item[0][0][0],
                item[0][0][1],
                item[0][0][2],
                item[0][1],
            ),
        ),
        1,
    ):
        sample = unit_lessons[0]
        subject = _text(getattr(sample, "subject", ""))
        subject_key = _key(subject)
        lesson_type = _lesson_type(getattr(sample, "lesson_type_code", ""))
        role = _role(lesson_type)
        entry = _catalog_entry(candidate_catalog, subject_key)
        primary = _unique(entry.get(role) or [], valid_teachers)
        opposite = "other" if role == "lecturer" else "lecturer"
        fallback = _unique(
            [
                *(entry.get(opposite) or []),
                *(entry.get("all") or []),
            ],
            valid_teachers,
        )

        current_raw = _text(getattr(sample, "teacher", ""))
        current = valid_teachers.get(current_raw.casefold().replace("ё", "е"), "")
        if current and current not in primary:
            # The teacher explicitly extracted from a schedule cell is a strong
            # preference, even if the legend was incomplete.
            primary.insert(0, current)

        manual_raw = _text(manual_overrides.get(subject_key))
        manual = valid_teachers.get(manual_raw.casefold().replace("ё", "е"), "")
        if manual and manual not in primary:
            primary.insert(0, manual)

        units.append(AssignmentUnit(
            id=index,
            slot=slot,
            signature=signature,
            lessons=unit_lessons,
            subject=subject,
            subject_key=subject_key,
            lesson_type=lesson_type,
            role=role,
            room=_text(getattr(sample, "room", "")),
            current_teacher=current,
            manual_teacher=manual,
            primary=primary,
            fallback=[value for value in fallback if value not in primary],
        ))
    return units


def _original_conflicts(units: Sequence[AssignmentUnit]) -> Dict[Tuple[int, str, int], Dict[str, List[int]]]:
    result: Dict[Tuple[int, str, int], Dict[str, List[int]]] = {}
    by_slot: MutableMapping[Tuple[int, str, int], MutableMapping[str, List[int]]]
    by_slot = defaultdict(lambda: defaultdict(list))
    for unit in units:
        if unit.current_teacher:
            by_slot[unit.slot][unit.current_teacher].append(unit.id)
    for slot, teachers in by_slot.items():
        conflicts = {teacher: ids for teacher, ids in teachers.items() if len(ids) > 1}
        if conflicts:
            result[slot] = conflicts
    return result


def _candidate_cost(
    unit: AssignmentUnit,
    teacher: str,
    total_load: Counter,
    subject_load: Counter,
) -> Tuple[int, int, int, str]:
    role_penalty = 0 if teacher in unit.primary else 50
    current_penalty = 0 if teacher == unit.current_teacher else 8
    return (
        role_penalty + current_penalty,
        int(subject_load[(teacher, unit.subject_key)]),
        int(total_load[teacher]),
        teacher.casefold(),
    )


def _assign_slot(
    slot_units: Sequence[AssignmentUnit],
    *,
    total_load: Counter,
    subject_load: Counter,
) -> List[AssignmentUnit]:
    """Maximum matching with deterministic, load-aware augmenting paths."""

    occupant: Dict[str, AssignmentUnit] = {}
    unresolved: List[AssignmentUnit] = []

    fixed = [unit for unit in slot_units if unit.manual_teacher]
    movable = [unit for unit in slot_units if not unit.manual_teacher]

    # Manual decisions are hard constraints. A duplicate manual decision is not
    # silently moved: it stays visible as an unresolved collision.
    for unit in sorted(fixed, key=lambda item: item.id):
        teacher = unit.manual_teacher
        if teacher and teacher not in occupant:
            occupant[teacher] = unit
            unit.assigned = teacher
        else:
            unresolved.append(unit)

    def ordered_candidates(unit: AssignmentUnit) -> List[str]:
        return sorted(
            unit.candidates,
            key=lambda teacher: _candidate_cost(unit, teacher, total_load, subject_load),
        )

    def place(unit: AssignmentUnit, visited_teachers: set[str], visited_units: set[int]) -> bool:
        if unit.id in visited_units:
            return False
        visited_units.add(unit.id)
        for teacher in ordered_candidates(unit):
            if teacher in visited_teachers:
                continue
            visited_teachers.add(teacher)
            previous = occupant.get(teacher)
            if previous is None:
                occupant[teacher] = unit
                unit.assigned = teacher
                return True
            if previous.manual_teacher:
                continue
            previous_teacher = previous.assigned
            if place(previous, visited_teachers, visited_units):
                occupant[teacher] = unit
                unit.assigned = teacher
                if previous_teacher and occupant.get(previous_teacher) is previous:
                    occupant.pop(previous_teacher, None)
                return True
        return False

    movable_order = sorted(
        movable,
        key=lambda unit: (
            len(unit.candidates) or 10_000,
            0 if unit.role == "lecturer" else 1,
            unit.subject_key,
            unit.id,
        ),
    )
    for unit in movable_order:
        if not unit.candidates or not place(unit, set(), set()):
            unresolved.append(unit)

    for unit in unresolved:
        unit.assigned = UNASSIGNED_TEACHER

    for unit in slot_units:
        unit.used_fallback = bool(
            unit.assigned
            and unit.assigned != UNASSIGNED_TEACHER
            and unit.assigned not in unit.primary
        )
        weight = max(1, len(unit.lessons))
        if unit.assigned != UNASSIGNED_TEACHER:
            total_load[unit.assigned] += weight
            subject_load[(unit.assigned, unit.subject_key)] += weight
    return unresolved


def _issue(
    *,
    code: str,
    severity: str,
    message: str,
    default_decision: str,
    impact: str,
    resolution: str,
    priority: int,
    items: Sequence[Mapping[str, Any]] = (),
) -> Dict[str, Any]:
    return {
        "code": code,
        "scope": "teacher",
        "category": "conflict",
        "severity": severity,
        "priority": priority,
        "message": message,
        "default_decision": default_decision,
        "impact": impact,
        "resolved": resolution != "unresolved",
        "resolution": resolution,
        "actions": [],
        "action": {},
        "blocking": False,
        "source": "teacher_assignment",
        "items": [dict(item) for item in items],
    }


def resolve_teacher_collisions(
    lessons: Sequence[Any],
    teachers_config: Sequence[Mapping[str, Any]],
    *,
    candidate_catalog: Mapping[str, Any] | None = None,
    manual_overrides: Mapping[str, str] | None = None,
) -> Dict[str, Any]:
    """Resolve teacher collisions globally after every source file was parsed.

    The algorithm builds assignment units for all groups, treats truly parallel
    groups of one lesson as one unit, and performs a deterministic bipartite
    matching for every timetable slot. Role-compatible teachers are preferred;
    role fallback is allowed only when it avoids a collision. Remaining
    impossible assignments are moved to ``Не назначен`` instead of hiding a
    double booking.
    """

    valid_teachers: Dict[str, str] = {}
    for teacher in teachers_config:
        short = _text(teacher.get("short_name") or teacher.get("full_name"))
        full = _text(teacher.get("full_name") or short)
        for alias in (short, full):
            if alias:
                valid_teachers[alias.casefold().replace("ё", "е")] = short

    units = _build_units(
        list(lessons),
        valid_teachers=valid_teachers,
        candidate_catalog=dict(candidate_catalog or {}),
        manual_overrides=dict(manual_overrides or {}),
    )
    original = _original_conflicts(units)
    total_load: Counter = Counter()
    subject_load: Counter = Counter()
    unresolved: List[AssignmentUnit] = []

    slots: MutableMapping[Tuple[int, str, int], List[AssignmentUnit]]
    slots = defaultdict(list)
    for unit in units:
        slots[unit.slot].append(unit)

    for slot in sorted(slots):
        unresolved.extend(_assign_slot(
            slots[slot],
            total_load=total_load,
            subject_load=subject_load,
        ))

    decisions: List[Dict[str, Any]] = []
    reassigned = 0
    fallback_count = 0
    for unit in units:
        before = unit.current_teacher or UNASSIGNED_TEACHER
        after = unit.assigned or UNASSIGNED_TEACHER
        if after != before:
            reassigned += 1
        if unit.used_fallback:
            fallback_count += 1

        for lesson in unit.lessons:
            lesson.teacher = after

        reason = "Назначение сохранено."
        if unit.manual_teacher:
            reason = "Применено ручное назначение оператора."
        elif after == UNASSIGNED_TEACHER:
            reason = "Свободного допустимого преподавателя в этом слоте нет."
        elif unit.used_fallback:
            reason = "Использован резервный преподаватель дисциплины для устранения коллизии."
        elif before != after and unit.current_teacher:
            reason = "Занятие переназначено свободному преподавателю дисциплины."
        elif before != after:
            reason = "Выбран свободный преподаватель с подходящей ролью и меньшей нагрузкой."

        decisions.append({
            "unit_id": unit.id,
            "week": unit.slot[0],
            "day": unit.slot[1],
            "pair": unit.slot[2],
            "groups": sorted({_text(getattr(item, "group", "")) for item in unit.lessons}),
            "subject": unit.subject,
            "lesson_type": unit.lesson_type,
            "role": unit.role,
            "room": unit.room,
            "before": before,
            "after": after,
            "manual": bool(unit.manual_teacher),
            "role_fallback": unit.used_fallback,
            "candidates": list(unit.candidates),
            "reason": reason,
        })

    unresolved_items = [
        item for item in decisions if item["after"] == UNASSIGNED_TEACHER
    ]
    original_count = sum(
        sum(max(0, len(unit_ids) - 1) for unit_ids in teachers.values())
        for teachers in original.values()
    )
    unresolved_count = len(unresolved_items)
    resolved_count = max(0, original_count - unresolved_count)

    issues: List[Dict[str, Any]] = []
    if unresolved_items:
        issues.append(_issue(
            code="teacher_conflicts_unresolved",
            severity="problem",
            priority=100,
            message=f"Не удалось автоматически назначить преподавателя для {len(unresolved_items)} занятий без двойной занятости.",
            default_decision="Неразрешимые занятия помещены в раздел «Не назначен», а не наложены на уже занятого преподавателя.",
            impact="В итоговом расписании не скрывается двойная занятость; оператор видит конкретные занятия для ручного решения.",
            resolution="unresolved",
            items=unresolved_items,
        ))
    if resolved_count:
        resolved_items = [
            item for item in decisions
            if item["before"] != item["after"] and item["after"] != UNASSIGNED_TEACHER
        ]
        issues.append(_issue(
            code="teacher_conflicts_resolved",
            severity="info",
            priority=30,
            message=f"Автоматически устранено конфликтов занятий: {resolved_count}.",
            default_decision="Занятия переданы свободным допустимым преподавателям с учётом роли и нагрузки.",
            impact="Двойная занятость устранена без удаления занятий.",
            resolution="auto",
            items=resolved_items,
        ))
    if fallback_count:
        fallback_items = [item for item in decisions if item["role_fallback"]]
        issues.append(_issue(
            code="teacher_role_fallback",
            severity="attention",
            priority=60,
            message=f"Для устранения коллизий использовано резервных назначений: {fallback_count}.",
            default_decision="Резервный преподаватель выбран только среди преподавателей этой дисциплины.",
            impact="Роль преподавателя отклонена от предпочтительной, но конфликт устранён и занятие сохранено.",
            resolution="default_with_override",
            items=fallback_items,
        ))

    balanced_load = dict(sorted(total_load.items(), key=lambda item: item[0].casefold()))
    load_values = list(balanced_load.values())
    return {
        "algorithm": "slot-bipartite-matching-v1",
        "unit_count": len(units),
        "lesson_count": len(lessons),
        "original_conflict_count": original_count,
        "resolved_conflict_count": resolved_count,
        "unresolved_conflict_count": unresolved_count,
        "reassigned_unit_count": reassigned,
        "role_fallback_count": fallback_count,
        "load_by_teacher": balanced_load,
        "load_spread": (max(load_values) - min(load_values)) if load_values else 0,
        "decisions": decisions,
        "issues": issues,
    }
