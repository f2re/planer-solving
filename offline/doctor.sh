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
        --help|-h) echo "doctor.sh [--install-dir PATH] [--port PORT] [--output FILE]"; exit 0 ;;
        *) echo "Неизвестный параметр: $1" >&2; exit 2 ;;
    esac
done

TMP_REPORT="$(mktemp -t planner-solving-doctor-XXXXXX)"
cleanup() { rm -f "$TMP_REPORT"; }
trap cleanup EXIT
section() { printf '\n===== %s =====\n' "$1"; }
run() {
    printf '\n$'; printf ' %q' "$@"; printf '\n'
    "$@" 2>&1
    local code=$?
    printf '[код возврата: %s]\n' "$code"
    return "$code"
}

collect_report() {
    local status=0 current="" runtime="" managed="" python="" service_user="planner-solving"

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
    command -v ldd >/dev/null 2>&1 && run ldd --version || true
    run df -h "$INSTALL_ROOT" || true
    run df -i "$INSTALL_ROOT" || true

    section "Структура установки и Python"
    run ls -ld "$INSTALL_ROOT" "$INSTALL_ROOT/current" "$INSTALL_ROOT/releases" "$INSTALL_ROOT/runtime" "$INSTALL_ROOT/shared" "$INSTALL_ROOT/state" || true
    if [[ -e "$INSTALL_ROOT/current" ]]; then
        current="$(readlink -f "$INSTALL_ROOT/current" 2>/dev/null || true)"
        managed="$(cat "$current/.planner-runtime" 2>/dev/null || cat "$current/.venv/.planner-runtime" 2>/dev/null || true)"
        python="$current/.venv/bin/python"
        echo "Активный выпуск: $current"
        echo "Рабочий venv: $current/.venv"
        echo "Управляемый runtime: ${managed:-не указан}"
        [[ -f "$current/VERSION" ]] && echo "Версия приложения: $(cat "$current/VERSION")"
        run ls -l "$python" "$current/.venv/bin/python.real" || status=1
        run "$python" --version || status=1
        run "$python" -c 'import sys; print("executable=",sys.executable); print("prefix=",sys.prefix); print("base_prefix=",sys.base_prefix)' || status=1
        run "$python" -c 'import fastapi,openpyxl,ortools,pandas,pydantic,uvicorn; print("основные библиотеки: OK")' || status=1
        [[ -x "$managed/python" ]] && run "$managed/python" -c 'import ensurepip,ssl,sqlite3,sys,venv; print("runtime=",sys.version)' || status=1
        command -v ldd >/dev/null 2>&1 && [[ -f "$current/.venv/bin/python.real" ]] && run ldd "$current/.venv/bin/python.real" || true
    else
        echo "ОШИБКА: ссылка current отсутствует"
        status=1
    fi

    section "Найденные Python и виртуальные окружения"
    if [[ -x "$INSTALL_ROOT/state/python-info.sh" ]]; then
        run "$INSTALL_ROOT/state/python-info.sh" || status=1
    else
        echo "Команда поиска Python отсутствует: $INSTALL_ROOT/state/python-info.sh"
        status=1
    fi

    section "Права на данные"
    command -v namei >/dev/null 2>&1 && run namei -l "$INSTALL_ROOT/shared/data" || true
    run find "$INSTALL_ROOT/shared" -maxdepth 2 -printf '%M %u:%g %p\n' || true

    section "Стабильный запуск"
    runtime="$INSTALL_ROOT/state/run-service.sh"
    if [[ -x "$runtime" ]]; then
        run env PLANNER_INSTALL_ROOT="$INSTALL_ROOT" PLANNER_PORT="$PORT" "$runtime" --print || status=1
        run env PLANNER_INSTALL_ROOT="$INSTALL_ROOT" PLANNER_PORT="$PORT" "$runtime" --check || status=1
    else
        echo "ОШИБКА: отсутствует $runtime"
        status=1
    fi

    section "systemd"
    if command -v systemctl >/dev/null 2>&1 && [[ -d /run/systemd/system ]]; then
        [[ -f /etc/systemd/system/planner-solving.service ]] && service_user="$(awk -F= '$1=="User"{print $2; exit}' /etc/systemd/system/planner-solving.service)"
        echo "Пользователь службы: ${service_user:-не определён}"
        run systemctl cat "$SERVICE" || status=1
        run systemctl status "$SERVICE" --no-pager -l || status=1
        run systemctl is-enabled "$SERVICE" || true
        run systemctl is-active "$SERVICE" || status=1
        command -v journalctl >/dev/null 2>&1 && run journalctl -u "$SERVICE" -n 160 --no-pager -o short-iso || true
    else
        echo "systemd не запущен в этом окружении."
    fi

    section "Порт и HTTP"
    if command -v ss >/dev/null 2>&1; then run ss -ltnp || true
    elif command -v netstat >/dev/null 2>&1; then run netstat -ltnp || true
    fi
    if command -v curl >/dev/null 2>&1; then
        run curl -fsS --max-time 5 "http://127.0.0.1:$PORT/api/health" || status=1
        run curl -fsS --max-time 8 "http://127.0.0.1:$PORT/api/system/recovery" || true
    elif [[ -x "$python" ]]; then
        run "$python" - "$PORT" <<'PY' || status=1
import sys
from urllib.request import urlopen
with urlopen(f"http://127.0.0.1:{int(sys.argv[1])}/api/health", timeout=5) as response:
    print(response.read().decode('utf-8'))
PY
    fi

    section "Последнее обновление"
    [[ -f "$INSTALL_ROOT/state/last-update.json" ]] && cat "$INSTALL_ROOT/state/last-update.json" || echo "Сведения отсутствуют."
    [[ -f "$INSTALL_ROOT/state/history.jsonl" ]] && tail -n 15 "$INSTALL_ROOT/state/history.jsonl" || true

    section "План восстановления"
    echo "1. Не удаляйте $INSTALL_ROOT/shared: там находятся база, черновики, история и результаты."
    echo "2. Устраните первый неуспешный раздел выше: место/права, Python, SQLite, systemd или порт."
    echo "3. Безопасное восстановление выпуска и venv:"
    echo "   sudo ./install-planner-solving.sh --python bundled --strict-python --repair"
    echo "4. После восстановления перезапустите и проверьте службу:"
    echo "   sudo systemctl daemon-reload"
    echo "   sudo systemctl restart $SERVICE"
    echo "   curl -fsS http://127.0.0.1:$PORT/api/health"
    echo "5. Если ошибка повторяется, приложите этот отчёт и код инцидента из интерфейса."

    section "Итог"
    if [[ $status -eq 0 ]]; then
        echo "Критических проблем не обнаружено. Повтор операции безопасен."
    else
        echo "Обнаружены ошибки. Рабочие данные не удаляйте; выполните план восстановления выше."
    fi
    return "$status"
}

collect_report | tee "$TMP_REPORT"
STATUS=${PIPESTATUS[0]}
if [[ -n "$OUTPUT" ]]; then
    install -m 0644 "$TMP_REPORT" "$OUTPUT"
    echo "Отчёт сохранён: $OUTPUT"
fi
exit "$STATUS"
