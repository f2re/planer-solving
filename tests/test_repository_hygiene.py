from pathlib import Path

from tools.service_preflight import frontend_asset_errors


ROOT = Path(__file__).resolve().parents[1]


def test_confirmed_repository_artifacts_are_absent() -> None:
    banned = (
        "inspect_bottom.py",
        "inspect_xlsx.py",
        "main.py",
        "run_full_process.py",
        "plan.md",
        "planner-web.service",
        "teacher_schedules.xlsx",
        "web/frontend/assets/bootstrap.min.css",
        "web/frontend/assets/readability.css",
        "web/frontend/assets/clean-flow-2-21.css",
        ".gemini/agents/frontend_developer.toml",
    )
    leaked = [relative for relative in banned if (ROOT / relative).exists()]
    assert leaked == []


def test_runtime_dependencies_match_actual_application_imports() -> None:
    requirements = (ROOT / "requirements-runtime.txt").read_text(encoding="utf-8").casefold()
    preflight = (ROOT / "tools/service_preflight.py").read_text(encoding="utf-8").casefold()
    for package in ("ortools", "pandas", "python-dateutil", "numpy", "protobuf"):
        assert package not in requirements
    for module in ("ortools", "pandas"):
        assert f'"{module}"' not in preflight
    for package in ("openpyxl", "fastapi", "uvicorn", "python-multipart", "pydantic"):
        assert package in requirements


def test_frontend_has_no_unreachable_static_files() -> None:
    errors, checked = frontend_asset_errors(ROOT / "web/frontend")
    assert errors == []
    assert "assets/interface-clean.css" in checked
    assert "assets/ux-flow-2-26.css" in checked
    assert "assets/brand/organized-flow.png" in checked
    assert "favicon.svg" in checked
    assert "site.webmanifest" in checked


def test_obsolete_runtime_patch_is_removed() -> None:
    source = (ROOT / "web/frontend/assets/ui-runtime-fixes.js").read_text(encoding="utf-8")
    assert "installPasswordInputPolicy" in source
    assert "applyEditorRuntimeFixes" not in source
