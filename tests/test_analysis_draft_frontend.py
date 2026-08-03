from pathlib import Path


ROOT = Path(__file__).parents[1] / "web" / "frontend" / "assets"


def read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_schedule_draft_is_saved_server_side_and_restored_after_reload():
    draft = read("schedule-draft.js")
    planner = read("planner-app.js")
    assert "planner-analysis-session-v2" in draft
    assert "axios.put(`/api/analysis/${id}/draft`" in draft
    assert "axios.get(`/api/analysis/${stored.session_id}`" in draft
    assert "period_overrides" in draft
    assert "calendar_overrides" in draft
    assert "layouts" in draft
    assert "keepalive: true" in draft
    assert "beforeunload" in draft
    assert "restoreDraft" in planner
    assert "reactiveWorkspace.refreshWorkspace(restored.workspace_id" in planner


def test_result_can_return_to_the_problem_file_without_deleting_session():
    draft = read("schedule-draft.js")
    markup = read("session-draft-markup.js")
    css = read("session-draft.css")
    assert "returnToCorrections" in draft
    assert "openResultFile" in draft
    assert "schedule.step.value = 2" in draft
    assert "Вернуться к файлам и правкам" in markup
    assert "Открыть и исправить" in markup
    assert "resultCorrections" in markup
    assert "resultProblemFiles" in markup
    assert ".result-corrections-panel" in css
    assert ".analysis-draft-status" in css


def test_bootstrap_loads_new_draft_styles_and_markup_before_mount():
    app = read("app.js")
    planner = read("planner-app.js")
    assert "/assets/session-draft.css" in app
    assert "installSessionDraftMarkup();" in planner
    assert planner.index("installSessionDraftMarkup();") < planner.index("createApp({")
