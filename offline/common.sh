#!/usr/bin/env bash
set -Eeuo pipefail

log() { printf '[planner] %s\n' "$*"; }
warn() { printf '[planner] ПРЕДУПРЕЖДЕНИЕ: %s\n' "$*" >&2; }
die() { printf '[planner] ОШИБКА: %s\n' "$*" >&2; exit 2; }

require_command() {
    local command_name="${1:-}"
    [[ -n "$command_name" ]] || die "Не задано имя команды."
    if [[ "$command_name" == */* ]]; then
        [[ -f "$command_name" && -x "$command_name" ]] || \
            die "Не найдена исполняемая команда (ожидался файл, а не каталог): $command_name"
    else
        command -v -- "$command_name" >/dev/null 2>&1 || die "Не найдена команда: $command_name"
    fi
}

canonical_path() {
    if command -v readlink >/dev/null 2>&1; then
        readlink -f -- "$1" 2>/dev/null || printf '%s\n' "$1"
    else
        printf '%s\n' "$1"
    fi
}

hash_file() {
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
        die "Не найдены sha256sum, busybox, openssl или python3 для SHA-256."
    fi
}

read_assignment() {
    local path="$1" key="$2"
    [[ -f "$path" ]] || return 0
    sed -n "s/^[[:space:]]*${key}[[:space:]]*=[[:space:]]*[\"']\{0,1\}\([^\"']*\)[\"']\{0,1\}[[:space:]]*$/\1/p" "$path" | tail -n 1
}

atomic_link() {
    local target="$1" link="$2" temporary="${2}.next.$$"
    rm -f "$temporary"
    ln -s "$target" "$temporary"
    mv -Tf "$temporary" "$link" 2>/dev/null || mv -f "$temporary" "$link"
}

run_as_user() {
    local user="$1"
    shift
    if [[ $EUID -ne 0 || -z "$user" || "$user" == root || "$user" == "$(id -un)" ]]; then
        "$@"
        return
    fi
    id "$user" >/dev/null 2>&1 || die "Пользователь не существует: $user"
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

INSTALL_LOCK_MODE=""
INSTALL_LOCK_PATH=""
acquire_install_lock() {
    local state_dir="$1"
    mkdir -p "$state_dir"
    INSTALL_LOCK_PATH="$state_dir/install.lock"
    if command -v flock >/dev/null 2>&1; then
        exec 9>"$INSTALL_LOCK_PATH"
        flock -n 9 || die "Другая установка или обновление уже выполняется: $INSTALL_LOCK_PATH"
        INSTALL_LOCK_MODE="flock"
    else
        INSTALL_LOCK_PATH="$state_dir/install.lock.d"
        mkdir "$INSTALL_LOCK_PATH" 2>/dev/null || \
            die "Другая установка или обновление уже выполняется: $INSTALL_LOCK_PATH"
        INSTALL_LOCK_MODE="mkdir"
    fi
}

release_install_lock() {
    if [[ "$INSTALL_LOCK_MODE" == mkdir && -n "$INSTALL_LOCK_PATH" ]]; then
        rmdir "$INSTALL_LOCK_PATH" 2>/dev/null || true
    fi
    INSTALL_LOCK_MODE=""
}

systemd_available() {
    command -v systemctl >/dev/null 2>&1 && [[ -d /run/systemd/system ]]
}

service_stop() {
    systemd_available || return 0
    systemctl stop planner-solving.service >/dev/null 2>&1 || true
    systemctl stop planner-web.service >/dev/null 2>&1 || true
}

service_start() {
    systemd_available || return 1
    systemctl daemon-reload
    systemctl enable planner-solving.service >/dev/null
    systemctl restart planner-solving.service
}

set_shared_owner() {
    local shared="$1" owner="$2"
    mkdir -p "$shared/data" "$shared/input" "$shared/output" "$shared/backups" "$shared/home" "$shared/cache"
    chown -R "$owner" "$shared" 2>/dev/null || true
    find "$shared" -type d -exec chmod 0750 {} + 2>/dev/null || true
    find "$shared" -type f -exec chmod u+rw,g+r,o-rwx {} + 2>/dev/null || true
}

backup_shared() {
    local shared="$1" backup_dir="$2" label="$3" stamp archive
    mkdir -p "$backup_dir"
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
import json, sys, time
from urllib.error import URLError
from urllib.request import urlopen
port = int(sys.argv[1]); attempts = int(sys.argv[2])
url = f"http://127.0.0.1:{port}/api/health"
for _ in range(attempts):
    try:
        with urlopen(url, timeout=2) as response:
            payload = json.loads(response.read().decode('utf-8'))
        if response.status == 200 and payload.get('status') == 'ok':
            raise SystemExit(0)
    except (OSError, URLError, ValueError, json.JSONDecodeError):
        time.sleep(1)
raise SystemExit(1)
PY
}

port_available() {
    local python_bin="$1" host="$2" port="$3"
    "$python_bin" - "$host" "$port" <<'PY'
import socket, sys
host = sys.argv[1]
port = int(sys.argv[2])
probe_host = '' if host in ('0.0.0.0', '::') else host
family = socket.AF_INET6 if ':' in probe_host else socket.AF_INET
sock = socket.socket(family, socket.SOCK_STREAM)
try:
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((probe_host, port))
except OSError as exc:
    print(exc, file=sys.stderr)
    raise SystemExit(1)
finally:
    sock.close()
PY
}

write_update_state() {
    local state_path="$1" previous="$2" current="$3" backup="$4" version="$5"
    local writer="${6:-${PYTHON_BIN:-python3}}"
    "$writer" - "$state_path" "$previous" "$current" "$backup" "$version" <<'PY'
import json, sys
from datetime import datetime, timezone
from pathlib import Path
path = Path(sys.argv[1])
payload = {
    'updated_at': datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    'previous_release': sys.argv[2] or None,
    'current_release': sys.argv[3],
    'backup_archive': sys.argv[4] or None,
    'version': sys.argv[5],
}
path.parent.mkdir(parents=True, exist_ok=True)
tmp = path.with_suffix(path.suffix + '.tmp')
tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
tmp.replace(path)
with (path.parent / 'history.jsonl').open('a', encoding='utf-8') as stream:
    stream.write(json.dumps(payload, ensure_ascii=False) + '\n')
PY
}
