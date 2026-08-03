from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "web" / "frontend" / "assets"


def test_history_uses_russian_statuses() -> None:
    state = (ASSETS / "history-ux-state.js").read_text(encoding="utf-8")
    markup = (ASSETS / "history-ux.js").read_text(encoding="utf-8")

    assert "Готово с замечаниями" in state
    assert "Частичный результат" in state
    assert "Не завершено" in state
    assert "processingStatusLabel(run.status)" in markup
    assert "processingStatusLabel(selectedRun.status)" in markup


def test_history_exposes_saved_decisions_per_file() -> None:
    state = (ASSETS / "history-ux-state.js").read_text(encoding="utf-8")
    markup = (ASSETS / "history-ux.js").read_text(encoding="utf-8")
    application = (ASSETS / "planner-app.js").read_text(encoding="utf-8")

    assert "historyFileIssues(file)" in markup
    assert "Решения: {{ historyFileIssues(file).length }}" in markup
    assert "По умолчанию:" in markup
    assert "issue.impact" in markup
    assert "Повторить с теми же решениями" in markup
    assert "fallbackIssues" in state
    assert "file?.report?.issues" in state
    assert "createHistoryUxState" in application
    assert "...historyUx" in application


def test_history_modal_is_read_only_and_repeatable() -> None:
    markup = (ASSETS / "history-ux.js").read_text(encoding="utf-8")

    assert "История неизменяема" in markup
    assert "repeatRun(selectedRun)" in markup
    assert "closeHistoryFileDecisions" in markup
