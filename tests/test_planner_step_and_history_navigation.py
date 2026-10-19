from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "web" / "frontend" / "assets"
INDEX = ROOT / "web" / "frontend" / "index.html"


def test_history_navigation_buttons_present_in_topbar_steps_and_result_screen() -> None:
    index_html = INDEX.read_text(encoding="utf-8")
    app_css = (ASSETS / "app.css").read_text(encoding="utf-8")

    # Topbar history button
    assert "topbar-history-button" in index_html
    assert "openOperations('history')" in index_html

    # Steps bar history button
    assert "steps-history-button" in index_html
    assert ".steps-history-button" in app_css

    # Result card history button (Step 3)
    assert "result-history-action" in index_html
    assert 'class="btn btn-secondary result-history-action"' in index_html


def test_browser_history_integration_contract() -> None:
    schedule_state = (ASSETS / "schedule-state.js").read_text(encoding="utf-8")

    # pushState called with step and #step- hash
    assert "history.pushState({ step: targetStep }, '', '#step-' + targetStep)" in schedule_state

    # window popstate listener
    assert "window.addEventListener('popstate'" in schedule_state
    assert "canGoToStep(targetStep)" in schedule_state


def test_interactive_step_chips_contract() -> None:
    index_html = INDEX.read_text(encoding="utf-8")
    app_css = (ASSETS / "app.css").read_text(encoding="utf-8")
    schedule_state = (ASSETS / "schedule-state.js").read_text(encoding="utf-8")

    # Step chips are interactive buttons
    assert '<button\n                type="button"\n                class="step-chip"' in index_html or '<button type="button" class="step-chip"' in index_html
    assert "button.step-chip" in app_css
    assert "cursor: pointer" in app_css

    # Step 1: always available for return
    assert '@click="goToStep(1)"' in index_html

    # Step 2: available when files loaded or sessionId exists
    assert ':disabled="!canGoToStep(2)"' in index_html
    assert '@click="goToStep(2)"' in index_html
    assert "analyzedFiles.value.length > 0 || sessionId.value" in schedule_state

    # Step 3: available when result exists
    assert ':disabled="!canGoToStep(3)"' in index_html
    assert '@click="goToStep(3)"' in index_html
    assert "Boolean(result.value)" in schedule_state


def test_back_navigation_from_step2_and_step3() -> None:
    index_html = INDEX.read_text(encoding="utf-8")
    operator_flow = (ASSETS / "operator-flow.js").read_text(encoding="utf-8")
    planner_app = (ASSETS / "planner-app.js").read_text(encoding="utf-8")

    # Step 2 has explicit back buttons to Step 1
    assert "← К исходным файлам" in index_html
    assert "back-to-files-btn" in index_html
    assert "back-to-step1-btn" in index_html
    assert "← К исходным файлам" in operator_flow

    # Step 3 returns to corrections on Step 2
    assert "returnToCorrections" in index_html
    assert "← К исправлениям" in index_html
    assert "returnToCorrections" in planner_app
    assert "schedule.step.value = 2" in planner_app


def test_first_screen_active_session_banner() -> None:
    index_html = INDEX.read_text(encoding="utf-8")
    app_css = (ASSETS / "app.css").read_text(encoding="utf-8")

    assert 'v-if="analyzedFiles.length > 0" class="card session-active-banner"' in index_html
    assert "Загружено файлов: {{ analyzedFiles.length }}" in index_html
    assert "Можно добавить ещё файлы или вернуться к проверке" in index_html
    assert "Продолжить исправление (Шаг 2) →" in index_html
    assert '@click="goToStep(2)"' in index_html
    assert ".session-active-banner" in app_css


def test_non_destructive_navigation_and_session_preservation() -> None:
    schedule_state = (ASSETS / "schedule-state.js").read_text(encoding="utf-8")

    # Navigation does not clear session data
    assert "canGoToStep" in schedule_state
    assert "goToStep" in schedule_state

    # Adding files when session is active preserves existing session
    assert "if (sessionId.value && analyzedFiles.value.length)" in schedule_state
    assert "`/api/analysis/${sessionId.value}/files`" in schedule_state
    assert "Предыдущие файлы и настройки сохранены" in schedule_state

    # Only explicit resetWorkflow deletes session
    assert "resetWorkflow" in schedule_state
    assert "axios.delete(`/api/analysis/${sessionId.value}`)" in schedule_state
