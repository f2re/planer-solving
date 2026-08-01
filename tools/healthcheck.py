"""Offline-safe installation and data health checks."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from src.data_migrations import CURRENT_SCHEMA_VERSION, MigrationError, detect_schema_version, validate_document


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Проверка установки Planner Solving")
    parser.add_argument("--app-root", type=Path, default=Path.cwd())
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)

    root = args.app_root.resolve()
    data_dir = (args.data_dir or root / "data").resolve()
    errors: list[str] = []
    details: dict[str, object] = {
        "app_root": str(root),
        "data_dir": str(data_dir),
        "schema_version": None,
        "supported_schema_version": CURRENT_SCHEMA_VERSION,
    }

    required = [
        root / "VERSION",
        root / "requirements-runtime.txt",
        root / "web" / "backend" / "main.py",
        root / "web" / "frontend" / "index.html",
    ]
    for path in required:
        if not path.exists():
            errors.append(f"Отсутствует обязательный файл: {path}")

    try:
        from web.backend.main import app  # noqa: F401
    except Exception as exc:  # pragma: no cover
        errors.append(f"Приложение не импортируется: {exc}")

    workspace_path = data_dir / "workspaces.json"
    if workspace_path.exists():
        try:
            payload = json.loads(workspace_path.read_text(encoding="utf-8"))
            details["schema_version"] = detect_schema_version(payload)
            validate_document(payload)
        except (OSError, json.JSONDecodeError, MigrationError) as exc:
            errors.append(f"Файл пространств повреждён: {exc}")
    else:
        errors.append(f"Не создан файл данных: {workspace_path}")

    details["ok"] = not errors
    details["errors"] = errors
    if args.as_json:
        print(json.dumps(details, ensure_ascii=False, indent=2))
    elif errors:
        print("Проверка не пройдена:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
    else:
        print(
            f"Проверка пройдена. Версия схемы данных: "
            f"{details['schema_version']}/{CURRENT_SCHEMA_VERSION}."
        )
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
