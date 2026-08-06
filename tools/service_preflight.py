"""Fast, offline-safe checks executed before the systemd service starts."""
from __future__ import annotations

import argparse
import importlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Any

try:
    from web.backend.recovery_catalog import compact_recommendations
except Exception:  # The preflight must explain an incomplete release, not crash on import.
    def compact_recommendations(_codes: list[str]) -> list[dict[str, Any]]:
        return []


REQUIRED_MODULES = (
    "fastapi",
    "uvicorn",
    "pydantic",
    "openpyxl",
    "multipart",
)
REQUIRED_FRONTEND_FILES = (
    "index.html",
    "assets/app.css",
    "assets/app.js",
    "assets/vue.global.prod.js",
    "assets/axios.min.js",
    "assets/planner-app.js",
    "assets/unified-operations.js",
)
LOCAL_ASSET_RE = re.compile(
    r"[\'\"](/(?:assets/[A-Za-z0-9_./-]+|favicon\.(?:svg|ico)|site\.webmanifest))[\'\"]"
)
HTML_ASSET_RE = re.compile(
    r"(?:src|href)=[\'\"](/?(?:assets/[^\'\"]+|favicon\.(?:svg|ico)|site\.webmanifest))[\'\"]"
)
CSS_URL_RE = re.compile(r"url\(\s*[\'\"]?([^\'\")]+)[\'\"]?\s*\)")
STATIC_IMPORT_RE = re.compile(r"\bfrom\s+[\'\"](\.[^\'\"]+\.js)[\'\"]")
SIDE_EFFECT_IMPORT_RE = re.compile(r"\bimport\s+[\'\"](\.[^\'\"]+\.js)[\'\"]")
DYNAMIC_IMPORT_RE = re.compile(r"\bimport\s*\(\s*[\'\"](\.[^\'\"]+\.js)[\'\"]\s*\)")


def frontend_asset_errors(frontend_dir: Path) -> tuple[list[str], list[str]]:
    """Validate entrypoints, local dependency closure and orphan assets."""

    frontend = frontend_dir.resolve()
    errors: list[str] = []
    checked: list[str] = []
    queue: list[Path] = []
    visited: set[Path] = set()

    def add(path: Path) -> None:
        resolved = path.resolve(strict=False)
        try:
            resolved.relative_to(frontend)
        except ValueError:
            errors.append(f"Ссылка интерфейса выходит за каталог frontend: {path}")
            return
        if resolved not in visited and resolved not in queue:
            queue.append(resolved)

    for relative in REQUIRED_FRONTEND_FILES:
        add(frontend / relative)
    for relative in ("favicon.svg", "favicon.ico", "site.webmanifest"):
        add(frontend / relative)

    while queue:
        path = queue.pop(0)
        if path in visited:
            continue
        visited.add(path)
        relative = path.relative_to(frontend).as_posix()
        if not path.is_file():
            errors.append(f"Отсутствует файл интерфейса: {relative}")
            continue
        try:
            if path.stat().st_size <= 0:
                errors.append(f"Пустой файл интерфейса: {relative}")
                continue
            checked.append(relative)
            if path.suffix not in {".html", ".js", ".css", ".webmanifest"}:
                continue
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            errors.append(f"Файл интерфейса недоступен: {relative}: {exc}")
            continue

        for absolute in LOCAL_ASSET_RE.findall(source):
            add(frontend / absolute.removeprefix("/"))
        if path.suffix == ".html":
            for reference in HTML_ASSET_RE.findall(source):
                add(frontend / reference.lstrip("/"))
        elif path.suffix == ".css":
            for reference in CSS_URL_RE.findall(source):
                if reference.startswith(("data:", "http://", "https://", "#")):
                    continue
                add(
                    frontend / reference.lstrip("/")
                    if reference.startswith("/")
                    else path.parent / reference
                )
        elif path.suffix == ".js":
            relative_imports = (
                STATIC_IMPORT_RE.findall(source)
                + SIDE_EFFECT_IMPORT_RE.findall(source)
                + DYNAMIC_IMPORT_RE.findall(source)
            )
            for imported in relative_imports:
                add(path.parent / imported)

    inventory = {
        path.resolve()
        for path in frontend.rglob("*")
        if path.is_file()
    }
    for path in sorted(inventory - visited):
        errors.append(
            "Неиспользуемый файл интерфейса: "
            + path.relative_to(frontend).as_posix()
        )

    return errors, sorted(set(checked))


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
        "mutable_targets": {},
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
        app_root / "web" / "frontend" / "assets" / "app.js",
        app_root / "web" / "frontend" / "assets" / "unified-operations.js",
        app_root / "requirements-runtime.txt",
    )
    for path in required_files:
        if not path.is_file():
            issue(
                "internal_error",
                f"Отсутствует файл приложения: {path}",
                "Повторно разверните тот же выпуск штатным установщиком с --repair; shared-данные сохранятся.",
            )

    frontend_errors, frontend_checked = frontend_asset_errors(app_root / "web" / "frontend")
    details["frontend_assets"] = frontend_checked
    for message in frontend_errors:
        issue(
            "internal_error",
            message,
            "Автономный пакет неполон или смешаны версии файлов. Повторно скопируйте архив и .sha256, затем выполните установщик с --repair.",
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

    installed_layout = shared_dir.name == "shared" and (
        (app_root / "teachers.json").is_symlink()
        or os.environ.get("PLANNER_SHARED_DIR")
    )
    if installed_layout:
        expected_targets = {
            "data": shared_dir / "data",
            "input": shared_dir / "input",
            "output": shared_dir / "output",
            "teachers.json": shared_dir / "teachers.json",
        }
        for name, expected in expected_targets.items():
            logical = app_root / name
            resolved = logical.resolve(strict=False)
            expected_resolved = expected.resolve(strict=False)
            details["mutable_targets"][name] = str(resolved)
            if resolved != expected_resolved:
                issue(
                    "storage_unavailable",
                    f"Изменяемый путь {logical} ведёт в {resolved}, ожидался {expected_resolved}.",
                    "Не меняйте права каталога выпуска. Повторите установку с --repair: установщик восстановит ссылки на shared.",
                )
        writable_directory(shared_dir)

    if args.full:
        previous_base = os.environ.get("PLANNER_BASE_DIR")
        previous_shared = os.environ.get("PLANNER_SHARED_DIR")
        os.environ["PLANNER_BASE_DIR"] = str(app_root)
        if shared_dir.name == "shared":
            os.environ["PLANNER_SHARED_DIR"] = str(shared_dir)
        try:
            from web.backend.app_factory import create_app

            app = create_app(app_root)
            details["routes"] = len(app.routes)
            context = app.state.context
            details["resolved_teachers_json"] = str(context.paths.teachers_json)
            if installed_layout and context.paths.teachers_json != (shared_dir / "teachers.json").resolve():
                issue(
                    "storage_unavailable",
                    "Приложение не использует shared/teachers.json как изменяемое хранилище.",
                    "Выполните установщик с --repair и не запускайте код непосредственно из каталога releases.",
                )
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
            if previous_shared is None:
                os.environ.pop("PLANNER_SHARED_DIR", None)
            else:
                os.environ["PLANNER_SHARED_DIR"] = previous_shared

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
                f"Python {details['python_version']}, модулей {len(REQUIRED_MODULES)}, "
                f"файлов интерфейса {len(frontend_checked)}{suffix}."
            )
        for warning in warnings:
            print(f"Предупреждение: {warning}", file=sys.stderr)
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
