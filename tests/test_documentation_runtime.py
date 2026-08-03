from pathlib import Path


def test_runtime_documentation_covers_installation_python_discovery_and_diagnostics():
    docs = Path(__file__).parents[1] / "docs"
    installation = (docs / "INSTALLATION.md").read_text(encoding="utf-8")
    troubleshooting = (docs / "TROUBLESHOOTING.md").read_text(encoding="utf-8")
    assert "/opt/planner-solving" in installation
    assert "run-service.sh" in installation
    assert "planner-solving-doctor" in installation
    assert "planner-solving-python" in installation
    assert "встроенный Python" in installation or "встроенный runtime" in installation
    assert "pyenv" in installation
    assert "LD_LIBRARY_PATH" in troubleshooting
    assert "libpython" in troubleshooting
    assert "--list-python" in troubleshooting
    assert "--repair" in troubleshooting
    assert "MutationObserver" in troubleshooting
    assert "ModuleNotFoundError" in troubleshooting
    assert "journalctl -u planner-solving" in troubleshooting
