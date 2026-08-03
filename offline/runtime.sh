#!/usr/bin/env bash
set -Eeuo pipefail

INSTALL_ROOT="${PLANNER_INSTALL_ROOT:-/opt/planner-solving}"
HOST="${PLANNER_HOST:-0.0.0.0}"
PORT="${PLANNER_PORT:-8001}"
WORKERS="${PLANNER_WORKERS:-1}"
MODE="start"

usage() {
    cat <<'EOF_HELP'
Стабильный запуск Planner Solving.

  run-service.sh [--check|--print]
EOF_HELP
}
while (($#)); do
    case "$1" in
        --check) MODE="check"; shift ;;
        --print) MODE="print"; shift ;;
        --help|-h) usage; exit 0 ;;
        *) echo "Неизвестный параметр: $1" >&2; usage; exit 2 ;;
    esac
done

fail() {
    printf '[planner-runtime] ОШИБКА: %s\n' "$*" >&2
    printf '[planner-runtime] Выполните: sudo planner-solving-doctor\n' >&2
    exit 2
}

[[ "$PORT" =~ ^[0-9]+$ ]] && ((PORT >= 1 && PORT <= 65535)) || fail "Некорректный порт: $PORT"
[[ "$WORKERS" =~ ^[0-9]+$ ]] && ((WORKERS >= 1 && WORKERS <= 16)) || fail "Некорректное число процессов: $WORKERS"
[[ -L "$INSTALL_ROOT/current" || -d "$INSTALL_ROOT/current" ]] || fail "Нет активного выпуска: $INSTALL_ROOT/current"
CURRENT="$(readlink -f "$INSTALL_ROOT/current")"
[[ -d "$CURRENT" ]] || fail "Активный выпуск отсутствует: $CURRENT"
PYTHON="$CURRENT/.venv/bin/python"
[[ -f "$PYTHON" && -x "$PYTHON" ]] || fail "Рабочий venv отсутствует: $PYTHON"
MANAGED_RUNTIME="$(cat "$CURRENT/.planner-runtime" 2>/dev/null || cat "$CURRENT/.venv/.planner-runtime" 2>/dev/null || true)"
LEGACY_RUNTIME=0
if [[ -z "$MANAGED_RUNTIME" || ! -x "$MANAGED_RUNTIME/python" ]]; then
    MANAGED_RUNTIME=""
    LEGACY_RUNTIME=1
fi
[[ -d "$INSTALL_ROOT/shared" ]] || fail "Каталог данных отсутствует: $INSTALL_ROOT/shared"

export PLANNER_BASE_DIR="$CURRENT"
export PYTHONPATH="$CURRENT"
export PYTHONDONTWRITEBYTECODE=1
export PYTHONUNBUFFERED=1
export PYTHONNOUSERSITE=1
export VIRTUAL_ENV="$CURRENT/.venv"
export PATH="$VIRTUAL_ENV/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
export HOME="${PLANNER_HOME:-$INSTALL_ROOT/shared/home}"
export XDG_CACHE_HOME="${PLANNER_CACHE_DIR:-$INSTALL_ROOT/shared/cache}"
unset PYTHONHOME
mkdir -p "$HOME" "$XDG_CACHE_HOME"
cd "$CURRENT"

if [[ "$MODE" == print ]]; then
    cat <<EOF_PRINT
INSTALL_ROOT=$INSTALL_ROOT
CURRENT=$CURRENT
MANAGED_RUNTIME=${MANAGED_RUNTIME:-legacy/system}
LEGACY_RUNTIME=$LEGACY_RUNTIME
PYTHON=$PYTHON
PYTHONPATH=$PYTHONPATH
VIRTUAL_ENV=$VIRTUAL_ENV
HOME=$HOME
HOST=$HOST
PORT=$PORT
WORKERS=$WORKERS
EOF_PRINT
    "$PYTHON" -c 'import sys; print("PYTHON_VERSION=" + sys.version.split()[0]); print("SYS_EXECUTABLE=" + sys.executable); print("SYS_PREFIX=" + sys.prefix); print("SYS_BASE_PREFIX=" + sys.base_prefix)'
    exit 0
fi

if [[ -f "$CURRENT/tools/service_preflight.py" ]]; then
    "$PYTHON" -m tools.service_preflight \
        --app-root "$CURRENT" \
        --shared-dir "$INSTALL_ROOT/shared" \
        --full
fi

if [[ "$MODE" == check ]]; then
    "$PYTHON" -m tools.healthcheck \
        --app-root "$CURRENT" \
        --data-dir "$INSTALL_ROOT/shared/data"
    exit 0
fi

exec "$PYTHON" -m uvicorn web.backend.main:app \
    --host "$HOST" \
    --port "$PORT" \
    --workers "$WORKERS"
