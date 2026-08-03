#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
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
        --help|-h) echo "rollback.sh [--install-dir PATH] [--port PORT] [--no-systemd] [--yes]"; exit 0 ;;
        *) die "Неизвестный параметр: $1" ;;
    esac
done

[[ -d "$INSTALL_ROOT" ]] || die "Каталог установки не найден: $INSTALL_ROOT"
INSTALL_ROOT="$(cd "$INSTALL_ROOT" && pwd -P)"
STATE_DIR="$INSTALL_ROOT/state"
STATE="$STATE_DIR/last-update.json"
SHARED="$INSTALL_ROOT/shared"
RUNTIME="$STATE_DIR/run-service.sh"
[[ -f "$STATE" ]] || die "Сведения о предыдущем обновлении не найдены: $STATE"
[[ -d "$SHARED" ]] || die "Каталог данных не найден: $SHARED"
[[ -x "$RUNTIME" ]] || die "Стабильный запускатель не найден: $RUNTIME"

acquire_install_lock "$STATE_DIR"
trap release_install_lock EXIT

if [[ -z "$PORT" && -f /etc/default/planner-solving ]]; then
    PORT="$(read_assignment /etc/default/planner-solving PLANNER_PORT)"
fi
PORT="${PORT:-8001}"
[[ "$PORT" =~ ^[0-9]+$ ]] && ((PORT >= 1 && PORT <= 65535)) || die "Некорректный порт: $PORT"
if [[ $NO_SYSTEMD -eq 0 ]] && ! systemd_available; then NO_SYSTEMD=1; fi

json_string() {
    local key="$1"
    sed -n 's/^[[:space:]]*"'"$key"'"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$STATE" | head -n 1
}
PREVIOUS="$(json_string previous_release)"
RECORDED_CURRENT="$(json_string current_release)"
BACKUP="$(json_string backup_archive)"
CURRENT="$(readlink -f "$INSTALL_ROOT/current" 2>/dev/null || true)"
[[ -n "$CURRENT" ]] || CURRENT="$RECORDED_CURRENT"
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
    echo "Данные будут восстановлены из: $BACKUP"
    printf 'Продолжить? [y/N] '
    read -r answer
    [[ "$answer" =~ ^[YyДд]$ ]] || exit 0
fi

[[ $NO_SYSTEMD -eq 1 ]] || service_stop
EMERGENCY="$(backup_shared "$SHARED" "$SHARED/backups" "before-rollback")"
log "Аварийная копия текущих данных: $EMERGENCY"

rollback_rollback() {
    local code=$?
    warn "Откат не завершён; возвращается состояние до попытки отката."
    [[ $NO_SYSTEMD -eq 1 ]] || service_stop || true
    [[ -d "$CURRENT" ]] && atomic_link "$CURRENT" "$INSTALL_ROOT/current" || true
    restore_shared "$SHARED" "$EMERGENCY" || true
    set_shared_owner "$SHARED" "$SERVICE_USER:$SERVICE_GROUP" || true
    [[ $NO_SYSTEMD -eq 1 ]] || service_start || true
    exit "$code"
}
trap rollback_rollback ERR

restore_shared "$SHARED" "$BACKUP"
set_shared_owner "$SHARED" "$SERVICE_USER:$SERVICE_GROUP"
atomic_link "$PREVIOUS" "$INSTALL_ROOT/current"
run_as_user "$SERVICE_USER" env \
    PLANNER_INSTALL_ROOT="$INSTALL_ROOT" PLANNER_PORT="$PORT" \
    "$RUNTIME" --check

if [[ $NO_SYSTEMD -eq 0 ]]; then
    service_start
    if ! wait_for_health "$PREVIOUS/.venv/bin/python" "$PORT" 75; then
        journalctl -u planner-solving.service -n 120 --no-pager >&2 2>/dev/null || true
        false
    fi
fi

ROLLBACK_VERSION="$(cat "$PREVIOUS/VERSION" 2>/dev/null || echo unknown)"
write_update_state "$STATE" "$CURRENT" "$PREVIOUS" "$EMERGENCY" "$ROLLBACK_VERSION" "$PREVIOUS/.venv/bin/python"
trap - ERR
log "Откат завершён. Активный выпуск: $PREVIOUS"
log "Рабочий venv: $PREVIOUS/.venv"
log "Резервная копия состояния до отката: $EMERGENCY"
