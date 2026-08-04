from pathlib import Path


ROOT = Path(__file__).parents[1] / "web" / "frontend" / "assets"


def read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_failure_center_handles_every_operator_action_family():
    source = read("failure-recovery.js")
    for action in (
        "retry_request",
        "open_diagnostics",
        "copy_admin_command",
        "copy_incident_id",
        "start_new_session",
        "restore_server_draft",
        "open_history",
        "refresh_workspaces",
        "open_workspace_data",
        "replace_current_file",
        "generate_now",
        "review_session_files",
    ):
        assert action in source
    assert "/api/system/recovery" in source
    assert "planner:failure" in source
    assert "incidentId" in source
    assert "state_preserved" in source
    assert "ACTIONABLE_CODES" in source
    assert "http://" not in source
    assert "https://" not in source


def test_fetch_failures_are_forwarded_without_consuming_response():
    source = read("fetch-recovery.js")
    assert "response.clone().json()" in source
    assert "return response" in source
    assert "planner:failure" in source
    assert "pathname.startsWith('/api/')" in source
    assert "transport: 'fetch'" in source
    assert "path !== '/api/system/recovery'" in source


def test_recovery_interceptors_precede_vue_startup_requests_and_draft_runtime():
    source = read("app.js")
    assert "'/assets/failure-recovery.css'" in source
    assert "import('/assets/failure-recovery.js')" in source
    assert "import('/assets/fetch-recovery.js')" in source
    mount = source.index("application.mount()")
    failure = source.index("failureRecovery.installFailureRecovery?.()")
    fetch = source.index("fetchRecovery.installFetchRecovery?.()")
    draft = source.index("draftRuntime.installSessionDraftRuntime?.()")
    assert failure < fetch < mount < draft


def test_recovery_styles_support_mobile_and_reduced_motion():
    source = read("failure-recovery.css")
    for selector in (
        ".failure-recovery-backdrop",
        ".failure-recovery-dialog",
        ".failure-diagnostics-list",
        ".failure-command",
        "@media (max-width: 620px)",
        "@media (prefers-reduced-motion: reduce)",
    ):
        assert selector in source
