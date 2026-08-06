import json
from pathlib import Path
from xml.etree import ElementTree


ROOT = Path(__file__).parents[1]
FRONTEND = ROOT / "web" / "frontend"
ASSETS = FRONTEND / "assets"
BRAND = ASSETS / "brand"


def test_favicon_and_manifest_are_valid_local_assets():
    svg = FRONTEND / "favicon.svg"
    ico = FRONTEND / "favicon.ico"
    manifest_path = FRONTEND / "site.webmanifest"

    ElementTree.parse(svg)
    assert ico.read_bytes()[:4] == b"\x00\x00\x01\x00"
    assert ico.stat().st_size > 1_000

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["name"].startswith("Planner Solving")
    assert manifest["display"] == "standalone"
    assert manifest["theme_color"] == "#315efb"
    icon_paths = {item["src"] for item in manifest["icons"]}
    assert "/favicon.svg" in icon_paths
    assert "/assets/brand/app-icon-128.webp" in icon_paths
    assert all(not value.startswith(("http://", "https://")) for value in icon_paths)


def test_brand_images_are_bundled_webp_files():
    # File-size thresholds catch empty placeholders without coupling the test
    # to a particular WebP encoder or compression ratio. Resolution and visual
    # composition are part of the reviewed source assets; valid WebP headers
    # and non-trivial payloads are sufficient for the offline bundle contract.
    expected = {
        "app-icon-128.webp": 1_500,
        "hero-schedule.webp": 10_000,
        "organized-flow.webp": 10_000,
    }
    for name, minimum_size in expected.items():
        path = BRAND / name
        payload = path.read_bytes()
        assert path.is_file(), name
        assert len(payload) >= minimum_size, name
        assert payload[:4] == b"RIFF", name
        assert payload[8:12] == b"WEBP", name


def test_brand_module_is_offline_idempotent_and_accessible():
    source = (ASSETS / "brand-refresh.js").read_text(encoding="utf-8")
    assert "installBrandMetadata" in source
    assert "installBrandMarkup" in source
    assert "plannerBrandMetadata" in source
    assert "plannerBrandMarkup" in source
    assert "/favicon.svg" in source
    assert "/favicon.ico" in source
    assert "/site.webmanifest" in source
    assert "/assets/brand/hero-schedule.webp" in source
    assert "/assets/brand/organized-flow.webp" in source
    assert "alt=\"Интерфейс Planner Solving" in source
    assert "alt=\"Готовое организованное расписание" in source
    assert "http://" not in source
    assert "https://" not in source
    assert "decorateResultCard" in source
    assert "MutationObserver" in source


def test_brand_is_installed_before_vue_mount_and_css_is_last():
    source = (ASSETS / "app.js").read_text(encoding="utf-8")
    assert "'/assets/brand-refresh.css'" in source
    assert "import('/assets/brand-refresh.js')" in source
    assert source.index("brand.installBrandMetadata?.()") < source.index("application.mount()")
    assert source.index("brand.installBrandMarkup?.()") < source.index("application.mount()")

    styles = source[source.index("for (const href of ["):source.index("]) {")]
    assert styles.rfind("/assets/brand-refresh.css") > styles.rfind("/assets/unified-operations.css")


def test_brand_styles_cover_start_result_and_accessibility():
    source = (ASSETS / "brand-refresh.css").read_text(encoding="utf-8")
    clean = (ASSETS / "clean-flow-2-21.css").read_text(encoding="utf-8")
    required = (
        ".brand-mark-image",
        ".brand-hero-visual",
        ".dropzone",
        ".result-brand-illustration",
        "@media (max-width: 1040px)",
        "@media (max-width: 620px)",
        "@media (prefers-reduced-motion: reduce)",
    )
    for selector in required:
        assert selector in source
    assert ".teacher-mapping-dialog" in clean
    assert "@media (min-width: 981px) and (max-height: 790px)" in clean
    assert "url(http" not in source + clean
    assert "url(https" not in source + clean


def test_visual_identity_release_and_documentation():
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    parts = tuple(int(item) for item in version.split(".")[:3])
    assert parts >= (2, 18, 0)

    documentation = (ROOT / "docs" / "VISUAL_IDENTITY.md").read_text(encoding="utf-8")
    assert "hero-schedule.webp" in documentation
    assert "favicon.svg" in documentation
    assert "полностью офлайн" in documentation.lower() or "автоном" in documentation.lower()
