from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "web" / "frontend" / "assets"


def test_editor_history_covers_all_operator_file_decisions() -> None:
    source = (ASSETS / "editor-history-state.js").read_text(encoding="utf-8")

    assert "const MAX_HISTORY = 80" in source
    for field in (
        "group_name",
        "enabled",
        "layout",
        "period_overrides",
        "teacher_overrides",
        "calendar_overrides",
    ):
        assert field in source
    assert "delete schedule.validations[file.file_id]" in source
    assert "await schedule.loadPreview()" in source
    assert "window.__plannerSessionDraft?.flush?.()" in source


def test_editor_history_has_keyboard_and_toolbar_controls() -> None:
    state = (ASSETS / "editor-history-state.js").read_text(encoding="utf-8")
    markup = (ASSETS / "editor-workspace-markup.js").read_text(encoding="utf-8")
    application = (ASSETS / "planner-app.js").read_text(encoding="utf-8")

    assert "createEditorHistoryState" in application
    assert "...editorHistory" in application
    assert "undoEditorChange" in state
    assert "redoEditorChange" in state
    assert "event.metaKey || event.ctrlKey" in state
    assert "key === 'z'" in state
    assert "key === 'y'" in state
    assert "sheet-history-undo" in markup
    assert "sheet-history-redo" in markup
    assert '@click="undoEditorChange"' in markup
    assert '@click="redoEditorChange"' in markup


def test_history_is_isolated_per_file_and_reset_on_context_change() -> None:
    state = (ASSETS / "editor-history-state.js").read_text(encoding="utf-8")
    application = (ASSETS / "planner-app.js").read_text(encoding="utf-8")

    assert "const buckets = new Map()" in state
    assert "bucketFor(snapshot.file_id)" in state
    assert "schedule.sessionId.value" in state
    assert "resetEditorHistory" in state
    assert "editorHistory.resetEditorHistory()" in application
