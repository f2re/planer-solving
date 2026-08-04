"""Safe, operator-facing diagnostics for recoverable runtime failures."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
from typing import Any, Dict

from src.platform_store import PLATFORM_SCHEMA_VERSION
from web.backend.app_context import ApplicationContext
from web.backend.recovery_catalog import compact_recommendations


MIN_FREE_CRITICAL = 100 * 1024 * 1024
MIN_FREE_WARNING = 1024 * 1024 * 1024


def _check(
    code: str,
    title: str,
    ok: bool,
    message: str,
    *,
    severity: str = "critical",
    tool: str = "",
) -> Dict[str, Any]:
    return {
        "code": code,
        "title": title,
        "ok": bool(ok),
        "severity": "ok" if ok else severity,
        "message": message,
        "tool": tool,
    }


def _directory_check(name: str, path: Path) -> Dict[str, Any]:
    try:
        path.mkdir(parents=True, exist_ok=True)
        usage = shutil.disk_usage(path)
        with tempfile.NamedTemporaryFile(prefix=".planner-recovery-", dir=path, delete=True):
            pass
        if usage.free < MIN_FREE_CRITICAL:
            return _check(
                "storage_unavailable",
                name,
                False,
                f"Свободно только {usage.free // (1024 * 1024)} МБ: запись результата ненадёжна.",
                tool="Освободить место и повторить операцию.",
            )
        if usage.free < MIN_FREE_WARNING:
            return _check(
                "storage_low_space",
                name,
                False,
                f"Свободно {usage.free // (1024 * 1024)} МБ. Работа возможна, но требуется очистка.",
                severity="warning",
                tool="Удалить старые временные файлы или расширить раздел.",
            )
        return _check(
            f"{name.casefold().replace(' ', '_')}_writable",
            name,
            True,
            f"Каталог доступен для записи; свободно {usage.free // (1024 * 1024)} МБ.",
        )
    except OSError as exc:
        return _check(
            "storage_unavailable",
            name,
            False,
            f"Каталог недоступен для записи: {exc}",
            tool="Проверить владельца, права и доступность файловой системы.",
        )


def _database_check(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return _check(
            "workspace_error",
            "База данных",
            False,
            "Файл SQLite отсутствует.",
            tool="Запустить штатный установщик с --repair или восстановить shared/data из резервной копии.",
        )
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=3)
        try:
            quick_check = str(connection.execute("PRAGMA quick_check").fetchone()[0])
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        finally:
            connection.close()
    except (OSError, sqlite3.Error) as exc:
        return _check(
            "workspace_error",
            "База данных",
            False,
            f"SQLite не открывается: {exc}",
            tool="Не удалять файл; снять резервную копию и выполнить planner-solving-doctor.",
        )
    if quick_check != "ok":
        return _check(
            "workspace_error",
            "База данных",
            False,
            f"SQLite quick_check: {quick_check}",
            tool="Остановить службу, сохранить копию базы и восстановить последний исправный снимок.",
        )
    if version > PLATFORM_SCHEMA_VERSION:
        return _check(
            "workspace_error",
            "Версия базы данных",
            False,
            f"База версии {version}, приложение поддерживает {PLATFORM_SCHEMA_VERSION}.",
            tool="Установить более новую версию Planner Solving.",
        )
    return _check(
        "database_ok",
        "База данных",
        True,
        f"SQLite исправна, версия схемы {version}/{PLATFORM_SCHEMA_VERSION}.",
    )


def build_recovery_status(context: ApplicationContext) -> Dict[str, Any]:
    checks = [
        _directory_check("Данные", context.paths.data_dir),
        _directory_check("Исходники", context.paths.input_dir),
        _directory_check("Результаты", context.paths.output_dir),
        _directory_check("Временные сеансы", context.paths.session_root),
        _database_check(context.paths.workspace_database),
    ]
    template_exists = context.paths.weekly_template.is_file()
    checks.append(_check(
        "weekly_template_ok" if template_exists else "weekly_template_missing",
        "Шаблон недельного расписания",
        template_exists,
        (
            "Шаблон найден."
            if template_exists
            else "Файл obrazec/Недельное.xlsx отсутствует; общее расписание создаётся, недельное — нет."
        ),
        severity="warning",
        tool="Добавить совместимый шаблон Недельное.xlsx и повторить формирование.",
    ))

    failed = [item for item in checks if not item["ok"]]
    critical = [item for item in failed if item["severity"] == "critical"]
    codes = [str(item["code"]) for item in failed]
    return {
        "status": "critical" if critical else "warning" if failed else "ok",
        "app_version": context.application_version(),
        "checks": checks,
        "critical_count": len(critical),
        "warning_count": len(failed) - len(critical),
        "active_session_count": sum(
            1 for item in context.paths.session_root.iterdir() if item.is_dir()
        ) if context.paths.session_root.is_dir() else 0,
        "recommended_actions": compact_recommendations(codes),
        "admin_commands": [
            "sudo planner-solving-doctor --output /tmp/planner-solving-doctor.txt",
            "sudo systemctl status planner-solving --no-pager -l",
            "sudo journalctl -u planner-solving -n 160 --no-pager",
        ],
        "safe_to_retry": not critical,
        "environment": {
            "pid": os.getpid(),
            "base_dir": str(context.paths.base_dir),
        },
    }
