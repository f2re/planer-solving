"""Explicit application context: paths, storage and analysis-session lifecycle."""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import sqlite3
import time
from typing import Any, Dict, Optional, Protocol
import uuid

from src.data_migrations import CURRENT_SCHEMA_VERSION, MigrationError, detect_schema_version
from src.platform_store import PLATFORM_SCHEMA_VERSION
from src.transactional_platform_store import TransactionalPlatformStore
from src.workspace_domain import WorkspaceError
from web.backend.errors import SessionCorrupted, SessionNotFound, UploadedFileNotFound


class WorkspaceRepository(Protocol):
    def load(self) -> Dict[str, Any]: ...
    def schema_version(self) -> int: ...
    def list_workspaces(self) -> list[Dict[str, Any]]: ...
    def default_workspace_id(self) -> str: ...
    def get_workspace(self, workspace_id: Optional[str] = None) -> Dict[str, Any]: ...


@dataclass(frozen=True)
class ApplicationPaths:
    base_dir: Path
    data_dir: Path
    input_dir: Path
    output_dir: Path
    session_root: Path
    frontend_dir: Path
    teachers_json: Path
    workspaces_json: Path
    workspace_database: Path
    version_file: Path
    weekly_template: Path

    @classmethod
    def from_base_dir(cls, base_dir: Path) -> "ApplicationPaths":
        base = Path(base_dir).resolve()
        data = base / "data"
        input_dir = base / "input"
        return cls(
            base_dir=base,
            data_dir=data,
            input_dir=input_dir,
            output_dir=base / "output",
            session_root=input_dir / "analysis_sessions",
            frontend_dir=base / "web" / "frontend",
            teachers_json=base / "teachers.json",
            workspaces_json=data / "workspaces.json",
            workspace_database=data / "planner-solving.sqlite3",
            version_file=base / "VERSION",
            weekly_template=base / "obrazec" / "Недельное.xlsx",
        )


class AnalysisSessionStore:
    def __init__(self, root: Path, max_age_seconds: int = 24 * 60 * 60):
        self.root = Path(root).resolve()
        self.max_age_seconds = int(max_age_seconds)
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def atomic_json_write(path: Path, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)

    def cleanup_old(self) -> None:
        threshold = time.time() - self.max_age_seconds
        for candidate in self.root.iterdir():
            if not candidate.is_dir():
                continue
            try:
                if candidate.stat().st_mtime < threshold:
                    shutil.rmtree(candidate, ignore_errors=True)
            except OSError:
                continue

    def create(self) -> tuple[str, Path]:
        self.cleanup_old()
        session_id = str(uuid.uuid4())
        path = self.root / session_id
        path.mkdir(parents=True, exist_ok=False)
        return session_id, path

    def path(self, session_id: str, *, require_exists: bool = True) -> Path:
        try:
            parsed = uuid.UUID(str(session_id))
        except (ValueError, AttributeError, TypeError) as exc:
            raise SessionNotFound("Сеанс анализа не найден.") from exc
        if str(parsed) != str(session_id).lower():
            raise SessionNotFound("Сеанс анализа не найден.")
        path = (self.root / str(parsed)).resolve()
        if path.parent != self.root:
            raise SessionNotFound("Сеанс анализа не найден.")
        if require_exists and not path.is_dir():
            raise SessionNotFound("Сеанс анализа не найден или истёк.")
        return path

    def manifest_path(self, session_id: str) -> Path:
        return self.path(session_id) / "manifest.json"

    def load_manifest(self, session_id: str) -> Dict[str, Any]:
        path = self.manifest_path(session_id)
        if not path.exists():
            raise SessionNotFound("Сеанс анализа не найден или истёк.")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SessionCorrupted("Файл сеанса повреждён или недоступен.") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("files"), list):
            raise SessionCorrupted("Файл сеанса имеет неверную структуру.")
        return payload

    def save_manifest(self, session_id: str, manifest: Dict[str, Any]) -> None:
        self.atomic_json_write(self.manifest_path(session_id), manifest)

    @staticmethod
    def manifest_file(manifest: Dict[str, Any], file_id: str) -> Dict[str, Any]:
        for item in manifest.get("files", []):
            if isinstance(item, dict) and item.get("file_id") == file_id:
                return item
        raise UploadedFileNotFound("Файл в сеансе не найден.")

    @staticmethod
    def _same_file(left: Path, right: Path) -> bool:
        try:
            return os.path.samestat(left.stat(), right.stat())
        except OSError:
            return False

    def _display_alias(
        self,
        session_dir: Path,
        canonical: Path,
        file_item: Dict[str, Any],
    ) -> Path:
        """Return a safe path whose basename is the user's original filename.

        Files are stored under opaque internal names so sessions cannot collide.
        Parsers and reports, however, must never expose those UUID names. A
        per-file alias keeps the original basename without changing the manifest
        or duplicating large workbooks on normal Linux filesystems.
        """

        display_name = Path(str(file_item.get("filename") or canonical.name)).name
        if not display_name or display_name in {".", ".."} or display_name == canonical.name:
            return canonical
        file_id = Path(str(file_item.get("file_id") or canonical.stem)).name
        if not file_id or file_id in {".", ".."}:
            file_id = canonical.stem or "source"
        alias_dir = session_dir / ".display" / file_id
        alias_dir.mkdir(parents=True, exist_ok=True)
        alias = alias_dir / display_name

        # Remove aliases left by a previous per-file replacement. They are
        # private session artefacts and never referenced from the manifest.
        try:
            for candidate in alias_dir.iterdir():
                if candidate != alias:
                    if candidate.is_dir() and not candidate.is_symlink():
                        shutil.rmtree(candidate, ignore_errors=True)
                    else:
                        candidate.unlink(missing_ok=True)
        except OSError:
            pass

        if alias.is_symlink():
            try:
                if alias.resolve() == canonical:
                    return alias
            except OSError:
                pass
        elif alias.is_file() and self._same_file(alias, canonical):
            return alias

        try:
            alias.unlink(missing_ok=True)
        except OSError:
            return canonical

        # A relative symlink stays valid when the complete installation is
        # moved or restored from an offline backup.
        try:
            relative_target = os.path.relpath(canonical, alias.parent)
            alias.symlink_to(relative_target)
            if alias.resolve() == canonical:
                return alias
        except OSError:
            try:
                alias.unlink(missing_ok=True)
            except OSError:
                return canonical

        # Restricted environments may disallow symlinks. A hard link preserves
        # the original name without copying; stored_path detects a stale inode
        # after atomic replacement and recreates it on the next access.
        try:
            os.link(canonical, alias)
            if self._same_file(alias, canonical):
                return alias
        except OSError:
            try:
                alias.unlink(missing_ok=True)
            except OSError:
                return canonical

        # Last resort for unusual filesystems. This is normally executed only
        # once per source file; metadata lets later calls reuse the copy until
        # the canonical workbook changes.
        metadata = alias_dir / ".source.json"
        try:
            signature = {
                "source": str(canonical),
                "size": canonical.stat().st_size,
                "mtime_ns": canonical.stat().st_mtime_ns,
            }
            if alias.is_file() and metadata.is_file():
                previous = json.loads(metadata.read_text(encoding="utf-8"))
                if previous == signature:
                    return alias
            temporary = alias.with_name(f".{alias.name}.{uuid.uuid4().hex}.tmp")
            shutil.copy2(canonical, temporary)
            os.replace(temporary, alias)
            self.atomic_json_write(metadata, signature)
            return alias
        except (OSError, json.JSONDecodeError):
            try:
                alias.unlink(missing_ok=True)
            except OSError:
                pass
            return canonical

    def stored_path(self, session_id: str, file_item: Dict[str, Any]) -> Path:
        session_dir = self.path(session_id)
        stored_name = str(file_item.get("stored_name") or "")
        canonical = (session_dir / stored_name).resolve()
        if (
            not stored_name
            or canonical == session_dir
            or session_dir not in canonical.parents
            or not canonical.is_file()
        ):
            raise UploadedFileNotFound("Загруженный файл не найден.")
        return self._display_alias(session_dir, canonical, file_item)

    def write_snapshot(self, session_id: str, name: str, payload: Any) -> Path:
        safe_name = Path(name).name
        path = self.path(session_id) / safe_name
        self.atomic_json_write(path, payload)
        return path

    def delete(self, session_id: str) -> None:
        shutil.rmtree(self.path(session_id))


class ApplicationContext:
    """All mutable runtime dependencies owned by one FastAPI application."""

    def __init__(
        self,
        base_dir: Optional[Path] = None,
        workspace_repository: Optional[WorkspaceRepository] = None,
    ) -> None:
        configured = base_dir or Path(
            os.environ.get("PLANNER_BASE_DIR", Path(__file__).resolve().parents[2])
        )
        self.paths = ApplicationPaths.from_base_dir(Path(configured))
        for directory in (
            self.paths.data_dir,
            self.paths.input_dir,
            self.paths.output_dir,
            self.paths.session_root,
        ):
            directory.mkdir(parents=True, exist_ok=True)
        self.sessions = AnalysisSessionStore(self.paths.session_root)
        if workspace_repository is None:
            self._validate_storage_schema()
            self._validate_legacy_schema_before_import()
            workspace_repository = TransactionalPlatformStore(
                self.paths.workspace_database,
                self.paths.workspaces_json,
                self.paths.teachers_json,
            )
        self.workspace_repository = workspace_repository

    def _validate_storage_schema(self) -> None:
        database = self.paths.workspace_database
        if not database.exists() or database.stat().st_size == 0:
            return
        try:
            connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
            try:
                version = int(connection.execute("PRAGMA user_version").fetchone()[0])
                quick_check = str(connection.execute("PRAGMA quick_check").fetchone()[0])
            finally:
                connection.close()
        except (OSError, sqlite3.Error) as exc:
            raise WorkspaceError(f"Не удалось проверить базу SQLite: {exc}") from exc
        if quick_check != "ok":
            raise WorkspaceError(f"База SQLite повреждена: {quick_check}")
        if version > PLATFORM_SCHEMA_VERSION:
            raise WorkspaceError(
                f"База SQLite имеет версию {version}, а приложение поддерживает только "
                f"версию {PLATFORM_SCHEMA_VERSION}. Установите более новую версию приложения."
            )
        # Versions 0..4 are migrated transactionally by TransactionalPlatformStore.

    def _validate_legacy_schema_before_import(self) -> None:
        if self.paths.workspace_database.exists() or not self.paths.workspaces_json.exists():
            return
        try:
            payload = json.loads(self.paths.workspaces_json.read_text(encoding="utf-8"))
            version = detect_schema_version(payload)
        except (OSError, json.JSONDecodeError, MigrationError) as exc:
            raise WorkspaceError(f"Не удалось проверить версию данных: {exc}") from exc
        if version > CURRENT_SCHEMA_VERSION:
            raise WorkspaceError(
                f"Данные имеют версию {version}, а приложение поддерживает только "
                f"версию {CURRENT_SCHEMA_VERSION}. Установите более новую версию приложения."
            )
        if version < CURRENT_SCHEMA_VERSION:
            raise WorkspaceError(
                f"Данные имеют версию {version} и требуют миграции до версии "
                f"{CURRENT_SCHEMA_VERSION}. Запустите tools.migrate или штатный start_web.sh."
            )

    def application_version(self) -> str:
        try:
            return self.paths.version_file.read_text(encoding="utf-8").strip() or "unknown"
        except OSError:
            return "unknown"

    def system_status(self) -> Dict[str, Any]:
        document = self.workspace_repository.load()
        schema_version = self.workspace_repository.schema_version()
        return {
            "status": "ok",
            "app_version": self.application_version(),
            "data_schema_version": int(document.get("version", 0)),
            "storage_schema_version": schema_version,
            "supported_data_schema_version": CURRENT_SCHEMA_VERSION,
            "supported_storage_schema_version": PLATFORM_SCHEMA_VERSION,
            "storage": "sqlite-platform",
            "features": {
                "import_wizard": True,
                "template_revisions": True,
                "processing_history": True,
                "roles": True,
                "audit": True,
                "composite_templates": True,
            },
        }

    @property
    def BASE_DIR(self) -> Path:
        return self.paths.base_dir

    @property
    def TEACHERS_JSON(self) -> Path:
        return self.paths.teachers_json

    @property
    def INPUT_DIR(self) -> Path:
        return self.paths.input_dir

    @property
    def OUTPUT_DIR(self) -> Path:
        return self.paths.output_dir

    @property
    def SESSION_ROOT(self) -> Path:
        return self.paths.session_root

    def _atomic_json_write(self, path: Path, data: Any) -> None:
        self.sessions.atomic_json_write(path, data)

    def _cleanup_old_sessions(self) -> None:
        self.sessions.cleanup_old()

    def _safe_session_dir(self, session_id: str) -> Path:
        return self.sessions.path(session_id)

    def _load_manifest(self, session_id: str) -> Dict[str, Any]:
        return self.sessions.load_manifest(session_id)

    def _manifest_file(self, manifest: Dict[str, Any], file_id: str) -> Dict[str, Any]:
        return self.sessions.manifest_file(manifest, file_id)

    def _stored_path(self, session_id: str, file_item: Dict[str, Any]) -> Path:
        return self.sessions.stored_path(session_id, file_item)
