#!/usr/bin/env bash
set -Eeuo pipefail

log() { printf '[planner] %s\n' "$*"; }
warn() { printf '[planner] ПРЕДУПРЕЖДЕНИЕ: %s\n' "$*" >&2; }
die() { printf '[planner] ОШИБКА: %s\n' "$*" >&2; exit 2; }

require_command() {
    if [[ "$1" == */* ]]; then
        [[ -x "$1" ]] || die "Не найдена исполняемая команда: $1"
    else
        command -v "$1" >/dev/null 2>&1 || die "Не найдена команда: $1"
    fi
}

atomic_link() {
    local target="$1" link="$2"
    local temporary="${link}.next.$$"
    rm -f "$temporary"
    ln -s "$target" "$temporary"
    mv -Tf "$temporary" "$link" 2>/dev/null || mv -f "$temporary" "$link"
}

run_as_user() {
    local user="$1"
    shift
    if [[ $EUID -ne 0 || -z "$user" || "$user" == "root" || "$user" == "$(id -un)" ]]; then
        exec_or_run=("$@")
        "${exec_or_run[@]}"
        return
    fi
    if command -v runuser >/dev/null 2>&1; then
        runuser -u "$user" -- "$@"
    elif command -v sudo >/dev/null 2>&1; then
        sudo -u "$user" -- "$@"
    elif command -v su >/dev/null 2>&1; then
        local quoted=""
        printf -v quoted '%q ' "$@"
        su -s /bin/bash "$user" -c "$quoted"
    else
        die "Нельзя выполнить команду от имени $user: отсутствуют runuser, sudo и su."
    fi
}

_python_matches() {
    local candidate="$1" expected_major="${2:-}" expected_minor="${3:-}"
    [[ -x "$candidate" ]] || return 1
    if [[ -n "$expected_major" && -n "$expected_minor" ]]; then
        "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] == (int(sys.argv[1]), int(sys.argv[2])) else 1)' \
            "$expected_major" "$expected_minor" >/dev/null 2>&1
    else
        "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1
    fi
}

resolve_python_bin() {
    local user="${1:-}" expected_major="${2:-}" expected_minor="${3:-}" install_root="${4:-/opt/planner-solving}"
    local candidate="" home="" version_glob=""

    if [[ -n "${PYTHON_BIN:-}" ]]; then
        candidate="$(command -v "$PYTHON_BIN" 2>/dev/null || true)"
        [[ -z "$candidate" && -x "$PYTHON_BIN" ]] && candidate="$PYTHON_BIN"
        _python_matches "$candidate" "$expected_major" "$expected_minor" || \
            die "Указанный Python не подходит пакету: $PYTHON_BIN"
        printf '%s\n' "$candidate"
        return 0
    fi

    if [[ -n "$expected_major" && -n "$expected_minor" ]]; then
        for candidate in \
            "$install_root/python/bin/python${expected_major}.${expected_minor}" \
            "$install_root/python/bin/python3" \
            "/opt/python${expected_major}.${expected_minor}/bin/python${expected_major}.${expected_minor}" \
            "/usr/local/bin/python${expected_major}.${expected_minor}" \
            "/usr/bin/python${expected_major}.${expected_minor}"; do
            if _python_matches "$candidate" "$expected_major" "$expected_minor"; then
                printf '%s\n' "$candidate"
                return 0
            fi
        done
        candidate="$(command -v "python${expected_major}.${expected_minor}" 2>/dev/null || true)"
        if _python_matches "$candidate" "$expected_major" "$expected_minor"; then
            printf '%s\n' "$candidate"
            return 0
        fi
    fi

    if [[ -n "$user" ]]; then
        home="$(getent passwd "$user" 2>/dev/null | cut -d: -f6 || true)"
    fi
    if [[ -n "$home" && -d "$home/.pyenv/versions" ]]; then
        if [[ -n "$expected_major" && -n "$expected_minor" ]]; then
            version_glob="${expected_major}.${expected_minor}*"
        else
            version_glob="*"
        fi
        while IFS= read -r candidate; do
            if _python_matches "$candidate" "$expected_major" "$expected_minor"; then
                if run_as_user "$user" "$candidate" -c 'import sys; print(sys.executable)' >/dev/null 2>&1; then
                    printf '%s\n' "$candidate"
                    return 0
                fi
            fi
        done < <(find "$home/.pyenv/versions" -path "*/${version_glob}/bin/python3" -type f -o -type l 2>/dev/null | sort -Vr)
    fi

    for candidate in "$(command -v python3 2>/dev/null || true)" /usr/bin/python3 /usr/local/bin/python3; do
        if _python_matches "$candidate" "$expected_major" "$expected_minor"; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done

    if [[ -n "$expected_major" && -n "$expected_minor" ]]; then
        die "Не найден Python ${expected_major}.${expected_minor}. Установите его в /usr/bin, /usr/local/bin или /opt/python${expected_major}.${expected_minor}, либо укажите --python PATH."
    fi
    die "Не найден Python 3.11+. Укажите путь через --python или PYTHON_BIN."
}

service_stop() {
    command -v systemctl >/dev/null 2>&1 || return 0
    systemctl stop planner-solving.service >/dev/null 2>&1 || true
    systemctl stop planner-web.service >/dev/null 2>&1 || true
}

service_start() {
    command -v systemctl >/dev/null 2>&1 || return 0
    systemctl daemon-reload
    systemctl enable --now planner-solving.service
}

set_shared_owner() {
    local shared="$1" owner="$2"
    mkdir -p "$shared/data" "$shared/input" "$shared/output" "$shared/backups" "$shared/home" "$shared/cache"
    chown -R "$owner" "$shared" 2>/dev/null || true
    find "$shared" -type d -exec chmod 0750 {} + 2>/dev/null || true
    find "$shared" -type f -exec chmod u+rw,g+r,o-rwx {} + 2>/dev/null || true
}

backup_shared() {
    local shared="$1" backup_dir="$2" label="$3"
    mkdir -p "$backup_dir"
    local stamp archive
    stamp="$(date +%Y%m%d-%H%M%S)"
    archive="$backup_dir/${label}-${stamp}.tar.gz"
    tar --ignore-failed-read -czf "$archive" -C "$shared" data teachers.json config.json 2>/dev/null || {
        rm -f "$archive"
        die "Не удалось создать резервную копию данных."
    }
    printf '%s\n' "$archive"
}

restore_shared() {
    local shared="$1" archive="$2"
    [[ -f "$archive" ]] || die "Резервная копия не найдена: $archive"
    rm -rf "$shared/data"
    rm -f "$shared/teachers.json" "$shared/config.json"
    mkdir -p "$shared"
    tar -xzf "$archive" -C "$shared"
    mkdir -p "$shared/data" "$shared/input" "$shared/output" "$shared/backups" "$shared/home" "$shared/cache"
    [[ -f "$shared/teachers.json" ]] || printf '[]\n' > "$shared/teachers.json"
    [[ -f "$shared/config.json" ]] || printf '{}\n' > "$shared/config.json"
}

wait_for_health() {
    local python_bin="$1" port="$2" attempts="${3:-30}"
    "$python_bin" - "$port" "$attempts" <<'PY'
import json
import sys
import time
from urllib.request import urlopen
from urllib.error import URLError

port = int(sys.argv[1])
attempts = int(sys.argv[2])
url = f"http://127.0.0.1:{port}/api/health"
for _ in range(attempts):
    try:
        with urlopen(url, timeout=2) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if response.status == 200 and payload.get("status") == "ok":
            raise SystemExit(0)
    except (OSError, URLError, ValueError, json.JSONDecodeError):
        time.sleep(1)
raise SystemExit(1)
PY
}

write_update_state() {
    local state_path="$1" previous="$2" current="$3" backup="$4" version="$5"
    local writer="${PYTHON_BIN:-python3}"
    "$writer" - "$state_path" "$previous" "$current" "$backup" "$version" <<'PY'
import json
from datetime import datetime, timezone
from pathlib import Path
import sys

path = Path(sys.argv[1])
payload = {
    "updated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    "previous_release": sys.argv[2] or None,
    "current_release": sys.argv[3],
    "backup_archive": sys.argv[4] or None,
    "version": sys.argv[5],
}
path.parent.mkdir(parents=True, exist_ok=True)
tmp = path.with_suffix(path.suffix + ".tmp")
tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
tmp.replace(path)
with (path.parent / "history.jsonl").open("a", encoding="utf-8") as stream:
    stream.write(json.dumps(payload, ensure_ascii=False) + "\n")
PY
}
