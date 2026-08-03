#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_ROOT/common.sh"

INSTALL_ROOT="/opt/planner-solving"
PORT=""
NO_SYSTEMD=0
ASSUME_YES=0

while (($#)); do
    case "$1" in
        --install-dir) INSTALL_ROOT="$2"; shift 2 ;;
        --port) PORT="$2"; shift 2 ;;
        --no-systemd) NO_SYSTEMD=1; shift ;;
        --yes|-y) ASSUME_YES=1; shift ;;
        --help|-h)
            echo "rollback.sh [--install-dir PATH] [--port PORT] [--no-systemd] [--yes]"
            exit 0
            ;;
        *) die "Неизвестный параметр: $1" ;;
    esac
done

[[ -d "$INSTALL_ROOT" ]] || die "Каталог установки не найден: $INSTALL_ROOT"
INSTALL_ROOT="$(cd "$INSTALL_ROOT" && pwd)"
STATE="$INSTALL_ROOT/state/last-update.json"
SHARED="$INSTALL_ROOT/shared"
RUNTIME="$INSTALL_ROOT/state/run-service.sh"
[[ -f "$STATE" ]] || die "Сведения о предыдущем обновлении не найдены: $STATE"
[[ -d "$SHARED" ]] || die "Каталог данных не найден: $SHARED"
[[ -x "$RUNTIME" ]] || die "Стабильный запускатель не найден: $RUNTIME"

if [[ -z "$PORT" && -f /etc/default/planner-solving ]]; then
    PORT="$(sed -n 's/^PLANNER_PORT=["'"']\{0,1\}\([^"'"']*\)["'"']\{0,1\}$/\1/p' /etc/default/planner-solving | tail -n 1)"
fi
PORT="${PORT:-8001}"
[[ "$PORT" =~ ^[0-9]+$ ]] && ((PORT >= 1 && PORT <= 65535)) || die "Некорректный порт: $PORT"

ACTIVE="$(readlink -f "$INSTALL_ROOT/current" 2>/dev/null || true)"
[[ -x "$ACTIVE/.venv/bin/python" ]] || die "Python активного выпуска недоступен: $ACTIVE/.venv/bin/python"
readarray -t META < <("$ACTIVE/.venv/bin/python" - "$STATE" <<'PY'
import json, sys
from pathlib import Path
m=json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
print(m.get("previous_release") or "")
print(m.get("current_release") or "")
print(m.get("backup_archive") or "")
PY
)
PREVIOUS="${META[0]}"
CURRENT="${META[1]}"
BACKUP="${META[2]}"
[[ -d "$PREVIOUS" ]] || die "Предыдущий выпуск отсутствует: $PREVIOUS"
[[ -x "$PREVIOUS/.venv/bin/python" ]] || die "В предыдущем выпуске нет рабочего venv: $PREVIOUS/.venv/bin/python"
[[ -f "$BACKUP" ]] || die "Резервная копия данных отсутствует: $BACKUP"

SERVICE_USER="planner-solving"
if [[ -f /etc/systemd/system/planner-solving.service ]]; then
    SERVICE_USER="$(awk -F= '$1=="User"{print $2; exit}' /etc/systemd/system/planner-solving.service)"
fi
SERVICE_USER="${SERVICE_USER:-planner-solving}"
SERVICE_GROUP="$(id -gn "$SERVICE_USER" 2>/dev/null || echo "$SERVICE_USER")"

if [[ $ASSUME_YES -eq 0 ]]; then
    echo "Текущий выпуск: $CURRENT"
    echo "Будет восстановлен: $PREVIOUS"
    echo "Будут восстановлены данные из: $BACKUP"
    printf 'Продолжить? [y/N] '
    read -r answer
    [[ "$answer" =~ ^[YyДд]$ ]] || exit 0
fi

[[ $NO_SYSTEMD -eq 1 ]] || service_stop
EMERGENCY="$(backup_shared "$SHARED" "$SHARED/backups" "before-rollback")"
log "Аварийная копия текущих данных: $EMERGENCY"

rollback_rollback() {
    local code=$?
    warn "Откат не завершён, возвращается состояние до попытки отката."
    [[ $NO_SYSTEMD -eq 1 ]] || service_stop || true
    [[ -d "$CURRENT" ]] && atomic_link "$CURRENT" "$INSTALL_ROOT/current"
    restore_shared "$SHARED" "$EMERGENCY"
    set_shared_owner "$SHARED" "$SERVICE_USER:$SERVICE_GROUP"
    [[ $NO_SYSTEMD -eq 1 ]] || service_start || true
    exit "$code"
}
trap rollback_rollback ERR

restore_shared "$SHARED" "$BACKUP"
set_shared_owner "$SHARED" "$SERVICE_USER:$SERVICE_GROUP"
atomic_link "$PREVIOUS" "$INSTALL_ROOT/current"

run_as_user "$SERVICE_USER" env \
    PLANNER_INSTALL_ROOT="$INSTALL_ROOT" \
    PLANNER_PORT="$PORT" \
    "$RUNTIME" --check

if [[ $NO_SYSTEMD -eq 0 ]]; then
    service_start
    if ! wait_for_health "$PREVIOUS/.venv/bin/python" "$PORT" 60; then
        warn "После отката служба не прошла HTTP-проверку."
        journalctl -u planner-solving.service -n 100 --no-pager >&2 2>/dev/null || true
        false
    fi
fi

ROLLBACK_VERSION="$(cat "$PREVIOUS/VERSION" 2>/dev/null || echo unknown)"
PYTHON_BIN="$PREVIOUS/.venv/bin/python"
export PYTHON_BIN
write_update_state "$STATE" "$CURRENT" "$PREVIOUS" "$EMERGENCY" "$ROLLBACK_VERSION"
trap - ERR
log "Откат завершён. Текущий выпуск: $PREVIOUS"
log "Резервная копия состояния до отката: $EMERGENCY"
