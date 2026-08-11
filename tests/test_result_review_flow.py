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


def test_result_review_runtime_restores_both_local_png_illustrations() -> None:
    flow = (ASSETS / "result-review-flow.js").read_text(encoding="utf-8")

    assert "/assets/brand/hero-schedule.png" in flow
    assert "/assets/brand/organized-flow.png" in flow
    assert ".webp" not in flow
    assert "decorateStartScreen" in flow
    assert "decorateResultScreen" in flow
    assert "MutationObserver" in flow
    assert "/assets/result-review-flow.css" in flow
    assert "http://" not in flow
    assert "https://" not in flow


def test_result_layout_never_spans_image_over_files_or_actions() -> None:
    css = (ASSETS / "result-review-flow.css").read_text(encoding="utf-8")
    ux = (ASSETS / "ux-flow-2-26.css").read_text(encoding="utf-8")

    assert '"hero"\n        "art"\n        "files"\n        "actions"' in css
    assert '"files art"' not in css
    assert "max-height: none" in css
    assert "position: static" in css
    assert "background: transparent" in css
    assert '"nav"\n        "hero"\n        "art"\n        "files"\n        "actions"' in ux


def test_result_actions_have_one_primary_task_and_separate_navigation() -> None:
    brand = (ASSETS / "brand-refresh.js").read_text(encoding="utf-8")
    ux = (ASSETS / "ux-flow-2-26.css").read_text(encoding="utf-8")

    assert "result-back-nav" in brand
    assert "result-back-trigger" in brand
    assert "result-download-primary" in brand
    assert "result-download-secondary" in brand
    assert "result-tertiary-action" in brand
    assert "История формирования" in brand
    assert "Новые файлы" in brand
    assert ".result-card .result-back-trigger" in ux
    assert "display: none !important" in ux
    assert ".result-card .result-download-primary" in ux
    assert ".result-card .result-tertiary-action" in ux


def test_upload_progress_and_review_footer_cannot_compete_with_primary_action() -> None:
    brand = (ASSETS / "brand-refresh.js").read_text(encoding="utf-8")
    ux = (ASSETS / "ux-flow-2-26.css").read_text(encoding="utf-8")

    assert "bottom-duplicate-primary" in brand
    assert "Перепроверить файлы" in brand
    assert "Очистить сеанс" in brand
    assert ".bottom-actions .bottom-duplicate-primary" in ux
    assert ".planner-branded .upload-stream-progress" in ux
    assert "width: 100% !important" in ux
    assert "max-width: 440px" in ux
    assert "overflow-wrap: anywhere" in ux
