#!/usr/bin/env python3
"""Wrap an existing native offline archive into an F2RE Project Control ZIP."""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
import zipfile


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_atom(name: str, value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,127}", value):
        raise SystemExit(f"Некорректный {name}: {value!r}")
    return value


def signing_key_id(private_key: Path) -> str:
    result = subprocess.run(
        ["openssl", "pkey", "-in", str(private_key), "-pubout", "-outform", "DER"],
        check=True,
        stdout=subprocess.PIPE,
    )
    return hashlib.sha256(result.stdout).hexdigest()[:32]


def sign_manifest(private_key: Path, manifest_bytes: bytes) -> bytes:
    with tempfile.TemporaryDirectory(prefix="f2re-sign-") as temporary:
        manifest_path = Path(temporary) / "manifest.json"
        signature_path = Path(temporary) / "manifest.sig"
        manifest_path.write_bytes(manifest_bytes)
        subprocess.run(
            [
                "openssl", "pkeyutl", "-sign", "-rawin",
                "-inkey", str(private_key), "-in", str(manifest_path), "-out", str(signature_path),
            ],
            check=True,
        )
        return signature_path.read_bytes()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--display-name", required=True)
    parser.add_argument("--adapter", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--source-commit", default="unknown")
    parser.add_argument("--native-format", required=True)
    parser.add_argument("--signing-key")
    args = parser.parse_args()

    archive = Path(args.archive).resolve()
    if not archive.is_file():
        raise SystemExit(f"Native archive не найден: {archive}")
    project_id = validate_atom("project-id", args.project_id)
    adapter = validate_atom("adapter", args.adapter)
    version = validate_atom("version", args.version)
    source_commit = str(args.source_commit or "unknown").strip()
    if source_commit != "unknown" and not re.fullmatch(r"[0-9a-fA-F]{7,64}", source_commit):
        raise SystemExit(f"Некорректный source commit: {source_commit}")

    output_dir = Path(args.output).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    package_name = f"{project_id}-{version}-project-control.f2re.zip"
    package_path = output_dir / package_name
    checksum_path = output_dir / f"{package_name}.sha256"
    if package_path.exists() or checksum_path.exists():
        for stale in (package_path, checksum_path):
            try:
                stale.unlink()
            except FileNotFoundError:
                pass

    payload_name = f"payload/{archive.name}"
    signing = None
    signing_key = Path(args.signing_key).resolve() if args.signing_key else None
    if signing_key:
        if not signing_key.is_file():
            raise SystemExit(f"Signing key не найден: {signing_key}")
        signing = {"algorithm": "ed25519", "keyId": signing_key_id(signing_key)}

    manifest = {
        "schema": "f2re-managed-service/v1",
        "controllerApi": 1,
        "projectId": project_id,
        "displayName": args.display_name,
        "adapter": adapter,
        "version": version,
        "sourceCommit": source_commit,
        "builtAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "nativeBundleFormat": args.native_format,
        "signing": signing,
        "payload": {
            "path": payload_name,
            "sha256": sha256_file(archive),
            "size": archive.stat().st_size,
        },
    }
    manifest_bytes = (json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    signature = sign_manifest(signing_key, manifest_bytes) if signing_key else None

    with zipfile.ZipFile(package_path, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as package:
        package.writestr("f2re-service.json", manifest_bytes)
        if signature is not None:
            package.writestr("f2re-service.sig", base64.b64encode(signature) + b"\n")
        package.write(archive, payload_name)

    checksum_path.write_text(f"{sha256_file(package_path)}  {package_path.name}\n", encoding="utf-8")
    print(package_path)
    if signing:
        print(f"Подпись: ed25519 keyId={signing['keyId']}")
    else:
        print("ВНИМАНИЕ: package создан без release-подписи.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
