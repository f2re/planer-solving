from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "web" / "frontend" / "assets"


def test_operator_flow_is_loaded_before_vue_mount() -> None:
    source = (ASSETS / "app.js").read_text(encoding="utf-8")

    assert "operator-flow.css" in source
    assert "import('/assets/operator-flow.js')" in source
    assert source.index("installOperatorFlowMarkup") < source.index("application.mount()")
    assert source.index("application.mount()") < source.index("installOperatorFlowRuntime")


def test_operator_flow_keeps_result_editable() -> None:
    source = (ASSETS / "operator-flow.js").read_text(encoding="utf-8")

    assert "Вернуться к проверке" in source
    assert "Открыть и уточнить" in source
    assert "step=2; selectFile(detail.file_id)" in source
    assert "текущий сеанс и все ручные правки сохранены" in source


def test_operator_flow_states_nonblocking_policy() -> None:
    source = (ASSETS / "operator-flow.js").read_text(encoding="utf-8")

    assert "Ничего не блокируется" in source
    assert "Результат будет создан в любом случае" in source
    assert "спорные решения сохраняются для последующей правки" in source


def test_operator_flow_has_primary_keyboard_actions() -> None:
    source = (ASSETS / "operator-flow.js").read_text(encoding="utf-8")

    assert "event.key.toLowerCase() === 'o'" in source
    assert "event.key === 'Enter'" in source
    assert "event.key === 'Escape'" in source


def test_ux_audit_defines_issue_resolution_contract() -> None:
    audit = (ROOT / "docs" / "UX_OPERATOR_FLOW_AUDIT.md").read_text(encoding="utf-8")

    assert "Результат формируется всегда" in audit
    assert '"default_decision"' in audit
    assert '"actions"' in audit
    assert "append/replace/remove" in audit
