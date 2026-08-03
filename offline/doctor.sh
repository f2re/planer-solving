#!/usr/bin/env bash
set -u

INSTALL_ROOT="${PLANNER_INSTALL_ROOT:-/opt/planner-solving}"
SERVICE="planner-solving.service"
PORT="${PLANNER_PORT:-8001}"
OUTPUT=""

while (($#)); do
    case "$1" in
        --install-dir) INSTALL_ROOT="$2"; shift 2 ;;
        --service) SERVICE="$2"; shift 2 ;;
        --port) PORT="$2"; shift 2 ;;
        --output) OUTPUT="$2"; shift 2 ;;
        --help|-h)
            echo "doctor.sh [--install-dir PATH] [--port PORT] [--output FILE]"
            exit 0
            ;;
        *) echo "Неизвестный параметр: $1" >&2; exit 2 ;;
    esac
done

STATUS=0
TMP_REPORT="$(mktemp -t planner-solving-doctor-XXXXXX)"
cleanup() { rm -f "$TMP_REPORT"; }
trap cleanup EXIT

section() { printf '\n===== %s =====\n' "$1"; }
run() {
    printf '\n$'
    printf ' %q' "$@"
    printf '\n'
    "$@" 2>&1
    local code=$?
    printf '[код возврата: %s]\n' "$code"
    return "$code"
}

{
    echo "Отчёт диагностики Planner Solving"
    echo "Дата: $(date -Is 2>/dev/null || date)"
    echo "Узел: $(hostname 2>/dev/null || echo unknown)"
    echo "Пользователь: $(id 2>/dev/null || true)"
    echo "Каталог установки: $INSTALL_ROOT"
    echo "Служба: $SERVICE"
    echo "Порт: $PORT"

    section "Система"
    run uname -a || true
    [[ -f /etc/os-release ]] && cat /etc/os-release
    run df -h "$INSTALL_ROOT" || true
    run df -i "$INSTALL_ROOT" || true

    section "Структура установки"
    run ls -ld "$INSTALL_ROOT" "$INSTALL_ROOT/current" "$INSTALL_ROOT/releases" "$INSTALL_ROOT/shared" "$INSTALL_ROOT/state" || true
    if [[ -e "$INSTALL_ROOT/current" ]]; then
        CURRENT="$(readlink -f "$INSTALL_ROOT/current" 2>/dev/null || true)"
        echo "Активный выпуск: $CURRENT"
        [[ -f "$CURRENT/VERSION" ]] && echo "Версия: $(cat "$CURRENT/VERSION")"
        run ls -l "$CURRENT/.venv/bin/python" || true
        run "$CURRENT/.venv/bin/python" --version || STATUS=1
        run "$CURRENT/.venv/bin/python" -c 'import sys; print("executable=",sys.executable); print("prefix=",sys.prefix); print("base_prefix=",sys.base_prefix)' || STATUS=1
    else
        echo "ОШИБКА: ссылка current отсутствует"
        STATUS=1
    fi

    section "Права на данные"
    run find "$INSTALL_ROOT/shared" -maxdepth 2 -printf '%M %u:%g %p\n' || true

    section "Стабильный запуск"
    RUNTIME="$INSTALL_ROOT/state/run-service.sh"
    if [[ -x "$RUNTIME" ]]; then
        PLANNER_INSTALL_ROOT="$INSTALL_ROOT" PLANNER_PORT="$PORT" run "$RUNTIME" --print || STATUS=1
        PLANNER_INSTALL_ROOT="$INSTALL_ROOT" PLANNER_PORT="$PORT" run "$RUNTIME" --check || STATUS=1
    else
        echo "ОШИБКА: отсутствует $RUNTIME"
        STATUS=1
    fi

    section "systemd"
    if command -v systemctl >/dev/null 2>&1; then
        run systemctl cat "$SERVICE" || STATUS=1
        run systemctl status "$SERVICE" --no-pager -l || STATUS=1
        run systemctl is-enabled "$SERVICE" || true
        run systemctl is-active "$SERVICE" || STATUS=1
        if command -v journalctl >/dev/null 2>&1; then
            run journalctl -u "$SERVICE" -n 120 --no-pager -o short-iso || true
        fi
    else
        echo "systemd не найден."
    fi

    section "Порт и HTTP"
    if command -v ss >/dev/null 2>&1; then
        run ss -ltnp || true
    elif command -v netstat >/dev/null 2>&1; then
        run netstat -ltnp || true
    fi
    if command -v curl >/dev/null 2>&1; then
        run curl -fsS --max-time 5 "http://127.0.0.1:$PORT/api/health" || STATUS=1
    elif [[ -x "${CURRENT:-}/.venv/bin/python" ]]; then
        run "$CURRENT/.venv/bin/python" - "$PORT" <<'PY' || STATUS=1
import sys
from urllib.request import urlopen
port = int(sys.argv[1])
with urlopen(f"http://127.0.0.1:{port}/api/health", timeout=5) as response:
    print(response.read().decode("utf-8"))
PY
    fi

    section "Последнее обновление"
    [[ -f "$INSTALL_ROOT/state/last-update.json" ]] && cat "$INSTALL_ROOT/state/last-update.json" || echo "Сведения отсутствуют."
    [[ -f "$INSTALL_ROOT/state/history.jsonl" ]] && tail -n 10 "$INSTALL_ROOT/state/history.jsonl" || true

    section "Итог"
    if [[ $STATUS -eq 0 ]]; then
        echo "Критических проблем не обнаружено."
    else
        echo "Обнаружены ошибки. Сохраните этот отчёт и исправьте первый неуспешный раздел."
    fi
} | tee "$TMP_REPORT"

if [[ -n "$OUTPUT" ]]; then
    install -m 0644 "$TMP_REPORT" "$OUTPUT"
    echo "Отчёт сохранён: $OUTPUT"
fi
exit "$STATUS"
