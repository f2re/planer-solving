from pathlib import Path


def test_session_recovery_release_is_2_16_or_newer():
    version = (Path(__file__).parents[1] / "VERSION").read_text(encoding="utf-8").strip()
    parts = tuple(int(item) for item in version.split(".")[:3])
    assert parts >= (2, 16, 0)
