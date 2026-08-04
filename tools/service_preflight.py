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

from web.backend.recovery_catalog import compact_recommendations


REQUIRED_MODULES = (
    "fastapi",
    "uvicorn",
    "pydantic",
    "openpyxl",
    "pandas",
    "ortools",
    "multipart",
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Проверка окружения службы Planner Solving")
    parser.add_argument("--app-root", type=Path, default=Path.cwd())
    parser.add_argument("--shared-dir", type=Path)
    parser.add_argument(
        "--full",
        action="store_true",
        help="дополнительно создать FastAPI-приложение; применять после миграции данных",
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)

    app_root = args.app_root.resolve()
    shared_dir = (args.shared_dir or app_root / "data").resolve()
    errors: list[str] = []
    warnings: list[str] = []
    issues: list[dict[str, str]] = []
    issue_codes: list[str] = []

    def issue(code: str, message: str, resolution: str) -> None:
        errors.append(message)
        issue_codes.append(code)
        issues.append({"code": code, "message": message, "resolution": resolution})

    def writable_directory(path: Path) -> None:
        try:
            path.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(prefix=".planner-write-", dir=path, delete=True):
                pass
        except OSError as exc:
            issue(
                "storage_unavailable",
                f"Каталог недоступен для записи: {path}: {exc}",
                "Проверьте владельца и права каталога, свободное место и режим файловой системы; затем повторите --check.",
            )

    details: dict[str, Any] = {
        "app_root": str(app_root),
        "shared_dir": str(shared_dir),
        "python": sys.executable,
        "python_version": ".".join(map(str, sys.version_info[:3])),
        "prefix": sys.prefix,
        "base_prefix": sys.base_prefix,
        "full": bool(args.full),
        "modules": {},
    }

    if sys.version_info < (3, 11):
        issue(
            "internal_error",
            f"Требуется Python 3.11+, найден {details['python_version']}.",
            "Используйте встроенный runtime пакета: установщик --python bundled --strict-python --repair.",
        )
    if sys.prefix == sys.base_prefix:
        warnings.append("Служба запущена не из виртуального окружения; штатный systemd должен использовать current/.venv/bin/python.")

    executable = Path(sys.executable)
    if not executable.is_file() or not os.access(executable, os.X_OK):
        issue(
            "internal_error",
            f"Интерпретатор недоступен: {executable}",
            "Проверьте ссылку current и пересоздайте venv установщиком с --repair.",
        )

    for module_name in REQUIRED_MODULES:
        try:
            module = importlib.import_module(module_name)
            details["modules"][module_name] = getattr(module, "__version__", "ok")
        except Exception as exc:  # pragma: no cover - exercised by broken installations
            details["modules"][module_name] = None
            issue(
                "internal_error",
                f"Не импортируется модуль {module_name}: {exc}",
                "Не устанавливайте пакет глобально. Пересоздайте venv выпуска из автономного wheelhouse командой установщика --repair.",
            )

    required_files = (
        app_root / "VERSION",
        app_root / "web" / "backend" / "main.py",
        app_root / "web" / "backend" / "recovery_catalog.py",
        app_root / "web" / "frontend" / "index.html",
        app_root / "requirements-runtime.txt",
    )
    for path in required_files:
        if not path.is_file():
            issue(
                "internal_error",
                f"Отсутствует файл приложения: {path}",
                "Повторно разверните тот же выпуск штатным установщиком с --repair; shared-данные сохранятся.",
            )

    for name in ("data", "input", "output"):
        expected = shared_dir / name if shared_dir.name != name else shared_dir
        if shared_dir.name == "shared":
            expected = shared_dir / name
        elif name == "data":
            expected = shared_dir
        else:
            expected = app_root / name
        writable_directory(expected)

    if args.full:
        previous_base = os.environ.get("PLANNER_BASE_DIR")
        os.environ["PLANNER_BASE_DIR"] = str(app_root)
        try:
            from web.backend.app_factory import create_app

            app = create_app(app_root)
            details["routes"] = len(app.routes)
        except Exception as exc:  # pragma: no cover - exercised by broken installations
            issue(
                "workspace_error",
                f"Приложение не создаётся: {exc}",
                "Запустите planner-solving-doctor, проверьте SQLite и миграции; затем повторите установщик с --repair.",
            )
        finally:
            if previous_base is None:
                os.environ.pop("PLANNER_BASE_DIR", None)
            else:
                os.environ["PLANNER_BASE_DIR"] = previous_base

    details["ok"] = not errors
    details["errors"] = errors
    details["warnings"] = warnings
    details["issues"] = issues
    details["recommendations"] = compact_recommendations(issue_codes)
    details["admin_commands"] = [
        "sudo planner-solving-doctor --output /tmp/planner-solving-doctor.txt",
        "sudo ./install-planner-solving.sh --python bundled --strict-python --repair",
    ]
    if args.as_json:
        print(json.dumps(details, ensure_ascii=False, indent=2, default=str))
    else:
        if errors:
            print("Предварительная проверка службы не пройдена:", file=sys.stderr)
            for item in issues:
                print(f"- [{item['code']}] {item['message']}", file=sys.stderr)
                print(f"  Решение: {item['resolution']}", file=sys.stderr)
            print("Штатные инструменты:", file=sys.stderr)
            for command in details["admin_commands"]:
                print(f"- {command}", file=sys.stderr)
        else:
            suffix = (
                f", маршрутов {details.get('routes', 0)}"
                if args.full
                else ", без открытия базы"
            )
            print(
                "Окружение службы исправно: "
                f"Python {details['python_version']}, модулей {len(REQUIRED_MODULES)}{suffix}."
            )
        for warning in warnings:
            print(f"Предупреждение: {warning}", file=sys.stderr)
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
