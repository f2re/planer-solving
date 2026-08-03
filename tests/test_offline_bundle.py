import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tarfile

from offline.build_bundle import build, copy_application
from offline.verify_bundle import verify_bundle


def test_verify_bundle_detects_tampering(tmp_path: Path) -> None:
    root = tmp_path / "bundle"
    root.mkdir()
    payload = root / "app.txt"
    payload.write_text("ok", encoding="utf-8")
    digest = hashlib.sha256(payload.read_bytes()).hexdigest()
    (root / "manifest.json").write_text(json.dumps({
        "format": "planner-solving-offline",
        "files": {"app.txt": {"sha256": digest, "size": 2}},
    }), encoding="utf-8")
    assert verify_bundle(root)["ok"] is True
    payload.write_text("changed", encoding="utf-8")
    result = verify_bundle(root)
    assert result["ok"] is False
    assert "Контрольная сумма" in result["errors"][0] or "Размер файла" in result["errors"][0]


def test_copy_application_excludes_runtime_data(tmp_path: Path) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    (source / "src").mkdir(parents=True)
    (source / "data").mkdir()
    (source / "src" / "module.py").write_text("x=1", encoding="utf-8")
    (source / "data" / "workspaces.json").write_text("secret", encoding="utf-8")
    (source / "teachers.json").write_text("secret", encoding="utf-8")
    copy_application(source, target)
    assert (target / "src" / "module.py").exists()
    assert not (target / "data" / "workspaces.json").exists()
    assert not (target / "teachers.json").exists()
    assert (target / "data" / ".gitkeep").exists()


def test_build_bundle_with_existing_wheelhouse(tmp_path: Path) -> None:
    root = tmp_path / "project"
    (root / "offline").mkdir(parents=True)
    (root / "src").mkdir()
    (root / "VERSION").write_text("9.9.9\n", encoding="utf-8")
    (root / "requirements-runtime.txt").write_text("example==1\n", encoding="utf-8")
    (root / "src" / "app.py").write_text("value=1\n", encoding="utf-8")
    for name in (
        "install_or_update.sh",
        "rollback.sh",
        "common.sh",
        "verify_bundle.py",
        "runtime.sh",
        "doctor.sh",
    ):
        shutil.copy2(Path(__file__).parents[1] / "offline" / name, root / "offline" / name)
    wheelhouse = tmp_path / "wheels"
    wheelhouse.mkdir()
    (wheelhouse / "example-1-py3-none-any.whl").write_bytes(b"fake wheel for packaging test")
    output = tmp_path / "dist"
    archive = build(argparse.Namespace(
        root=root,
        output=output,
        python="python3",
        use_wheelhouse=wheelhouse,
    ))
    assert archive.exists()
    extracted = tmp_path / "extracted"
    with tarfile.open(archive, "r:gz") as tar:
        tar.extractall(extracted, filter="data")
    bundle_root = next(extracted.iterdir())
    assert verify_bundle(bundle_root)["ok"] is True
    assert (bundle_root / "app" / "src" / "app.py").exists()
    assert (bundle_root / "runtime.sh").is_file()
    assert (bundle_root / "doctor.sh").is_file()
