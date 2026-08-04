"""Verify an extracted offline bundle against its integrity manifest."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any


class VerificationError(RuntimeError):
    pass


REQUIRED_FRONTEND_FILES = (
    "index.html",
    "assets/app.css",
    "assets/app.js",
    "assets/vue.global.prod.js",
    "assets/axios.min.js",
    "assets/planner-app.js",
    "assets/unified-operations.js",
)
ABSOLUTE_ASSET_RE = re.compile(r"['\"](/assets/[A-Za-z0-9_./-]+\.(?:js|css))['\"]")
HTML_ASSET_RE = re.compile(r"(?:src|href)=['\"]/?assets/([^'\"]+)['\"]")
STATIC_IMPORT_RE = re.compile(r"\bfrom\s+['\"](\.[^'\"]+\.js)['\"]")
SIDE_EFFECT_IMPORT_RE = re.compile(r"\bimport\s+['\"](\.[^'\"]+\.js)['\"]")
DYNAMIC_IMPORT_RE = re.compile(r"\bimport\s*\(\s*['\"](\.[^'\"]+\.js)['\"]\s*\)")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VerificationError(f"Не удалось прочитать manifest.json: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("format") != "planner-solving-offline":
        raise VerificationError("Файл manifest.json не относится к Planner Solving.")
    if not isinstance(payload.get("files"), dict) or not payload["files"]:
        raise VerificationError("В manifest.json отсутствует перечень файлов.")
    return payload


def safe_path(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise VerificationError(f"Недопустимый путь в manifest.json: {relative}") from exc
    return candidate


def verify_frontend(root: Path, manifest: dict[str, Any]) -> tuple[list[str], int]:
    """Require the browser entrypoint and all local module dependencies."""

    app_root = (root / "app").resolve()
    frontend = app_root / "web" / "frontend"
    errors: list[str] = []
    queue: list[Path] = []
    visited: set[Path] = set()
    checked = 0

    def add(path: Path) -> None:
        resolved = path.resolve(strict=False)
        try:
            resolved.relative_to(frontend)
        except ValueError:
            errors.append(f"Ссылка интерфейса выходит за каталог frontend: {path}")
            return
        if resolved not in queue and resolved not in visited:
            queue.append(resolved)

    for relative in REQUIRED_FRONTEND_FILES:
        add(frontend / relative)

    index = frontend / "index.html"
    if index.is_file():
        try:
            source = index.read_text(encoding="utf-8")
            for relative in HTML_ASSET_RE.findall(source):
                add(frontend / "assets" / relative)
        except OSError as exc:
            errors.append(f"Не удалось прочитать app/web/frontend/index.html: {exc}")

    app_script = frontend / "assets" / "app.js"
    if app_script.is_file():
        try:
            source = app_script.read_text(encoding="utf-8")
            for absolute in ABSOLUTE_ASSET_RE.findall(source):
                add(frontend / absolute.removeprefix("/"))
        except OSError as exc:
            errors.append(f"Не удалось прочитать app/web/frontend/assets/app.js: {exc}")

    while queue:
        path = queue.pop(0)
        if path in visited:
            continue
        visited.add(path)
        try:
            relative_frontend = path.relative_to(frontend).as_posix()
            relative_bundle = path.relative_to(root).as_posix()
        except ValueError:
            errors.append(f"Недопустимый путь интерфейса: {path}")
            continue

        if not path.is_file():
            errors.append(f"Отсутствует обязательный файл интерфейса: {relative_frontend}")
            continue
        if relative_bundle not in manifest["files"]:
            errors.append(f"Файл интерфейса отсутствует в manifest: {relative_bundle}")
            continue
        try:
            if path.stat().st_size <= 0:
                errors.append(f"Пустой файл интерфейса: {relative_frontend}")
                continue
            checked += 1
            if path.suffix != ".js":
                continue
            source = path.read_text(encoding="utf-8")
        except OSError as exc:
            errors.append(f"Файл интерфейса недоступен: {relative_frontend}: {exc}")
            continue

        for absolute in ABSOLUTE_ASSET_RE.findall(source):
            add(frontend / absolute.removeprefix("/"))
        imports = (
            STATIC_IMPORT_RE.findall(source)
            + SIDE_EFFECT_IMPORT_RE.findall(source)
            + DYNAMIC_IMPORT_RE.findall(source)
        )
        for imported in imports:
            add(path.parent / imported)

    return errors, checked


def verify_bundle(root: Path, manifest_path: Path | None = None) -> dict[str, Any]:
    root = root.resolve()
    manifest_path = (manifest_path or root / "manifest.json").resolve()
    manifest = load_manifest(manifest_path)
    errors: list[str] = []
    checked = 0
    for relative, metadata in sorted(manifest["files"].items()):
        if not isinstance(metadata, dict):
            errors.append(f"Некорректная запись manifest для {relative}")
            continue
        path = safe_path(root, relative)
        if not path.is_file():
            errors.append(f"Отсутствует файл: {relative}")
            continue
        expected_size = metadata.get("size")
        if expected_size is not None and path.stat().st_size != expected_size:
            errors.append(f"Размер файла изменён: {relative}")
            continue
        expected_hash = metadata.get("sha256")
        if not isinstance(expected_hash, str) or sha256(path) != expected_hash:
            errors.append(f"Контрольная сумма не совпадает: {relative}")
            continue
        checked += 1

    frontend_checked = 0
    has_frontend = any(
        relative.startswith("app/web/frontend/")
        for relative in manifest["files"]
    )
    if has_frontend:
        frontend_errors, frontend_checked = verify_frontend(root, manifest)
        errors.extend(frontend_errors)
    return {
        "ok": not errors,
        "checked": checked,
        "expected": len(manifest["files"]),
        "frontend_checked": frontend_checked,
        "errors": errors,
        "manifest": manifest,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Проверка офлайн-пакета Planner Solving")
    parser.add_argument("root", nargs="?", type=Path, default=Path.cwd())
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)
    try:
        result = verify_bundle(args.root, args.manifest)
    except VerificationError as exc:
        print(f"Ошибка проверки: {exc}", file=sys.stderr)
        return 2
    if args.as_json:
        print(json.dumps({k: v for k, v in result.items() if k != "manifest"}, ensure_ascii=False, indent=2))
    elif result["ok"]:
        print(
            f"Пакет проверен: {result['checked']} файлов; "
            f"цепочка интерфейса: {result['frontend_checked']} файлов."
        )
    else:
        print("Пакет повреждён:", file=sys.stderr)
        for error in result["errors"]:
            print(f"- {error}", file=sys.stderr)
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
