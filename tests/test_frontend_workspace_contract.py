from pathlib import Path


ROOT = Path(__file__).parents[1] / "web" / "frontend" / "assets"


def read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_editor_is_fullscreen_reactive_and_supports_shift_selection():
    markup = read("editor-workspace-markup.js")
    state = read("editor-workspace.js")
    css = read("workspace-editor.css")
    assert "Развернуть рабочий лист" in markup
    assert "fitSheetToScreen" in markup
    assert "recalculateNow" in markup
    assert "requestTemplateSave" in markup
    assert "event.shiftKey" in state
    assert "full_sheet: true" in state
    assert "synchronizeDerivedLayout" in state
    assert "watch(() => schedule.currentLayout.value" in state
    assert "autoScrollSelection" in state
    assert ".sheet-workspace-open .workflow-grid" in css
    assert "position:fixed" in css
    assert "th.row-number.sheet-header-selected" in css


def test_workspace_refresh_is_explicit_and_background_synchronized():
    source = read("reactive-workspace.js")
    planner = read("planner-app.js")
    assert "refreshData" in source
    assert "refreshSpaces" in source
    assert "startReactiveSync" in source
    assert "visibilitychange" in source
    assert "workspace.loadData = reactiveWorkspace.refreshData" in planner
    assert "workspace.loadSpaces = reactiveWorkspace.refreshSpaces" in planner


def test_password_inputs_have_no_html_length_or_required_policy():
    source = read("ui-runtime-fixes.js")
    assert "removeAttribute(attribute)" in source
    assert "minlength" in source
    assert ":required" in source
