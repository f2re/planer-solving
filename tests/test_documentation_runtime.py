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


def test_parser_documentation_promises_recovery_and_in_place_corrections():
    docs = Path(__file__).parents[1] / "docs"
    guide = (docs / "OPERATOR_GUIDE.md").read_text(encoding="utf-8")
    recovery = (docs / "PARSER_RECOVERY.md").read_text(encoding="utf-8")
    audit = (docs / "PARSER_AUDIT_2_15.md").read_text(encoding="utf-8")
    for source in (guide, recovery, audit):
        lower = source.lower()
        assert "повторн" in lower and ("загруз" in lower or "загруж" in lower)
        assert "не блок" in lower or "без блок" in lower
    assert "переход месяца" in guide.lower()
    assert "Не назначен" in guide
    assert "Сбросить вид" in guide
    assert "диагностический Excel" in recovery
    assert "недел" in audit.lower()


def test_session_draft_documentation_covers_refresh_result_return_and_replacement():
    root = Path(__file__).parents[1]
    guide = (root / "docs" / "OPERATOR_GUIDE.md").read_text(encoding="utf-8")
    draft = (root / "docs" / "SESSION_DRAFT_RECOVERY.md").read_text(encoding="utf-8")
    readme = (root / "README.md").read_text(encoding="utf-8")
    for source in (guide, draft, readme):
        assert "24 час" in source
        assert "Замен" in source or "замен" in source
        assert "чернов" in source.lower()
    assert "F5" in guide
    assert "Вернуться к файлам и правкам" in guide
    assert "GET  /api/analysis/{session_id}" in draft
    assert "POST /api/analysis/{session_id}/files/{file_id}/replace" in draft
    assert "блокировка формирования при критических ошибках" not in readme
    assert "SESSION_DRAFT_RECOVERY.md" in readme
