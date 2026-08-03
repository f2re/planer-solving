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
try:
    from src.data_migrations import CURRENT_SCHEMA_VERSION
except ImportError:  # pragma: no cover - standalone packaging fixture
    CURRENT_SCHEMA_VERSION = 0

BUNDLE_FORMAT_VERSION = 3
EXCLUDED_NAMES = {
    ".git", ".github", ".gemini", ".idea", ".vscode", ".venv", "venv", "env",
    "__pycache__", ".pytest_cache", ".offline-cache", "dist", "build", "backups",
    "wheelhouse", "tests",
}
EXCLUDED_RELATIVE = {Path("data"), Path("input"), Path("output")}
SENSITIVE_FILENAMES = {"workspaces.json", "teachers.json", "config.json", "config.local.json"}
SUPPORT_SCRIPTS = (
    "install_or_update.sh",
    "rollback.sh",
    "common.sh",
    "verify_bundle.py",
    "verify_bundle.sh",
    "runtime.sh",
    "doctor.sh",
    "python_discovery.sh",
    "python_runtime.py",
)


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
    if relative.name in SENSITIVE_FILENAMES or relative.name == ".env" or relative.name.startswith(".env."):
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


def run(command: list[str], cwd: Path | None = None, *, capture: bool = False) -> str:
    print("+", " ".join(command))
    if capture:
        return subprocess.check_output(command, cwd=cwd, text=True)
    subprocess.run(command, cwd=cwd, check=True)
    return ""


def target_python_info(executable: str) -> dict[str, Any]:
    code = (
        "import ensurepip,json,platform,sqlite3,ssl,sys,sysconfig,venv;"
        "print(json.dumps({'major':sys.version_info.major,'minor':sys.version_info.minor,"
        "'micro':sys.version_info.micro,'version':platform.python_version(),"
        "'implementation':platform.python_implementation(),'architecture':platform.machine().lower(),"
        "'platform':platform.system().lower(),'libc':platform.libc_ver(),"
        "'base_prefix':sys.base_prefix,'executable':sys.executable,"
        "'soabi':sysconfig.get_config_var('SOABI') or ''}))"
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


def _runtime_info(runtime_dir: Path) -> dict[str, Any]:
    metadata = runtime_dir / "runtime.json"
    launcher = runtime_dir / "python"
    if not metadata.is_file() or not launcher.is_file():
        raise RuntimeError(f"Некорректный Python runtime: {runtime_dir}")
    try:
        info = json.loads(metadata.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Не удалось прочитать {metadata}: {exc}") from exc
    if not isinstance(info, dict):
        raise RuntimeError(f"Некорректный runtime.json: {metadata}")
    return info


def build(args: argparse.Namespace) -> Path:
    root = args.root.resolve()
    support_dir = Path(__file__).resolve().parent
    version = (root / "VERSION").read_text(encoding="utf-8").strip()
    if not version:
        raise RuntimeError("Файл VERSION пуст.")
    python_info = target_python_info(args.python)
    runtime_python = getattr(args, "runtime_python", None) or args.python
    include_runtime = bool(getattr(args, "include_python_runtime", True))
    supplied_runtime = getattr(args, "use_python_runtime", None)

    output_dir = args.output.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    architecture = python_info["architecture"] or "unknown"
    system = python_info["platform"] or "unknown"
    python_tag = f"py{python_info['major']}{python_info['minor']}"
    runtime_tag = "runtime" if include_runtime else "wheels"
    bundle_name = f"planner-solving-offline-{version}-{system}-{architecture}-{python_tag}-{runtime_tag}"

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
        use_wheelhouse = getattr(args, "use_wheelhouse", None)
        if use_wheelhouse:
            cached = Path(use_wheelhouse).resolve()
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

        for script in SUPPORT_SCRIPTS:
            source = support_dir / script
            if not source.is_file():
                raise RuntimeError(f"Отсутствует служебный файл пакета: {source}")
            shutil.copy2(source, stage / script)
        for script in (
            "install_or_update.sh", "rollback.sh", "runtime.sh", "doctor.sh",
            "verify_bundle.sh", "python_discovery.sh",
        ):
            (stage / script).chmod(0o755)

        runtime_info: dict[str, Any] | None = None
        if include_runtime:
            runtime_dir = stage / "python-runtime"
            if supplied_runtime:
                source_runtime = Path(supplied_runtime).resolve()
                runtime_info = _runtime_info(source_runtime)
                shutil.copytree(source_runtime, runtime_dir, symlinks=False)
            else:
                runtime_python_info = target_python_info(runtime_python)
                if (runtime_python_info["major"], runtime_python_info["minor"]) != (
                    python_info["major"], python_info["minor"]
                ):
                    raise RuntimeError("Python runtime и wheelhouse должны иметь одинаковую основную и дополнительную версию.")
                run([
                    runtime_python,
                    str(support_dir / "python_runtime.py"),
                    "export",
                    "--destination",
                    str(runtime_dir),
                ], cwd=root, capture=True)
                runtime_info = _runtime_info(runtime_dir)
            if (int(runtime_info.get("major", -1)), int(runtime_info.get("minor", -1))) != (
                python_info["major"], python_info["minor"]
            ):
                raise RuntimeError("Предоставленный Python runtime не соответствует wheelhouse.")
            if str(runtime_info.get("architecture") or "") != architecture:
                raise RuntimeError("Архитектура Python runtime не соответствует wheelhouse.")

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
                "micro": python_info["micro"],
                "version": python_info["version"],
                "implementation": python_info["implementation"],
                "soabi": python_info["soabi"],
                "runtime_included": include_runtime,
                "runtime_id": (runtime_info or {}).get("runtime_id"),
                "runtime_version": (runtime_info or {}).get("version"),
                "runtime_glibc_required": (runtime_info or {}).get("glibc_required"),
                "libc": python_info.get("libc"),
            },
            "requirements_sha256": sha256(requirements),
            "files": {},
        }
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        manifest["files"] = collect_files(stage, excluded=[manifest_path])
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

        sums_entries = dict(manifest["files"])
        sums_entries["manifest.json"] = {"sha256": sha256(manifest_path), "size": manifest_path.stat().st_size}
        (stage / "SHA256SUMS").write_text(
            "\n".join(
                f"{metadata['sha256']}  {relative}"
                for relative, metadata in sorted(sums_entries.items())
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
        print(f"Python runtime: {'включён' if include_runtime else 'не включён'}")
        if runtime_info:
            print(
                "Runtime: "
                f"{runtime_info.get('version')} / {runtime_info.get('architecture')}; "
                f"GLIBC <= {runtime_info.get('glibc_required') or 'не определено'}"
            )
        print(f"SHA-256: {checksum}")
        return archive


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Сборка автономного пакета Planner Solving")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, default=Path("dist"))
    parser.add_argument("--python", default=sys.executable, help="Python для wheelhouse")
    parser.add_argument("--runtime-python", help="Python, из которого экспортируется встроенный runtime")
    parser.add_argument("--use-wheelhouse", type=Path, help="Использовать готовый wheelhouse")
    parser.add_argument("--use-python-runtime", type=Path, help="Использовать заранее экспортированный runtime")
    parser.add_argument(
        "--without-python-runtime",
        action="store_false",
        dest="include_python_runtime",
        help="создать облегчённый пакет без встроенного Python",
    )
    parser.set_defaults(include_python_runtime=True)
    args = parser.parse_args(argv)
    try:
        build(args)
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"Ошибка сборки: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
