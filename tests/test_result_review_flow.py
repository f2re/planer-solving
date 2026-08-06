from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "web" / "frontend" / "assets"


def test_result_review_flow_is_compiled_before_mount_and_runs_after_mount() -> None:
    app = (ASSETS / "app.js").read_text(encoding="utf-8")
    flow = (ASSETS / "result-review-flow.js").read_text(encoding="utf-8")

    assert "import('/assets/result-review-flow.js')" in app
    assert app.index("installOperatorFlowMarkup") < app.index("installResultReviewMarkup")
    assert app.index("installResultReviewMarkup") < app.index("application.mount()")
    assert app.index("application.mount()") < app.index("installResultReviewRuntime")

    assert "returnToCorrections()" in flow
    assert "selectFile(detail.file_id)" in flow
    assert "Исправить и сформировать заново" in flow


def test_result_review_runtime_restores_both_local_illustrations() -> None:
    flow = (ASSETS / "result-review-flow.js").read_text(encoding="utf-8")

    assert "/assets/brand/hero-schedule.webp" in flow
    assert "/assets/brand/organized-flow.webp" in flow
    assert "decorateStartScreen" in flow
    assert "decorateResultScreen" in flow
    assert "MutationObserver" in flow
    assert "/assets/result-review-flow.css" in flow
    assert "http://" not in flow
    assert "https://" not in flow


def test_result_layout_never_spans_image_over_files_or_actions() -> None:
    css = (ASSETS / "result-review-flow.css").read_text(encoding="utf-8")

    assert '"hero"\n        "art"\n        "files"\n        "actions"' in css
    assert '"files art"' not in css
    assert "max-height: none" in css
    assert "position: static" in css
    assert "background: transparent" in css
    assert "box-shadow: none" in css
