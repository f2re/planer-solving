from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "web" / "frontend" / "assets"


def test_assignment_dialog_has_three_simple_roles_and_workspace_defaults() -> None:
    state = (ASSETS / "teacher-mapping-state.js").read_text(encoding="utf-8")
    markup = (ASSETS / "operator-flow.js").read_text(encoding="utf-8")

    assert "teacher-assignment-rules" in state
    assert "@lecturer|" not in state  # keys are built, not hard-coded per subject
    assert "configuredTeacherRulesCount" in state
    assert "teacherMappingSaveDefaults" in state
    assert "Использовать эти правила в следующих расписаниях" in markup
    assert ">Лекции<" in markup
    assert ">Практика<" in markup
    assert ">Резерв<" in markup
    assert "Пустое поле оставляет автоматическое распределение" in markup


def test_start_and_result_screens_are_compact_and_result_image_is_reactive() -> None:
    flow = (ASSETS / "operator-flow.js").read_text(encoding="utf-8")
    brand = (ASSETS / "brand-refresh.js").read_text(encoding="utf-8")
    styles = (ASSETS / "interface-clean.css").read_text(encoding="utf-8")

    assert "operator-principles" not in flow
    assert "brand-feature-list" not in flow
    assert "/assets/interface-clean.css" in flow
    assert "decorateResultCard" in brand
    assert "MutationObserver" in brand
    assert "organized-flow.webp" in brand
    assert "grid-template-areas" in styles
    assert "max-height: 790px" in styles
    assert "result-brand-illustration" in styles
    assert "teacher-rule-grid" in styles
