#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_ROOT/common.sh"

INSTALL_ROOT=""
PORT="8001"
PYTHON_BIN="${PYTHON_BIN:-python3}"
NO_SYSTEMD=0
ASSUME_YES=0
while (($#)); do
    case "$1" in
        --install-dir) INSTALL_ROOT="$2"; shift 2 ;;
        --port) PORT="$2"; shift 2 ;;
        --python) PYTHON_BIN="$2"; shift 2 ;;
        --no-systemd) NO_SYSTEMD=1; shift ;;
        --yes|-y) ASSUME_YES=1; shift ;;
        --help|-h) echo "rollback.sh --install-dir PATH [--no-systemd] [--yes]"; exit 0 ;;
        *) die "Неизвестный параметр: $1" ;;
    esac
done
if [[ -z "$INSTALL_ROOT" ]]; then
    if [[ $EUID -eq 0 ]]; then INSTALL_ROOT="/opt/planner-solving"; else INSTALL_ROOT="$HOME/.local/opt/planner-solving"; fi
fi
INSTALL_ROOT="$(cd "$INSTALL_ROOT" && pwd)"
STATE="$INSTALL_ROOT/state/last-update.json"
SHARED="$INSTALL_ROOT/shared"
[[ -f "$STATE" ]] || die "Сведения о предыдущем обновлении не найдены: $STATE"

readarray -t META < <("$PYTHON_BIN" - "$STATE" <<'PY'
import json, sys
from pathlib import Path
m=json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
print(m.get("previous_release") or "")
print(m.get("current_release") or "")
print(m.get("backup_archive") or "")
PY
)
PREVIOUS="${META[0]}"; CURRENT="${META[1]}"; BACKUP="${META[2]}"
[[ -d "$PREVIOUS" ]] || die "Предыдущий выпуск отсутствует: $PREVIOUS"
[[ -f "$BACKUP" ]] || die "Резервная копия данных отсутствует: $BACKUP"

if [[ $ASSUME_YES -eq 0 ]]; then
    echo "Откат вернёт код и данные к состоянию до последнего обновления."
    printf 'Продолжить? [y/N] '
    read -r answer
    [[ "$answer" =~ ^[YyДд]$ ]] || exit 0
fi

[[ $NO_SYSTEMD -eq 1 ]] || service_stop
EMERGENCY="$(backup_shared "$SHARED" "$SHARED/backups" "before-rollback")"
rollback_rollback() {
    local code=$?
    warn "Откат не завершён, возвращается состояние до попытки отката."
    [[ -d "$CURRENT" ]] && atomic_link "$CURRENT" "$INSTALL_ROOT/current"
    restore_shared "$SHARED" "$EMERGENCY"
    [[ $NO_SYSTEMD -eq 1 ]] || service_start || true
    exit "$code"
}
trap rollback_rollback ERR

restore_shared "$SHARED" "$BACKUP"
atomic_link "$PREVIOUS" "$INSTALL_ROOT/current"
(
    cd "$PREVIOUS"
    PYTHONPATH="$PREVIOUS" "$PREVIOUS/.venv/bin/python" -m tools.healthcheck \
        --app-root "$PREVIOUS" --data-dir "$SHARED/data"
)
if [[ $NO_SYSTEMD -eq 0 ]]; then
    service_start
    wait_for_health "$PYTHON_BIN" "$PORT" 45 || die "После отката служба не прошла проверку."
fi
trap - ERR
log "Откат завершён. Текущий выпуск: $PREVIOUS"
log "Резервная копия состояния до отката: $EMERGENCY"
