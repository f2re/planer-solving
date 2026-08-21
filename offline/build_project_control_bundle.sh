#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
OUTPUT="dist"
ARGS=("$@")
for ((i=0; i<${#ARGS[@]}; i++)); do
  case "${ARGS[$i]}" in
    --output)
      ((i + 1 < ${#ARGS[@]})) || { echo "--output требует значение" >&2; exit 2; }
      OUTPUT="${ARGS[$((i + 1))]}" ;;
    --python)
      ((i + 1 < ${#ARGS[@]})) || { echo "--python требует значение" >&2; exit 2; }
      PYTHON_BIN="${ARGS[$((i + 1))]}" ;;
    --output=*) OUTPUT="${ARGS[$i]#--output=}" ;;
    --python=*) PYTHON_BIN="${ARGS[$i]#--python=}" ;;
  esac
done
command -v "$PYTHON_BIN" >/dev/null 2>&1 || [[ -x "$PYTHON_BIN" ]] || { echo "Не найден Python: $PYTHON_BIN" >&2; exit 2; }
OUTPUT="$($PYTHON_BIN -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "$OUTPUT")"
VERSION="$(tr -d '[:space:]' < "$ROOT/VERSION")"
"$ROOT/offline/build_offline_bundle.sh" "$@"
ARCHIVE="$(find "$OUTPUT" -maxdepth 1 -type f -name "planner-solving-offline-${VERSION}-*.tar.gz" -printf '%T@\t%p\n' | LC_ALL=C sort -nr | head -n 1 | cut -f2-)"
[[ -n "$ARCHIVE" && -f "$ARCHIVE" && -f "$ARCHIVE.sha256" ]] || { echo "Не найден native archive версии $VERSION в $OUTPUT" >&2; exit 3; }
GIT_COMMIT="unknown"
if command -v git >/dev/null 2>&1 && git -C "$ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then GIT_COMMIT="$(git -C "$ROOT" rev-parse HEAD)"; fi
PACKAGE_ARGS=(
  --archive "$ARCHIVE"
  --output "$OUTPUT"
  --project-id planer-solving
  --display-name "Борис по парам"
  --adapter planer-solving-v1
  --version "$VERSION"
  --source-commit "$GIT_COMMIT"
  --native-format planner-solving-offline-v3
)
[[ -z "${F2RE_RELEASE_SIGNING_KEY:-}" ]] || PACKAGE_ARGS+=(--signing-key "$F2RE_RELEASE_SIGNING_KEY")
"$PYTHON_BIN" "$ROOT/offline/project_control_package.py" "${PACKAGE_ARGS[@]}"
