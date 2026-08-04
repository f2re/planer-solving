from web.backend.app_factory import create_app


def test_retry_closes_previous_running_row_for_same_session(tmp_path):
    app = create_app(tmp_path)
    repository = app.state.context.workspace_repository
    workspace_id = repository.default_workspace_id()

    first = repository.start_processing_run(
        workspace_id=workspace_id,
        session_id="operator-session",
        actor=None,
        source_count=1,
    )
    second = repository.start_processing_run(
        workspace_id=workspace_id,
        session_id="operator-session",
        actor=None,
        source_count=1,
    )

    first_run = repository.get_processing_run(first)
    second_run = repository.get_processing_run(second)
    assert first_run["status"] == "failed"
    assert first_run["error_count"] >= 1
    assert first_run["report"]["interruption"]["state_preserved"] is True
    assert "повторной" in first_run["report"]["interruption"]["message"].lower()
    assert second_run["status"] == "running"


def test_restart_marks_unfinished_history_as_failed(tmp_path):
    first_app = create_app(tmp_path)
    repository = first_app.state.context.workspace_repository
    workspace_id = repository.default_workspace_id()
    run_id = repository.start_processing_run(
        workspace_id=workspace_id,
        session_id="restart-session",
        actor=None,
        source_count=2,
    )
    assert repository.get_processing_run(run_id)["status"] == "running"

    restarted_app = create_app(tmp_path)
    restarted_repository = restarted_app.state.context.workspace_repository
    recovered = restarted_repository.get_processing_run(run_id)
    assert recovered["status"] == "failed"
    assert recovered["report"]["interruption"]["code"] == "processing_interrupted"
    assert "перезапуск" in recovered["report"]["interruption"]["message"].lower()
