#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
OUTPUT="dist"
ARGS=("$@")

for ((index=0; index<${#ARGS[@]}; index++)); do
    if [[ "${ARGS[$index]}" == "--output" && $((index+1)) -lt ${#ARGS[@]} ]]; then
        OUTPUT="${ARGS[$((index+1))]}"
    elif [[ "${ARGS[$index]}" == --output=* ]]; then
        OUTPUT="${ARGS[$index]#--output=}"
    fi
done

"$PYTHON_BIN" "$ROOT/offline/build_bundle.py" --root "$ROOT" "$@"
mkdir -p "$OUTPUT"
cp "$ROOT/offline/install_from_archive.sh" "$OUTPUT/install-planner-solving.sh"
chmod 0755 "$OUTPUT/install-planner-solving.sh"
printf 'Создан установщик: %s\n' "$OUTPUT/install-planner-solving.sh"
