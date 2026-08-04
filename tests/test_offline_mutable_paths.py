from pathlib import Path

from web.backend.app_context import ApplicationContext, ApplicationPaths


def _link_release(release: Path, shared: Path) -> None:
    for name in ("data", "input", "output"):
        (shared / name).mkdir(parents=True, exist_ok=True)
        (release / name).symlink_to(shared / name, target_is_directory=True)
    (shared / "teachers.json").write_text("[]\n", encoding="utf-8")
    (release / "teachers.json").symlink_to(shared / "teachers.json")


def test_application_uses_shared_targets_from_immutable_release(tmp_path, monkeypatch):
    monkeypatch.delenv("PLANNER_SHARED_DIR", raising=False)
    release = tmp_path / "releases" / "2.19.1-20260804-200000"
    shared = tmp_path / "shared"
    release.mkdir(parents=True)
    shared.mkdir()
    _link_release(release, shared)

    paths = ApplicationPaths.from_base_dir(release)
    assert paths.shared_dir == shared.resolve()
    assert paths.data_dir == (shared / "data").resolve()
    assert paths.input_dir == (shared / "input").resolve()
    assert paths.output_dir == (shared / "output").resolve()
    assert paths.teachers_json == (shared / "teachers.json").resolve()

    # Reproduce the real offline layout: release content is readable but not
    # writable by the service user. Initialization must still create SQLite and
    # compatibility mirrors only under shared.
    release.chmod(0o555)
    context = ApplicationContext(release)

    assert context.paths.teachers_json == (shared / "teachers.json").resolve()
    assert (shared / "data" / "planner-solving.sqlite3").is_file()
    assert (shared / "data" / "workspaces.json").is_file()
    assert (release / "teachers.json").is_symlink()
    assert not (release / "teachers.json.tmp").exists()
    assert not list(release.glob(".teachers.json.*.tmp"))


def test_explicit_shared_directory_has_priority(tmp_path, monkeypatch):
    release = tmp_path / "release"
    shared = tmp_path / "persistent"
    release.mkdir()
    shared.mkdir()
    monkeypatch.setenv("PLANNER_SHARED_DIR", str(shared))

    paths = ApplicationPaths.from_base_dir(release)
    assert paths.shared_dir == shared.resolve()
    assert paths.teachers_json == shared.resolve() / "teachers.json"
    assert paths.session_root == shared.resolve() / "input" / "analysis_sessions"
