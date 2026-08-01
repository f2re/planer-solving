import json
from pathlib import Path

import pytest

from src.data_migrations import (
    CURRENT_SCHEMA_VERSION,
    MigrationError,
    detect_schema_version,
    migrate_document,
    migrate_file,
)


def test_legacy_teacher_list_migrates_to_workspace() -> None:
    migrated, applied = migrate_document([
        {"short_name": "Иванов И.И.", "full_name": "Иванов Иван Иванович"}
    ])
    assert migrated["version"] == CURRENT_SCHEMA_VERSION
    assert applied == ["0->1"]
    assert migrated["workspaces"][0]["teachers"][0]["short_name"] == "Иванов И.И."
    assert migrated["default_workspace_id"] == migrated["workspaces"][0]["id"]


def test_future_schema_is_rejected() -> None:
    with pytest.raises(MigrationError, match="новее поддерживаемой"):
        migrate_document({"version": CURRENT_SCHEMA_VERSION + 1, "workspaces": []})


def test_migrate_file_creates_backup_and_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "data" / "workspaces.json"
    path.parent.mkdir()
    path.write_text(json.dumps([
        {"short_name": "Петров П.П.", "full_name": "Петров Петр Петрович"}
    ], ensure_ascii=False), encoding="utf-8")
    backup_dir = tmp_path / "backups"

    report = migrate_file(path, backup_dir=backup_dir)
    assert report["changed"] is True
    assert Path(report["backup"]).exists()
    assert detect_schema_version(json.loads(path.read_text(encoding="utf-8"))) == CURRENT_SCHEMA_VERSION

    second = migrate_file(path, backup_dir=backup_dir)
    assert second["changed"] is False
    assert second["backup"] is None


def test_dry_run_does_not_write(tmp_path: Path) -> None:
    path = tmp_path / "workspaces.json"
    original = '[{"short_name":"Сидоров"}]'
    path.write_text(original, encoding="utf-8")
    report = migrate_file(path, dry_run=True)
    assert report["changed"] is True
    assert path.read_text(encoding="utf-8") == original
