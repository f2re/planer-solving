#!/usr/bin/env bash
set -Eeuo pipefail

log() { printf '[planner] %s\n' "$*"; }
warn() { printf '[planner] ПРЕДУПРЕЖДЕНИЕ: %s\n' "$*" >&2; }
die() { printf '[planner] ОШИБКА: %s\n' "$*" >&2; exit 2; }

require_command() {
    command -v "$1" >/dev/null 2>&1 || die "Не найдена команда: $1"
}

atomic_link() {
    local target="$1" link="$2" temporary="${link}.next.$$"
    rm -f "$temporary"
    ln -s "$target" "$temporary"
    mv -Tf "$temporary" "$link"
}

service_stop() {
    local service
    command -v systemctl >/dev/null 2>&1 || return 0
    for service in planner-solving.service planner-web.service; do
        if systemctl list-unit-files "$service" >/dev/null 2>&1; then
            systemctl stop "$service" >/dev/null 2>&1 || true
        fi
    done
}

service_start() {
    command -v systemctl >/dev/null 2>&1 || return 0
    systemctl daemon-reload
    systemctl enable --now planner-solving.service
}

set_shared_owner() {
    local shared="$1" owner="$2"
    chmod 0755 "$shared" 2>/dev/null || true
    chown -R "$owner" "$shared/data" "$shared/input" "$shared/output" 2>/dev/null || true
    chown "$owner" "$shared/teachers.json" "$shared/config.json" 2>/dev/null || true
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
    mkdir -p "$shared/data"
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
    "${PYTHON_BIN:-python3}" - "$state_path" "$previous" "$current" "$backup" "$version" <<'PY'
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
