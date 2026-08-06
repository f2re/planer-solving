from pathlib import Path

from offline.build_bundle import (
    BANNED_APPLICATION_FILES,
    BANNED_WHEEL_DISTRIBUTIONS,
    RUNTIME_DOCS,
    copy_application,
    should_copy,
)


ROOT = Path(__file__).resolve().parents[1]


def test_runtime_copy_contains_only_operational_documents(tmp_path: Path) -> None:
    destination = tmp_path / "app"
    destination.mkdir()
    copy_application(ROOT, destination, validate=True)

    copied_docs = {
        path.relative_to(destination).as_posix()
        for path in (destination / "docs").glob("*.md")
    }
    assert copied_docs == {path.as_posix() for path in RUNTIME_DOCS}
    assert not (destination / "offline").exists()
    assert not (destination / "requirements.txt").exists()
    assert not (destination / "GEMINI.md").exists()
    assert all(not (destination / relative).exists() for relative in BANNED_APPLICATION_FILES)


def test_bundle_filter_rejects_build_only_and_sensitive_paths() -> None:
    assert not should_copy(Path("offline/build_bundle.py"))
    assert not should_copy(Path("tests/test_api_workflow.py"))
    assert not should_copy(Path("requirements.txt"))
    assert not should_copy(Path("docs/AUDIT.md"))
    assert should_copy(Path("docs/INSTALLATION.md"))
    assert should_copy(Path("web/frontend/assets/interface-clean.css"))


def test_unused_heavy_wheels_are_explicitly_banned() -> None:
    assert {
        "absl_py", "immutabledict", "numpy", "ortools", "pandas", "protobuf",
        "python_dateutil", "six",
    } <= BANNED_WHEEL_DISTRIBUTIONS
