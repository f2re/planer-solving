from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "web" / "frontend" / "assets"


def test_server_draft_runtime_is_optional_but_loaded_after_application() -> None:
    source = (ASSETS / "app.js").read_text(encoding="utf-8")

    assert "session-draft.css" in source
    assert "import('/assets/session-draft-runtime.js')" in source
    assert source.index("application.mount()") < source.index("installSessionDraftRuntime")
    assert "Promise.allSettled" in source


def test_server_draft_runtime_persists_operator_decisions() -> None:
    source = (ASSETS / "session-draft-runtime.js").read_text(encoding="utf-8")

    for required in (
        "file_states",
        "layouts",
        "validations",
        "period_overrides",
        "calendar_overrides",
        "result",
        "base_revision",
    ):
        assert required in source
    assert "planner-active-session-v1" in source
    assert "Черновик изменён в другой вкладке" in source
    assert "Черновик восстановлен" in source
    assert "pagehide" in source
    assert "keepalive" in source
