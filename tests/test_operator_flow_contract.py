from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "web" / "frontend" / "assets"
INDEX = ROOT / "web" / "frontend" / "index.html"


def test_operator_flow_is_loaded_before_vue_mount() -> None:
    source = (ASSETS / "app.js").read_text(encoding="utf-8")

    assert "operator-flow.css" in source
    assert "session-file-actions.css" in source
    assert "import('/assets/operator-flow.js')" in source
    assert source.index("installOperatorFlowMarkup") < source.index("application.mount()")
    assert source.index("application.mount()") < source.index("installOperatorFlowRuntime")


def test_operator_flow_keeps_result_editable() -> None:
    source = (ASSETS / "operator-flow.js").read_text(encoding="utf-8")

    assert "Вернуться к проверке" in source
    assert "Открыть и уточнить" in source
    assert "step=2; selectFile(detail.file_id)" in source
    assert "текущий сеанс и все ручные правки сохранены" in source


def test_nonblocking_policy_lives_in_base_template() -> None:
    base = INDEX.read_text(encoding="utf-8")
    enhancements = (ASSETS / "operator-flow.js").read_text(encoding="utf-8")

    assert "Результат создаётся из пригодных данных" in base
    assert "остаются доступными для исправления" in base
    assert "Ничего не блокируется" in enhancements
    assert "Ручная правка необязательна" in enhancements
    assert "function text(" not in enhancements
    assert "document.title =" not in enhancements
    assert "upload-header .page-title" not in enhancements


def test_operator_flow_has_primary_keyboard_actions() -> None:
    source = (ASSETS / "operator-flow.js").read_text(encoding="utf-8")

    assert "event.key.toLowerCase() === 'o'" in source
    assert "#session-add-files" in source
    assert "event.key === 'Enter'" in source
    assert "event.key === 'Escape'" in source


def test_active_session_supports_individual_file_actions() -> None:
    markup = (ASSETS / "operator-flow.js").read_text(encoding="utf-8")
    state = (ASSETS / "session-file-actions.js").read_text(encoding="utf-8")
    application = (ASSETS / "planner-app.js").read_text(encoding="utf-8")

    assert "appendSessionFiles" in markup
    assert "replaceSessionFile" in markup
    assert "removeSessionFile" in markup
    assert "undoRemoveSessionFile" in markup
    assert "createSessionFileActions" in application
    assert "Ранее исправленные файлы не изменены" in state
    assert "Прежний исходник и все правки сохранены" in state


def test_attention_queue_explains_default_and_impact() -> None:
    markup = (ASSETS / "operator-flow.js").read_text(encoding="utf-8")
    state = (ASSETS / "session-file-actions.js").read_text(encoding="utf-8")

    assert "Контроль решений" in markup
    assert "По умолчанию:" in markup
    assert "issue.default_decision" in markup
    assert "issue.impact" in markup
    assert "openAttentionIssue" in markup
    assert "defaultResolution" in state
    assert "attentionIssues" in state


def test_unknown_teachers_can_be_assigned_without_leaving_flow() -> None:
    markup = (ASSETS / "operator-flow.js").read_text(encoding="utf-8")
    state = (ASSETS / "teacher-mapping-state.js").read_text(encoding="utf-8")
    application = (ASSETS / "planner-app.js").read_text(encoding="utf-8")

    assert "Назначить преподавателей" in markup
    assert "Не назначен — безопасное значение" in markup
    assert "openTeacherMapping(issue)" in markup
    assert "saveTeacherMapping" in markup
    assert "teacher_overrides" in state
    assert "createTeacherMappingState" in application
    assert "...teacherMapping" in application


def test_ux_audit_defines_issue_resolution_contract() -> None:
    audit = (ROOT / "docs" / "UX_OPERATOR_FLOW_AUDIT.md").read_text(encoding="utf-8")

    assert "Результат формируется всегда" in audit
    assert '"default_decision"' in audit
    assert '"actions"' in audit
    assert "append/replace/remove" in audit
