#!/usr/bin/env bash
set -Eeuo pipefail

QUIET=0
ROOT=""
while (($#)); do
    case "$1" in
        --quiet|-q) QUIET=1; shift ;;
        --help|-h)
            echo "verify_bundle.sh [--quiet] [BUNDLE_ROOT]"
            exit 0
            ;;
        *)
            [[ -z "$ROOT" ]] || { echo "Лишний параметр: $1" >&2; exit 2; }
            ROOT="$1"
            shift
            ;;
    esac
done
ROOT="${ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
ROOT="$(cd "$ROOT" && pwd -P)"
SUMS="$ROOT/SHA256SUMS"
[[ -f "$SUMS" ]] || { echo "SHA256SUMS не найден: $SUMS" >&2; exit 2; }

hash_one() {
    local path="$1"
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$path" | awk '{print $1}'
    elif command -v busybox >/dev/null 2>&1 && busybox sha256sum "$path" >/dev/null 2>&1; then
        busybox sha256sum "$path" | awk '{print $1}'
    elif command -v openssl >/dev/null 2>&1; then
        openssl dgst -sha256 "$path" | awk '{print $NF}'
    elif command -v python3 >/dev/null 2>&1; then
        python3 - "$path" <<'PY'
import hashlib, sys
h = hashlib.sha256()
with open(sys.argv[1], 'rb') as stream:
    for chunk in iter(lambda: stream.read(1024 * 1024), b''):
        h.update(chunk)
print(h.hexdigest())
PY
    else
        echo "Не найден инструмент для SHA-256: нужны sha256sum, busybox, openssl или python3." >&2
        return 2
    fi
}

status=0
checked=0
while IFS= read -r line || [[ -n "$line" ]]; do
    [[ -n "${line//[[:space:]]/}" ]] || continue
    expected="${line%%[[:space:]]*}"
    relative="${line#*  }"
    [[ "$relative" != "$line" ]] || relative="${line#*[[:space:]]}"
    relative="${relative#\*}"
    relative="${relative# }"
    if [[ -z "$relative" || "$relative" == /* || "$relative" == ../* || "$relative" == */../* ]]; then
        echo "Недопустимый путь в SHA256SUMS: $relative" >&2
        status=1
        continue
    fi
    path="$ROOT/$relative"
    if [[ ! -f "$path" ]]; then
        echo "$relative: ОТСУТСТВУЕТ" >&2
        status=1
        continue
    fi
    actual="$(hash_one "$path")" || { status=1; continue; }
    if [[ "$actual" == "$expected" ]]; then
        ((checked += 1))
        [[ $QUIET -eq 1 ]] || echo "$relative: OK"
    else
        echo "$relative: КОНТРОЛЬНАЯ СУММА НЕ СОВПАДАЕТ" >&2
        status=1
    fi
done < "$SUMS"

if [[ $status -eq 0 ]]; then
    echo "Пакет проверен: $checked файлов."
else
    echo "Пакет повреждён или неполон." >&2
fi
exit "$status"
