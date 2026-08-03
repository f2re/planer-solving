"""Offline-safe installation and operations-platform health checks."""
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
from src.platform_store import PLATFORM_SCHEMA_VERSION

REQUIRED_PLATFORM_TABLES = {
    "workspaces",
    "teachers",
    "templates",
    "users",
    "auth_sessions",
    "audit_log",
    "import_jobs",
    "template_profiles",
    "template_revisions",
    "processing_runs",
    "processing_files",
    "processing_artifacts",
}


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
        "supported_storage_schema_version": PLATFORM_SCHEMA_VERSION,
        "storage": "sqlite-platform",
    }

    required = [
        root / "VERSION",
        root / "requirements-runtime.txt",
        root / "web" / "backend" / "main.py",
        root / "web" / "backend" / "app_factory.py",
        root / "web" / "backend" / "app_context.py",
        root / "web" / "backend" / "auth.py",
        root / "web" / "backend" / "platform_api.py",
        root / "web" / "frontend" / "index.html",
        root / "src" / "platform_store.py",
        root / "src" / "import_wizard.py",
        root / "src" / "template_learning.py",
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
                tables = {
                    str(row[0])
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }
                workspace_count = int(
                    connection.execute("SELECT COUNT(*) FROM workspaces").fetchone()[0]
                )
                default_count = int(connection.execute(
                    "SELECT COUNT(*) FROM metadata WHERE key = 'default_workspace_id'"
                ).fetchone()[0])
                user_count = int(connection.execute("SELECT COUNT(*) FROM users").fetchone()[0])
                open_runs = int(connection.execute(
                    "SELECT COUNT(*) FROM processing_runs WHERE status = 'running'"
                ).fetchone()[0])
            finally:
                connection.close()
            details["storage_schema_version"] = storage_version
            details["workspace_count"] = workspace_count
            details["user_count"] = user_count
            details["bootstrap_required"] = user_count == 0
            details["running_processing_count"] = open_runs
            details["sqlite_quick_check"] = quick_check
            details["platform_tables"] = sorted(REQUIRED_PLATFORM_TABLES & tables)
            if quick_check != "ok":
                errors.append(f"SQLite quick_check: {quick_check}")
            if storage_version != PLATFORM_SCHEMA_VERSION:
                errors.append(
                    f"Версия SQLite {storage_version}, поддерживается {PLATFORM_SCHEMA_VERSION}."
                )
            missing_tables = REQUIRED_PLATFORM_TABLES - tables
            if missing_tables:
                errors.append(
                    "Отсутствуют таблицы операционной платформы: "
                    + ", ".join(sorted(missing_tables))
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
            f"SQLite: {details['storage_schema_version']}/{PLATFORM_SCHEMA_VERSION}; "
            f"пользователей: {details['user_count']}."
        )
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
