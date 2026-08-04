"""Offline-safe installation health checks with concrete recovery actions."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys
from typing import Any

from src.data_migrations import (
    CURRENT_SCHEMA_VERSION,
    MigrationError,
    detect_schema_version,
    validate_document,
)
from src.platform_store import PLATFORM_SCHEMA_VERSION
from web.backend.recovery_catalog import compact_recommendations

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
    issue_codes: list[str] = []
    issues: list[dict[str, str]] = []

    def issue(code: str, message: str, resolution: str) -> None:
        errors.append(message)
        issue_codes.append(code)
        issues.append({"code": code, "message": message, "resolution": resolution})

    details: dict[str, Any] = {
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
            issue(
                "internal_error",
                f"Отсутствует обязательный файл: {path}",
                "Повторно установите активный выпуск штатным установщиком с --repair.",
            )

    previous_base = os.environ.get("PLANNER_BASE_DIR")
    os.environ["PLANNER_BASE_DIR"] = str(root)
    try:
        from web.backend.main import app  # noqa: F401
    except Exception as exc:  # pragma: no cover
        issue(
            "internal_error",
            f"Приложение не импортируется: {exc}",
            "Проверьте рабочий venv командой planner-solving-python и выполните установщик с --repair.",
        )
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
            issue(
                "workspace_error",
                f"Совместимое JSON-зеркало повреждено: {exc}",
                "Не удаляйте SQLite. Запустите штатную миграцию или восстановите зеркало из базы/резервной копии.",
            )
    else:
        issue(
            "workspace_error",
            f"Не создано совместимое JSON-зеркало: {workspace_path}",
            "Запустите tools.migrate либо установщик с --repair для повторного формирования зеркала.",
        )

    database_path = data_dir / "planner-solving.sqlite3"
    details["database"] = str(database_path)
    if not database_path.exists():
        issue(
            "workspace_error",
            f"Не создана база SQLite: {database_path}",
            "Восстановите shared/data из резервной копии или выполните установщик с --repair.",
        )
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
                issue(
                    "workspace_error",
                    f"SQLite quick_check: {quick_check}",
                    "Остановите службу, сохраните копию базы и восстановите последний исправный снимок.",
                )
            if storage_version != PLATFORM_SCHEMA_VERSION:
                issue(
                    "workspace_error",
                    f"Версия SQLite {storage_version}, поддерживается {PLATFORM_SCHEMA_VERSION}.",
                    "Запустите штатную миграцию; если база новее приложения — обновите Planner Solving.",
                )
            missing_tables = REQUIRED_PLATFORM_TABLES - tables
            if missing_tables:
                issue(
                    "workspace_error",
                    "Отсутствуют таблицы операционной платформы: " + ", ".join(sorted(missing_tables)),
                    "Выполните tools.migrate на резервной копии и повторите healthcheck.",
                )
            if workspace_count < 1:
                issue(
                    "workspace_error",
                    "База SQLite не содержит рабочих пространств.",
                    "Восстановите JSON-зеркало/резервную копию либо создайте основное пространство через штатную инициализацию.",
                )
            if default_count != 1:
                issue(
                    "workspace_error",
                    "В SQLite не задано основное рабочее пространство.",
                    "Откройте Центр операций → Данные и назначьте одно пространство основным.",
                )
        except (OSError, sqlite3.Error) as exc:
            issue(
                "workspace_error",
                f"База SQLite недоступна или повреждена: {exc}",
                "Не удаляйте базу. Проверьте права, диск и резервную копию, затем выполните planner-solving-doctor.",
            )

    details["ok"] = not errors
    details["errors"] = errors
    details["issues"] = issues
    details["recommendations"] = compact_recommendations(issue_codes)
    details["admin_commands"] = [
        "sudo planner-solving-doctor --output /tmp/planner-solving-doctor.txt",
        "sudo ./install-planner-solving.sh --python bundled --strict-python --repair",
    ]
    if args.as_json:
        print(json.dumps(details, ensure_ascii=False, indent=2))
    elif errors:
        print("Проверка не пройдена:", file=sys.stderr)
        for item in issues:
            print(f"- [{item['code']}] {item['message']}", file=sys.stderr)
            print(f"  Решение: {item['resolution']}", file=sys.stderr)
        print("\nШтатные инструменты:", file=sys.stderr)
        for command in details["admin_commands"]:
            print(f"- {command}", file=sys.stderr)
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
