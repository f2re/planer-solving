from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "web" / "frontend" / "assets"


def test_workspace_management_is_embedded_in_operations_center() -> None:
    source = (ASSETS / "unified-operations.js").read_text(encoding="utf-8")

    assert "operations-workspace-section" in source
    assert "operations-workspace-nav" in source
    assert "Данные пространства" in source
    assert "manager-tabs" in source
    assert "modal-content" in source
    assert "workspace-data-button" in source
    assert "operationsTab='workspace'" in source


def test_legacy_manager_redirects_to_unified_center() -> None:
    source = (ASSETS / "unified-operations.js").read_text(encoding="utf-8")

    assert "legacy-workspace-manager" in source
    assert "redirectLegacyModal" in source
    assert "managerTabFromModal" in source
    assert "installUnifiedOperationsRuntime" in source
    assert "insertAdjacentHTML" not in source


def test_unified_operations_is_installed_before_vue_and_runtime_after_mount() -> None:
    bootstrap = (ASSETS / "app.js").read_text(encoding="utf-8")
    editor_markup = (ASSETS / "editor-workspace-markup.js").read_text(encoding="utf-8")

    assert "unified-operations.css" in bootstrap
    assert "import('/assets/unified-operations.js')" in bootstrap
    assert "installUnifiedOperationsRuntime" in bootstrap
    assert bootstrap.index("application.mount()") < bootstrap.index("installUnifiedOperationsRuntime")
    assert "installUnifiedOperationsMarkup" in editor_markup
    assert editor_markup.index("installUnifiedOperationsMarkup();") < editor_markup.rindex("}")


def test_unified_center_has_responsive_styles() -> None:
    styles = (ASSETS / "unified-operations.css").read_text(encoding="utf-8")

    assert ".operations-workspace-section" in styles
    assert ".operations-workspace-content" in styles
    assert ".legacy-workspace-manager" in styles
    assert "@media (max-width: 620px)" in styles
