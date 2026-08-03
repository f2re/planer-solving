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
    assert "resetWorkspaceView" in markup
    assert "event.shiftKey" in state
    assert "full_sheet: true" in state
    assert "synchronizeDerivedLayout" in state
    assert "watch(() => schedule.currentLayout.value" in state
    assert "autoScrollSelection" in state
    assert ".sheet-workspace-open .workflow-grid" in css
    assert "position:fixed" in css
    assert "th.row-number.sheet-header-selected" in css


def test_editor_view_and_window_positions_are_saved_per_workspace():
    state = read("editor-workspace.js")
    assert "planner-editor-view-v" in state
    assert "workspace.activeWorkspaceId.value" in state
    assert "localStorage.setItem(viewStorageKey()" in state
    assert "localStorage.getItem(viewStorageKey())" in state
    assert "dock.files.x" in state
    assert "dock.settings.x" in state
    assert "filesPanelVisible" in state
    assert "settingsPanelVisible" in state
    assert "editorControlsVisible" in state
    assert "sheetZoom" in state
    assert "liveRecalc" in state
    assert "beforeunload" in state
    assert "resetWorkspaceView" in state


def test_parser_recovery_is_editable_and_does_not_block_generation():
    schedule = read("schedule-state.js")
    markup = read("interaction-markup.js")
    css = read("parser-recovery.css")
    assert "const canGenerate = computed(() => enabledFiles.value.length > 0)" in schedule
    assert "allow_partial: true" in schedule
    assert "period_overrides" in schedule
    assert "calendar_overrides" in schedule
    assert "await validateAll();" in schedule
    assert "Исправьте разметку файлов с ошибками" not in schedule
    assert "period-recovery-section" in markup
    assert "Замечания не блокируют результат" in markup
    assert "updatePeriodDate" in markup
    assert "updateWeekMonth" in markup
    assert "applyRecoveredLayout" in markup
    assert "Предупреждения не блокируют формирование" in markup
    assert ".period-recovery-section" in css
    assert ".period-table" in css


def test_workspace_refresh_is_explicit_and_background_synchronized():
    source = read("reactive-workspace.js")
    planner = read("planner-app.js")
    assert "refreshData" in source
    assert "refreshSpaces" in source
    assert "startReactiveSync" in source
    assert "visibilitychange" in source
    assert "workspace.loadData = reactiveWorkspace.refreshData" in planner
    assert "workspace.loadSpaces = reactiveWorkspace.refreshSpaces" in planner


def test_password_policy_is_idempotent_and_cannot_starve_vue_mount():
    source = read("ui-runtime-fixes.js")
    bootstrap = read("app.js")
    assert "removeAttribute(attribute)" in source
    assert "attributeFilter: ['required', 'minlength']" in source
    assert "input.minLength =" not in source
    assert "queueMicrotask(relaxPasswordInputs)" not in source
    assert "window.setTimeout(relaxPasswordInputs" not in source
    assert "if (passwordObserver) return" in source
    assert bootstrap.index("application.mount()") < bootstrap.index("import('/assets/ui-runtime-fixes.js')")


def test_frontend_bootstrap_has_watchdog_and_visible_failure_path():
    source = read("app.js")
    assert "__plannerSolvingBoot" in source
    assert "planner-startup-error" in source
    assert "unhandledrejection" in source
    assert "Превышено время запуска интерфейса" in source
    assert "window.clearTimeout(watchdog)" in source
    assert "if (window[bootKey]?.started) return" in source
    assert "/assets/parser-recovery.css" in source
