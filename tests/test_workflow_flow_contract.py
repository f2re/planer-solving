from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_generation_is_available_inside_fullscreen_editor() -> None:
    markup = read("web/frontend/assets/editor-workspace-markup.js")
    app = read("web/frontend/assets/planner-app.js")

    assert '@click="generateFromEditor"' in markup
    assert "Сформировать" in markup
    assert "async () => {\n                generatedFromEditor.value" in app
    assert "await schedule.generate()" in app
    assert ">Выйти</span>" not in markup
    assert "К обычному виду" in markup


def test_result_can_return_to_same_correction_session() -> None:
    markup = read("web/frontend/assets/editor-workspace-markup.js")
    app = read("web/frontend/assets/planner-app.js")

    assert '@click="returnToCorrections"' in markup
    assert "schedule.step.value = 2" in app
    assert "schedule.sessionId.value" in app
    assert "await schedule.loadPreview()" in app
    assert "editor.enterSheetWorkspace(true)" in app


def test_current_run_is_linked_to_history_immediately() -> None:
    app = read("web/frontend/assets/planner-app.js")
    history = read("web/frontend/assets/history-ux.js")
    backend = read("web/backend/workspace_schedule.py")

    assert "schedule.result.value?.run_id" in app
    assert "await platform.selectOperationsTab('history')" in app
    assert "await platform.selectRun(run)" in app
    assert "selectedRun?.report?.session_id === sessionId" in history
    assert '"session_id": session_id' in backend


def test_markup_has_responsive_expert_mode_and_local_styles() -> None:
    markup = read("web/frontend/assets/editor-workspace-markup.js")
    css = read("web/frontend/assets/workflow-audit.css")

    assert "/assets/workflow-audit.css" in markup
    assert "expert-layout-details" in markup
    assert "Точные координаты" in markup
    assert "@media (max-width: 1366px)" in css
    assert ".issue-group-list" in css
