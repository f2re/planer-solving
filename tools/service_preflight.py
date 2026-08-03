"""Fast, offline-safe checks executed before the systemd service starts."""
from __future__ import annotations

import argparse
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any


REQUIRED_MODULES = (
    "fastapi",
    "uvicorn",
    "pydantic",
    "openpyxl",
    "pandas",
    "ortools",
    "multipart",
)


def _writable_directory(path: Path, errors: list[str]) -> None:
    try:
        path.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(prefix=".planner-write-", dir=path, delete=True):
            pass
    except OSError as exc:
        errors.append(f"Каталог недоступен для записи: {path}: {exc}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Проверка окружения службы Planner Solving")
    parser.add_argument("--app-root", type=Path, default=Path.cwd())
    parser.add_argument("--shared-dir", type=Path)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)

    app_root = args.app_root.resolve()
    shared_dir = (args.shared_dir or app_root / "data").resolve()
    errors: list[str] = []
    warnings: list[str] = []
    details: dict[str, Any] = {
        "app_root": str(app_root),
        "shared_dir": str(shared_dir),
        "python": sys.executable,
        "python_version": ".".join(map(str, sys.version_info[:3])),
        "prefix": sys.prefix,
        "base_prefix": sys.base_prefix,
        "modules": {},
    }

    if sys.version_info < (3, 11):
        errors.append(f"Требуется Python 3.11+, найден {details['python_version']}.")
    if sys.prefix == sys.base_prefix:
        warnings.append("Служба запущена не из виртуального окружения.")

    executable = Path(sys.executable)
    if not executable.is_file() or not os.access(executable, os.X_OK):
        errors.append(f"Интерпретатор недоступен: {executable}")

    for module_name in REQUIRED_MODULES:
        try:
            module = importlib.import_module(module_name)
            details["modules"][module_name] = getattr(module, "__version__", "ok")
        except Exception as exc:  # pragma: no cover - exercised by broken installations
            details["modules"][module_name] = None
            errors.append(f"Не импортируется модуль {module_name}: {exc}")

    required_files = (
        app_root / "VERSION",
        app_root / "web" / "backend" / "main.py",
        app_root / "web" / "frontend" / "index.html",
        app_root / "requirements-runtime.txt",
    )
    for path in required_files:
        if not path.is_file():
            errors.append(f"Отсутствует файл приложения: {path}")

    for name in ("data", "input", "output"):
        expected = shared_dir / name if shared_dir.name != name else shared_dir
        if shared_dir.name == "shared":
            expected = shared_dir / name
        elif name == "data":
            expected = shared_dir
        else:
            expected = app_root / name
        _writable_directory(expected, errors)

    previous_base = os.environ.get("PLANNER_BASE_DIR")
    os.environ["PLANNER_BASE_DIR"] = str(app_root)
    try:
        from web.backend.app_factory import create_app

        app = create_app(app_root)
        details["routes"] = len(app.routes)
    except Exception as exc:  # pragma: no cover - exercised by broken installations
        errors.append(f"Приложение не создаётся: {exc}")
    finally:
        if previous_base is None:
            os.environ.pop("PLANNER_BASE_DIR", None)
        else:
            os.environ["PLANNER_BASE_DIR"] = previous_base

    details["ok"] = not errors
    details["errors"] = errors
    details["warnings"] = warnings
    if args.as_json:
        print(json.dumps(details, ensure_ascii=False, indent=2, default=str))
    else:
        if errors:
            print("Предварительная проверка службы не пройдена:", file=sys.stderr)
            for error in errors:
                print(f"- {error}", file=sys.stderr)
        else:
            print(
                "Окружение службы исправно: "
                f"Python {details['python_version']}, модулей {len(REQUIRED_MODULES)}, "
                f"маршрутов {details.get('routes', 0)}."
            )
        for warning in warnings:
            print(f"Предупреждение: {warning}", file=sys.stderr)
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
