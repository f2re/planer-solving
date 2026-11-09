"""Contract tests for interactive teacher mapping flow and auto-recommendations.

Verifies the fix for non-working operator buttons and the new smart teacher
recommendation and autofill interface contracts across frontend and backend.
"""
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict
import pytest

from src.data_loader import DataLoader
from src.operator_issues import build_operator_issues
from src.schedule_analyzer import ScheduleAnalyzer


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "web" / "frontend" / "assets"


def test_schedule_state_handles_open_teacher_mapping_action() -> None:
    """1. schedule-state.js: applyParserAction handles action.type === 'open_teacher_mapping'."""
    source = (ASSETS / "schedule-state.js").read_text(encoding="utf-8")

    assert "applyParserAction" in source
    # Must handle open_teacher_mapping explicitly
    assert "open_teacher_mapping" in source

    # Extract applyParserAction body to verify handler contract
    action_handler_start = source.index("const applyParserAction =")
    action_handler_end = source.index("const validateCurrent =", action_handler_start)
    handler_code = source[action_handler_start:action_handler_end]

    assert "action.type === 'open_teacher_mapping'" in handler_code or "open_teacher_mapping" in handler_code
    assert "openTeacherMapping" in handler_code


def test_teacher_mapping_state_contracts_and_autofill() -> None:
    """2. teacher-mapping-state.js: autoFillAllRecommendations, assignCandidate, tabs, counters, auto-filter."""
    source = (ASSETS / "teacher-mapping-state.js").read_text(encoding="utf-8")

    # Functions for recommendations and assignment
    assert "autoFillAllRecommendations" in source
    assert "assignCandidate" in source

    # Reactive tabs and counters
    assert "teacherMappingTab" in source
    assert "unassignedCount" in source
    assert "configuredCount" in source

    # Returned / exported API
    export_block = source[source.rindex("return {"):]
    for symbol in (
        "autoFillAllRecommendations",
        "assignCandidate",
        "teacherMappingTab",
        "unassignedCount",
        "configuredCount",
        "openTeacherMapping",
        "closeTeacherMapping",
        "saveTeacherMapping",
    ):
        assert symbol in export_block, f"Symbol {symbol} missing in createTeacherMappingState return object"

    # openTeacherMapping should accept issue/action and prefill search / focus by subject
    open_fn_start = source.index("async function openTeacherMapping")
    open_fn_end = source.index("function closeTeacherMapping", open_fn_start)
    open_fn_code = source[open_fn_start:open_fn_end]
    assert "subject" in open_fn_code
    assert "teacherMappingSearch" in open_fn_code


def test_operator_flow_markup_has_recommendations_and_tabs() -> None:
    """3. operator-flow.js: autoFill button, chips, optgroups, and status filter tabs."""
    markup = (ASSETS / "operator-flow.js").read_text(encoding="utf-8")

    # Auto-fill all button
    assert "autoFillAllRecommendations" in markup

    # Recommendation chips (teacher-candidate-chips or chip-btn / assignCandidate)
    assert "assignCandidate" in markup
    assert "teacher-candidate-chips" in markup or "chip-btn" in markup

    # Select optgroups: recommended and all teachers
    assert '<optgroup label="⭐ Рекомендованные">' in markup or 'label="⭐ Рекомендованные"' in markup
    assert '<optgroup label="Все преподаватели">' in markup or 'label="Все преподаватели"' in markup

    # Status filter tabs (Все, Требуют назначения, Назначенные)
    assert "teacherMappingTab" in markup
    assert "Все" in markup
    assert "Требуют назначения" in markup
    assert "Назначенные" in markup


def test_step2_recovery_section_has_teacher_mapping_action() -> None:
    """4. interaction-markup.js: Quick teacher opening button directly on Step 2."""
    markup = (ASSETS / "interaction-markup.js").read_text(encoding="utf-8")

    assert "period-recovery-section" in markup
    recovery_section_start = markup.index("period-recovery-section")
    recovery_section_end = markup.index("const validationTitle =", recovery_section_start)
    section_code = markup[recovery_section_start:recovery_section_end]

    # Quick access button to open teacher mapping from Step 2
    assert "openTeacherMapping" in section_code or "open_teacher_mapping" in section_code


def test_data_loader_and_operator_issues_enriched_open_teacher_mapping_action() -> None:
    """5. data_loader.py & operator_issues.py: open_teacher_mapping enriched with subject & candidates."""
    # Source contract inspection
    loader_source = (ROOT / "src" / "data_loader.py").read_text(encoding="utf-8")
    assert "open_teacher_mapping" in loader_source
    assert "unknown_subjects" in loader_source

    issues_source = (ROOT / "src" / "operator_issues.py").read_text(encoding="utf-8")
    assert "open_teacher_mapping" in issues_source

    # End-to-end integration test: unassigned teacher lessons generate enriched action
    mock_report: Dict[str, Any] = {
        "file": "test_group.xlsx",
        "group": "101",
        "lesson_count": 10,
        "mapped_lessons": 6,
        "unknown_teacher_lessons": 4,
        "unknown_subjects": ["Философия", "Право"],
        "teacher_candidates": {
            "Философия": {"lecturer": ["Иванов И.И."], "other": ["Петров П.П."]},
            "Право": {"lecturer": ["Сидоров С.С."]},
        },
        "warnings": [
            "Для 4 занятий преподаватель не определён; они попадут в раздел «Не назначен»."
        ],
        "errors": [],
        "actions": [
            {
                "type": "open_teacher_mapping",
                "label": "Уточнить преподавателей",
                "subject": "Философия",
                "unknown_subjects": ["Философия", "Право"],
                "candidates": ["Иванов И.И.", "Петров П.П."],
                "blocking": False,
            }
        ],
        "auto_repairs": [],
    }

    issues = build_operator_issues(mock_report)
    teacher_issues = [i for i in issues if i.get("scope") == "teacher" or i.get("category") == "teacher"]
    assert len(teacher_issues) > 0, "Expected at least one teacher issue generated"

    issue = teacher_issues[0]
    actions = issue.get("actions") or []
    mapping_actions = [a for a in actions if a.get("type") == "open_teacher_mapping"]
    assert len(mapping_actions) > 0, "Expected open_teacher_mapping action in issue"

    action = mapping_actions[0]
    assert action.get("subject") == "Философия"
    assert "unknown_subjects" in action
    assert "candidates" in action


def test_data_loader_generates_enriched_open_teacher_mapping_action() -> None:
    """5b. DataLoader produces enriched open_teacher_mapping action with subject & candidates when unassigned."""
    loader = DataLoader("teachers.json")
    analysis = ScheduleAnalyzer().analyze("obrazec/512.xlsx")
    loader.load_group_schedule("obrazec/512.xlsx", "512", analysis.layout)
    report = loader.last_report

    assert report["unknown_teacher_lessons"] > 0
    mapping_actions = [a for a in report["actions"] if a.get("type") == "open_teacher_mapping"]
    assert len(mapping_actions) > 0
    action = mapping_actions[0]
    assert "unknown_subjects" in action
    assert "subject" in action
    assert "candidates" in action

