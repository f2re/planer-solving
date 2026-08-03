#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

BASE_PYTHON="${PLANNER_PYTHON:-${PYTHON_BIN:-python3}}"
VENV="$ROOT/.venv"
PYTHON="$VENV/bin/python"

if [[ ! -x "$PYTHON" ]]; then
    if [[ "${PLANNER_MANAGED_INSTALL:-0}" == "1" || "$ROOT" == /opt/planner-solving/releases/* ]]; then
        echo "[planner] В управляемом выпуске отсутствует .venv: $VENV" >&2
        echo "[planner] Повторите установку автономным пакетом; служба не устанавливает зависимости при старте." >&2
        exit 2
    fi
    command -v "$BASE_PYTHON" >/dev/null 2>&1 || {
        echo "[planner] Python не найден: $BASE_PYTHON" >&2
        exit 2
    }
    echo "[planner] Создаётся локальное виртуальное окружение..."
    "$BASE_PYTHON" -m venv "$VENV" || {
        echo "[planner] Не удалось создать venv. Установите python3-venv." >&2
        exit 2
    }
    if [[ -d "$ROOT/wheelhouse" ]] && find "$ROOT/wheelhouse" -maxdepth 1 -name '*.whl' -print -quit | grep -q .; then
        "$PYTHON" -m pip install --disable-pip-version-check --no-index \
            --find-links "$ROOT/wheelhouse" -r "$ROOT/requirements-runtime.txt"
    else
        "$PYTHON" -m pip install --disable-pip-version-check -r "$ROOT/requirements-runtime.txt"
    fi
fi

export PLANNER_BASE_DIR="$ROOT"
export PYTHONPATH="$ROOT"
export PYTHONDONTWRITEBYTECODE=1
export PYTHONUNBUFFERED=1
export PYTHONNOUSERSITE=1
export VIRTUAL_ENV="$VENV"
export PATH="$VENV/bin:$PATH"
unset PYTHONHOME

DATA_DIR="${PLANNER_DATA_DIR:-$ROOT/data}"
BACKUP_DIR="${PLANNER_BACKUP_DIR:-$DATA_DIR/backups/migrations}"
PORT="${PLANNER_PORT:-8001}"
HOST="${PLANNER_HOST:-0.0.0.0}"
WORKERS="${PLANNER_WORKERS:-1}"

"$PYTHON" -m tools.service_preflight \
    --app-root "$ROOT" \
    --shared-dir "$DATA_DIR"
"$PYTHON" -m tools.migrate \
    --data-dir "$DATA_DIR" \
    --legacy-teachers "$ROOT/teachers.json" \
    --backup-dir "$BACKUP_DIR"
"$PYTHON" -m tools.healthcheck \
    --app-root "$ROOT" \
    --data-dir "$DATA_DIR"

echo "Запуск веб-интерфейса на http://$HOST:$PORT"
exec "$PYTHON" -m uvicorn web.backend.main:app \
    --host "$HOST" \
    --port "$PORT" \
    --workers "$WORKERS"
