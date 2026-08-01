"""Build a self-contained, integrity-checked Planner Solving offline bundle."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
from typing import Any, Iterable

ROOT_HINT = Path(__file__).resolve().parents[1]
if str(ROOT_HINT) not in sys.path:
    sys.path.insert(0, str(ROOT_HINT))

from src.data_migrations import CURRENT_SCHEMA_VERSION

BUNDLE_FORMAT_VERSION = 1
EXCLUDED_NAMES = {
    ".git", ".github", ".idea", ".vscode", ".venv", "venv", "env",
    "__pycache__", ".pytest_cache", "dist", "build", "wheelhouse",
}
EXCLUDED_RELATIVE = {Path("data"), Path("input"), Path("output")}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def should_copy(relative: Path) -> bool:
    if any(part in EXCLUDED_NAMES for part in relative.parts):
        return False
    if relative in EXCLUDED_RELATIVE or any(parent in EXCLUDED_RELATIVE for parent in relative.parents):
        return False
    if relative.name.endswith((".pyc", ".pyo", ".log", ".tmp")):
        return False
    if relative.name in {"workspaces.json", "teachers.json"}:
        return False
    return True


def copy_application(source: Path, destination: Path) -> None:
    for path in source.rglob("*"):
        relative = path.relative_to(source)
        if not should_copy(relative):
            continue
        target = destination / relative
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif path.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
    for directory in ("data", "input", "output"):
        (destination / directory).mkdir(parents=True, exist_ok=True)
        (destination / directory / ".gitkeep").touch()


def run(command: list[str], cwd: Path | None = None) -> None:
    print("+", " ".join(command))
    subprocess.run(command, cwd=cwd, check=True)


def target_python_info(executable: str) -> dict[str, Any]:
    code = (
        "import json,platform,sys;"
        "print(json.dumps({'major':sys.version_info.major,'minor':sys.version_info.minor,"
        "'implementation':platform.python_implementation(),'architecture':platform.machine().lower(),"
        "'platform':platform.system().lower()}))"
    )
    try:
        payload = subprocess.check_output([executable, "-c", code], text=True)
        info = json.loads(payload)
    except (OSError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Не удалось проверить целевой Python {executable}: {exc}") from exc
    if (info["major"], info["minor"]) < (3, 11):
        raise RuntimeError("Целевой Python должен быть версии 3.11 или новее.")
    return info


def source_commit(root: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return os.environ.get("GITHUB_SHA", "unknown")


def collect_files(root: Path, excluded: Iterable[Path] = ()) -> dict[str, dict[str, Any]]:
    excluded_resolved = {path.resolve() for path in excluded}
    result: dict[str, dict[str, Any]] = {}
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if path.resolve() in excluded_resolved:
            continue
        relative = path.relative_to(root).as_posix()
        result[relative] = {"sha256": sha256(path), "size": path.stat().st_size}
    return result


def build(args: argparse.Namespace) -> Path:
    root = args.root.resolve()
    version = (root / "VERSION").read_text(encoding="utf-8").strip()
    if not version:
        raise RuntimeError("Файл VERSION пуст.")
    python_info = target_python_info(args.python)

    output_dir = args.output.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    architecture = python_info["architecture"] or "unknown"
    system = python_info["platform"] or "unknown"
    python_tag = f"py{python_info['major']}{python_info['minor']}"
    bundle_name = f"planner-solving-offline-{version}-{system}-{architecture}-{python_tag}"

    with tempfile.TemporaryDirectory(prefix="planner-bundle-") as temporary:
        stage = Path(temporary) / bundle_name
        app_dir = stage / "app"
        wheelhouse = stage / "wheelhouse"
        app_dir.mkdir(parents=True)
        wheelhouse.mkdir(parents=True)
        copy_application(root, app_dir)

        requirements = root / "requirements-runtime.txt"
        if not requirements.exists():
            raise RuntimeError("Отсутствует requirements-runtime.txt.")
        if args.use_wheelhouse:
            cached = args.use_wheelhouse.resolve()
            wheels = list(cached.glob("*.whl"))
            if not wheels:
                raise RuntimeError(f"В каталоге {cached} нет Python-колёс .whl.")
            for path in wheels:
                shutil.copy2(path, wheelhouse / path.name)
        else:
            run([
                args.python, "-m", "pip", "download", "--dest", str(wheelhouse),
                "--requirement", str(requirements), "--only-binary=:all:",
            ], cwd=root)

        for script in ("install_or_update.sh", "rollback.sh", "common.sh", "verify_bundle.py"):
            shutil.copy2(root / "offline" / script, stage / script)
        for script in (stage / "install_or_update.sh", stage / "rollback.sh"):
            script.chmod(0o755)

        manifest_path = stage / "manifest.json"
        manifest = {
            "format": "planner-solving-offline",
            "format_version": BUNDLE_FORMAT_VERSION,
            "app_version": version,
            "data_schema_version": CURRENT_SCHEMA_VERSION,
            "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "source_commit": source_commit(root),
            "platform": system,
            "architecture": architecture,
            "python": {
                "major": python_info["major"],
                "minor": python_info["minor"],
                "implementation": python_info["implementation"],
            },
            "requirements_sha256": sha256(requirements),
            "files": {},
        }
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        manifest["files"] = collect_files(stage, excluded=[manifest_path])
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

        sums = stage / "SHA256SUMS"
        sums.write_text(
            "\n".join(
                f"{metadata['sha256']}  {relative}"
                for relative, metadata in sorted(manifest["files"].items())
            ) + "\n",
            encoding="utf-8",
        )

        archive = output_dir / f"{bundle_name}.tar.gz"
        with tarfile.open(archive, "w:gz", format=tarfile.PAX_FORMAT) as tar:
            tar.add(stage, arcname=bundle_name)
        checksum = sha256(archive)
        (archive.with_suffix(archive.suffix + ".sha256")).write_text(
            f"{checksum}  {archive.name}\n", encoding="utf-8"
        )
        print(f"Создан пакет: {archive}")
        print(f"SHA-256: {checksum}")
        return archive


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Сборка офлайн-пакета Planner Solving")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, default=Path("dist"))
    parser.add_argument("--python", default=sys.executable, help="Python, для которого скачиваются колёса")
    parser.add_argument("--use-wheelhouse", type=Path, help="Не скачивать пакеты, использовать готовый wheelhouse")
    args = parser.parse_args(argv)
    try:
        build(args)
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"Ошибка сборки: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
