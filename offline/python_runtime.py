#!/usr/bin/env python3
"""Export a managed CPython runtime for offline installation.

The runtime is not a universal Python distribution: it is a stable copy of a
working interpreter, its standard library, libpython and non-glibc shared
libraries. The installer probes it on the target host before activation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import sysconfig
from typing import Iterable

EXCLUDED_DIR_NAMES = {
    "__pycache__",
    "site-packages",
    "dist-packages",
    "test",
    "tests",
    "idle_test",
}

GLIBC_CORE_PREFIXES = (
    "ld-linux",
    "ld-musl",
    "libc.so",
    "libm.so",
    "libpthread.so",
    "libdl.so",
    "librt.so",
    "libresolv.so",
    "libutil.so",
    "libanl.so",
    "libBrokenLocale.so",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_tree(source: Path, destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination)

    def ignore(_directory: str, names: list[str]) -> set[str]:
        return {
            name
            for name in names
            if name in EXCLUDED_DIR_NAMES or name.endswith((".pyc", ".pyo"))
        }

    shutil.copytree(source, destination, symlinks=False, ignore=ignore)


def _base_executable() -> Path:
    version = f"python{sys.version_info.major}.{sys.version_info.minor}"
    base = Path(sys.base_prefix)
    candidates = [
        Path(getattr(sys, "_base_executable", "") or ""),
        base / "bin" / version,
        base / "bin" / "python3",
        base / "bin" / "python",
        Path(sys.executable),
    ]
    for candidate in candidates:
        if not str(candidate):
            continue
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved.is_file() and os.access(resolved, os.X_OK):
            return resolved
    raise RuntimeError("Не найден исполняемый файл базового Python.")


def _stdlib_path() -> Path:
    version = f"python{sys.version_info.major}.{sys.version_info.minor}"
    candidates = [
        Path(sysconfig.get_path("stdlib") or ""),
        Path(sys.base_prefix) / "lib" / version,
        Path(sys.base_prefix) / "lib64" / version,
    ]
    for candidate in candidates:
        if candidate.is_dir() and (candidate / "os.py").is_file():
            return candidate.resolve()
    raise RuntimeError("Не найден каталог стандартной библиотеки Python.")


def _dependency_paths(binaries: Iterable[Path]) -> set[Path]:
    if not shutil.which("ldd"):
        return set()
    result: set[Path] = set()
    mapped = re.compile(r"=>\s+(/[^\s]+)")
    direct = re.compile(r"^\s*(/[^\s]+)\s+\(")
    for binary in binaries:
        try:
            output = subprocess.check_output(
                ["ldd", str(binary)],
                text=True,
                stderr=subprocess.STDOUT,
                env=os.environ.copy(),
            )
        except (OSError, subprocess.CalledProcessError):
            continue
        for line in output.splitlines():
            match = mapped.search(line) or direct.search(line)
            if not match:
                continue
            path = Path(match.group(1))
            if path.is_file():
                result.add(path)
    return result


def _is_glibc_core(path: Path) -> bool:
    return path.name.startswith(GLIBC_CORE_PREFIXES)


def _copy_runtime_libraries(base: Path, stdlib: Path, executable: Path, destination: Path) -> list[str]:
    destination.mkdir(parents=True, exist_ok=True)
    copied: dict[str, Path] = {}

    search_dirs = {
        base / "lib",
        base / "lib64",
        Path(sysconfig.get_config_var("LIBDIR") or ""),
    }
    configured_name = str(sysconfig.get_config_var("LDLIBRARY") or "")
    for directory in search_dirs:
        if not directory.is_dir():
            continue
        for pattern in ("libpython*.so*", "libpython*.dylib"):
            for path in directory.glob(pattern):
                if path.is_file():
                    copied.setdefault(path.name, path.resolve())
        if configured_name:
            path = directory / configured_name
            if path.is_file():
                copied.setdefault(path.name, path.resolve())

    dynload = stdlib / "lib-dynload"
    binaries = [executable]
    if dynload.is_dir():
        binaries.extend(path for path in dynload.glob("*.so") if path.is_file())

    for dependency in _dependency_paths(binaries):
        if _is_glibc_core(dependency):
            continue
        copied.setdefault(dependency.name, dependency)

    for name, source in sorted(copied.items()):
        target = destination / name
        shutil.copy2(source, target, follow_symlinks=True)
        mode = target.stat().st_mode
        if os.access(source, os.X_OK):
            target.chmod(mode | 0o111)
    return sorted(copied)


def _glibc_requirement(binaries: Iterable[Path]) -> str:
    if not shutil.which("objdump"):
        return ""
    versions: list[tuple[int, ...]] = []
    pattern = re.compile(r"GLIBC_(\d+(?:\.\d+)*)")
    for binary in binaries:
        try:
            output = subprocess.check_output(
                ["objdump", "-T", str(binary)],
                text=True,
                stderr=subprocess.DEVNULL,
            )
        except (OSError, subprocess.CalledProcessError):
            continue
        for match in pattern.finditer(output):
            versions.append(tuple(int(part) for part in match.group(1).split(".")))
    if not versions:
        return ""
    maximum = max(versions)
    return ".".join(str(part) for part in maximum)


def inspect_runtime() -> dict[str, object]:
    executable = _base_executable()
    stdlib = _stdlib_path()
    dynload = stdlib / "lib-dynload"
    binaries = [executable]
    if dynload.is_dir():
        binaries.extend(path for path in dynload.glob("*.so") if path.is_file())
    version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    digest = hashlib.sha256()
    digest.update(version.encode())
    digest.update(platform.machine().lower().encode())
    digest.update(_sha256(executable).encode())
    return {
        "version": version,
        "major": sys.version_info.major,
        "minor": sys.version_info.minor,
        "micro": sys.version_info.micro,
        "implementation": platform.python_implementation(),
        "architecture": platform.machine().lower(),
        "platform": platform.system().lower(),
        "libc": list(platform.libc_ver()),
        "glibc_required": _glibc_requirement(binaries),
        "source_executable": str(executable),
        "source_base_prefix": str(Path(sys.base_prefix).resolve()),
        "source_stdlib": str(stdlib),
        "soabi": str(sysconfig.get_config_var("SOABI") or ""),
        "runtime_id": digest.hexdigest()[:16],
    }


def export_runtime(destination: Path) -> dict[str, object]:
    info = inspect_runtime()
    destination = destination.resolve()
    temporary = destination.with_name(destination.name + f".tmp-{os.getpid()}")
    if temporary.exists():
        shutil.rmtree(temporary)
    temporary.mkdir(parents=True)

    prefix = temporary / "prefix"
    bin_dir = prefix / "bin"
    lib_dir = prefix / "lib"
    version_xy = f"{info['major']}.{info['minor']}"
    executable = Path(str(info["source_executable"]))
    stdlib = Path(str(info["source_stdlib"]))
    bin_dir.mkdir(parents=True)
    lib_dir.mkdir(parents=True)

    real_name = f"python{version_xy}"
    shutil.copy2(executable, bin_dir / real_name, follow_symlinks=True)
    (bin_dir / real_name).chmod(0o755)
    _copy_tree(stdlib, lib_dir / f"python{version_xy}")
    libraries = _copy_runtime_libraries(
        Path(str(info["source_base_prefix"])),
        stdlib,
        executable,
        lib_dir,
    )

    launcher = temporary / "python"
    launcher.write_text(
        "#!/bin/sh\n"
        "set -eu\n"
        "ROOT=$(CDPATH= cd -- \"$(dirname -- \"$0\")\" && pwd)\n"
        "PREFIX=\"$ROOT/prefix\"\n"
        f"REAL=\"$PREFIX/bin/{real_name}\"\n"
        "export PYTHONHOME=\"$PREFIX\"\n"
        "export PYTHONNOUSERSITE=1\n"
        "export PYTHONDWRITEBYTECODE=1\n"
        "export LD_LIBRARY_PATH=\"$PREFIX/lib:$PREFIX/lib64${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}\"\n"
        "exec \"$REAL\" \"$@\"\n",
        encoding="utf-8",
    )
    launcher.chmod(0o755)

    info["libraries"] = libraries
    info["launcher"] = "python"
    info["prefix"] = "prefix"
    (temporary / "runtime.json").write_text(
        json.dumps(info, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    probe = subprocess.run(
        [
            str(launcher),
            "-c",
            (
                "import ensurepip,json,platform,sqlite3,ssl,sys,venv; "
                "print(json.dumps({'version':list(sys.version_info[:3]),"
                "'prefix':sys.prefix,'base_prefix':sys.base_prefix,"
                "'arch':platform.machine().lower()}))"
            ),
        ],
        text=True,
        capture_output=True,
        env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
    )
    if probe.returncode != 0:
        shutil.rmtree(temporary, ignore_errors=True)
        raise RuntimeError(
            "Экспортированный Python не запускается: "
            + (probe.stderr.strip() or probe.stdout.strip() or f"код {probe.returncode}")
        )

    if destination.exists():
        shutil.rmtree(destination)
    temporary.replace(destination)
    return info


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Подготовка управляемого Python runtime")
    subparsers = parser.add_subparsers(dest="command", required=True)
    inspect_parser = subparsers.add_parser("inspect")
    inspect_parser.add_argument("--json", action="store_true")
    export_parser = subparsers.add_parser("export")
    export_parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "inspect":
            info = inspect_runtime()
        else:
            info = export_runtime(args.destination)
        print(json.dumps(info, ensure_ascii=False, indent=2))
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"Ошибка подготовки Python runtime: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
