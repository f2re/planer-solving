from pathlib import Path

from offline.verify_bundle import verify_frontend


def _manifest(root: Path) -> dict:
    files = {}
    for path in root.rglob("*"):
        if path.is_file():
            files[path.relative_to(root).as_posix()] = {"size": path.stat().st_size, "sha256": "unused"}
    return {"files": files}


def _write_frontend(root: Path, *, include_unified: bool) -> None:
    frontend = root / "app" / "web" / "frontend"
    assets = frontend / "assets"
    assets.mkdir(parents=True)
    (frontend / "index.html").write_text(
        '<link rel="stylesheet" href="assets/app.css">\n'
        '<script src="assets/vue.global.prod.js"></script>\n'
        '<script src="assets/axios.min.js"></script>\n'
        '<script src="assets/app.js"></script>\n',
        encoding="utf-8",
    )
    (assets / "app.css").write_text("body{}\n", encoding="utf-8")
    (assets / "vue.global.prod.js").write_text("globalThis.Vue = {};\n", encoding="utf-8")
    (assets / "axios.min.js").write_text("globalThis.axios = {};\n", encoding="utf-8")
    (assets / "planner-app.js").write_text("export function mount() {}\n", encoding="utf-8")
    (assets / "app.js").write_text(
        "Promise.allSettled([import('/assets/planner-app.js'), "
        "import('/assets/unified-operations.js')]);\n",
        encoding="utf-8",
    )
    if include_unified:
        (assets / "unified-operations.js").write_text(
            "export function installUnifiedOperationsRuntime() {}\n",
            encoding="utf-8",
        )


def test_bundle_verifier_rejects_missing_startup_module(tmp_path):
    _write_frontend(tmp_path, include_unified=False)
    errors, _ = verify_frontend(tmp_path, _manifest(tmp_path))
    assert any("unified-operations.js" in error for error in errors)


def test_bundle_verifier_accepts_complete_startup_chain(tmp_path):
    _write_frontend(tmp_path, include_unified=True)
    errors, checked = verify_frontend(tmp_path, _manifest(tmp_path))
    assert errors == []
    assert checked >= 7
