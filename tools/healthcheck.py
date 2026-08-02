"""Offline-safe installation and data health checks."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys

from src.data_migrations import (
    CURRENT_SCHEMA_VERSION,
    MigrationError,
    detect_schema_version,
    validate_document,
)
from src.sqlite_workspace_store import SQLITE_SCHEMA_VERSION


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
        "document_schema_version": None,
        "storage_schema_version": None,
        "supported_document_schema_version": CURRENT_SCHEMA_VERSION,
        "supported_storage_schema_version": SQLITE_SCHEMA_VERSION,
        "storage": "sqlite",
    }

    required = [
        root / "VERSION",
        root / "requirements-runtime.txt",
        root / "web" / "backend" / "main.py",
        root / "web" / "backend" / "app_factory.py",
        root / "web" / "backend" / "app_context.py",
        root / "web" / "frontend" / "index.html",
        root / "src" / "sqlite_workspace_store.py",
    ]
    for path in required:
        if not path.exists():
            errors.append(f"Отсутствует обязательный файл: {path}")

    previous_base = os.environ.get("PLANNER_BASE_DIR")
    os.environ["PLANNER_BASE_DIR"] = str(root)
    try:
        from web.backend.main import app  # noqa: F401
    except Exception as exc:  # pragma: no cover
        errors.append(f"Приложение не импортируется: {exc}")
    finally:
        if previous_base is None:
            os.environ.pop("PLANNER_BASE_DIR", None)
        else:
            os.environ["PLANNER_BASE_DIR"] = previous_base

    workspace_path = data_dir / "workspaces.json"
    if workspace_path.exists():
        try:
            payload = json.loads(workspace_path.read_text(encoding="utf-8"))
            details["document_schema_version"] = detect_schema_version(payload)
            validate_document(payload)
        except (OSError, json.JSONDecodeError, MigrationError) as exc:
            errors.append(f"Совместимое JSON-зеркало повреждено: {exc}")
    else:
        errors.append(f"Не создано совместимое JSON-зеркало: {workspace_path}")

    database_path = data_dir / "planner-solving.sqlite3"
    details["database"] = str(database_path)
    if not database_path.exists():
        errors.append(f"Не создана база SQLite: {database_path}")
    else:
        try:
            connection = sqlite3.connect(database_path)
            try:
                quick_check = str(connection.execute("PRAGMA quick_check").fetchone()[0])
                storage_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
                workspace_count = int(connection.execute("SELECT COUNT(*) FROM workspaces").fetchone()[0])
                default_count = int(connection.execute(
                    "SELECT COUNT(*) FROM metadata WHERE key = 'default_workspace_id'"
                ).fetchone()[0])
            finally:
                connection.close()
            details["storage_schema_version"] = storage_version
            details["workspace_count"] = workspace_count
            details["sqlite_quick_check"] = quick_check
            if quick_check != "ok":
                errors.append(f"SQLite quick_check: {quick_check}")
            if storage_version != SQLITE_SCHEMA_VERSION:
                errors.append(
                    f"Версия SQLite {storage_version}, поддерживается {SQLITE_SCHEMA_VERSION}."
                )
            if workspace_count < 1:
                errors.append("База SQLite не содержит рабочих пространств.")
            if default_count != 1:
                errors.append("В SQLite не задано основное рабочее пространство.")
        except (OSError, sqlite3.Error) as exc:
            errors.append(f"База SQLite недоступна или повреждена: {exc}")

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
            "Проверка пройдена. "
            f"Документ: {details['document_schema_version']}/{CURRENT_SCHEMA_VERSION}; "
            f"SQLite: {details['storage_schema_version']}/{SQLITE_SCHEMA_VERSION}."
        )
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
