"""Command-line entrypoint for safe persistent-data migrations."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from src.data_migrations import CURRENT_SCHEMA_VERSION, MigrationError, migrate_file


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Миграция данных Planner Solving")
    result.add_argument("--data-dir", type=Path, default=Path("data"))
    result.add_argument("--legacy-teachers", type=Path, default=Path("teachers.json"))
    result.add_argument("--backup-dir", type=Path, default=Path("backups/migrations"))
    result.add_argument("--dry-run", action="store_true")
    result.add_argument("--check", action="store_true", help="Проверить без записи")
    result.add_argument("--json", action="store_true", dest="as_json")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    path = args.data_dir / "workspaces.json"
    try:
        report = migrate_file(
            path,
            legacy_teachers_path=args.legacy_teachers,
            backup_dir=args.backup_dir,
            dry_run=args.dry_run or args.check,
            target_version=CURRENT_SCHEMA_VERSION,
        )
    except MigrationError as exc:
        print(f"Ошибка миграции: {exc}", file=sys.stderr)
        return 2
    if args.as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        action = "требуются изменения" if report["changed"] else "изменения не требуются"
        print(
            f"Схема данных: {report['from_version']} -> {report['to_version']}; "
            f"{action}; пространств: {report['workspace_count']}."
        )
        if report["applied"]:
            print("Применены миграции: " + ", ".join(report["applied"]))
        if report["backup"]:
            print("Резервная копия: " + report["backup"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
