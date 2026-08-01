"""Verify an extracted offline bundle against its integrity manifest."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any


class VerificationError(RuntimeError):
    pass


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
    return {
        "ok": not errors,
        "checked": checked,
        "expected": len(manifest["files"]),
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
        print(f"Пакет проверен: {result['checked']} файлов.")
    else:
        print("Пакет повреждён:", file=sys.stderr)
        for error in result["errors"]:
            print(f"- {error}", file=sys.stderr)
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
