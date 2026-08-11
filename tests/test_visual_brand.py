import json
import struct
import zlib
from pathlib import Path
from xml.etree import ElementTree


ROOT = Path(__file__).parents[1]
FRONTEND = ROOT / "web" / "frontend"
ASSETS = FRONTEND / "assets"
BRAND = ASSETS / "brand"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def assert_valid_png(path: Path, minimum_size: int) -> None:
    """Validate PNG structure, chunk CRCs and compressed raster data.

    A RIFF/WEBP signature check allowed truncated images to pass previous CI.
    This parser uses only the standard library and therefore also runs inside
    the small offline CI environment.
    """

    payload = path.read_bytes()
    assert path.is_file(), path.name
    assert len(payload) >= minimum_size, path.name
    assert payload.startswith(PNG_SIGNATURE), path.name

    offset = len(PNG_SIGNATURE)
    ihdr = None
    compressed = bytearray()
    saw_iend = False
    while offset < len(payload):
        assert offset + 12 <= len(payload), path.name
        length = struct.unpack(">I", payload[offset:offset + 4])[0]
        kind = payload[offset + 4:offset + 8]
        start = offset + 8
        end = start + length
        assert end + 4 <= len(payload), path.name
        data = payload[start:end]
        expected_crc = struct.unpack(">I", payload[end:end + 4])[0]
        actual_crc = zlib.crc32(kind + data) & 0xFFFFFFFF
        assert actual_crc == expected_crc, f"{path.name}: bad {kind!r} CRC"
        if kind == b"IHDR":
            ihdr = struct.unpack(">IIBBBBB", data)
        elif kind == b"IDAT":
            compressed.extend(data)
        elif kind == b"IEND":
            saw_iend = True
            offset = end + 4
            break
        offset = end + 4

    assert ihdr is not None and compressed and saw_iend, path.name
    width, height, bit_depth, color_type, compression, filter_method, interlace = ihdr
    assert width > 0 and height > 0
    assert bit_depth == 8
    assert color_type in {2, 3, 6}
    assert compression == 0 and filter_method == 0 and interlace == 0
    raster = zlib.decompress(bytes(compressed))
    channels = {2: 3, 3: 1, 6: 4}[color_type]
    assert len(raster) == height * (1 + width * channels), path.name


def test_favicon_and_manifest_are_valid_local_assets():
    svg = FRONTEND / "favicon.svg"
    ico = FRONTEND / "favicon.ico"
    manifest_path = FRONTEND / "site.webmanifest"

    ElementTree.parse(svg)
    assert ico.read_bytes()[:4] == b"\x00\x00\x01\x00"
    assert ico.stat().st_size > 1_000

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["name"].startswith("Борис по парам")
    assert manifest["short_name"] == "Борис по парам"
    assert manifest["display"] == "standalone"
    assert manifest["theme_color"] == "#315efb"
    icon_paths = {item["src"] for item in manifest["icons"]}
    assert "/favicon.svg" in icon_paths
    assert "/assets/brand/app-icon-128.png" in icon_paths
    assert all(not value.startswith(("http://", "https://")) for value in icon_paths)


def test_brand_images_are_decodable_png_files():
    expected = {
        "app-icon-128.png": 1_000,
        "hero-schedule.png": 8_000,
        "organized-flow.png": 7_000,
    }
    for name, minimum_size in expected.items():
        assert_valid_png(BRAND / name, minimum_size)
    assert list(BRAND.glob("*.webp")) == []


def test_brand_module_is_offline_idempotent_and_accessible():
    source = (ASSETS / "brand-refresh.js").read_text(encoding="utf-8")
    assert "installBrandMetadata" in source
    assert "installBrandMarkup" in source
    assert "plannerBrandMetadata" in source
    assert "plannerBrandMarkup" in source
    assert "/favicon.svg" in source
    assert "/favicon.ico" in source
    assert "/site.webmanifest" in source
    assert "/assets/brand/hero-schedule.png" in source
    assert "/assets/brand/organized-flow.png" in source
    assert "type: 'image/png'" in source
    assert "alt=\"Интерфейс «Борис по парам»" in source
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
    clean = (ASSETS / "interface-clean.css").read_text(encoding="utf-8")
    ux = (ASSETS / "ux-flow-2-26.css").read_text(encoding="utf-8")
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
    assert ".result-back-nav" in ux
    assert ".upload-stream-progress" in ux
    assert "url(http" not in source + clean + ux
    assert "url(https" not in source + clean + ux


def test_visual_identity_release_and_documentation():
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    parts = tuple(int(item) for item in version.split(".")[:3])
    assert parts >= (2, 26, 0)

    documentation = (ROOT / "docs" / "VISUAL_IDENTITY.md").read_text(encoding="utf-8")
    assert "Борис по парам" in documentation
    assert "hero-schedule.png" in documentation
    assert "favicon.svg" in documentation
    assert "полностью офлайн" in documentation.lower() or "автоном" in documentation.lower()
