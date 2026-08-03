#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

# ---------------------------------------------------------------------------
# Определяем базовый Python и создаём .venv при необходимости.
# ---------------------------------------------------------------------------
if [[ -n "${PLANNER_PYTHON:-}" ]]; then
    _BASE_PYTHON="$PLANNER_PYTHON"
else
    _BASE_PYTHON="${PYTHON_BIN:-python3}"
fi

if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
    echo "[planner] .venv не найден — создаю виртуальное окружение..."
    "$_BASE_PYTHON" -m venv "$ROOT/.venv"
    "$ROOT/.venv/bin/python" -m pip install --upgrade pip >/dev/null 2>&1 || true
    "$ROOT/.venv/bin/python" -m pip install -r "$ROOT/requirements-runtime.txt"
fi
PYTHON_BIN="$ROOT/.venv/bin/python"

export PYTHONPATH="$ROOT"
DATA_DIR="$ROOT/data"
BACKUP_DIR="${PLANNER_BACKUP_DIR:-$ROOT/data/backups/migrations}"
PORT="${PLANNER_PORT:-8001}"
HOST="${PLANNER_HOST:-0.0.0.0}"

"$PYTHON_BIN" -m tools.migrate \
    --data-dir "$DATA_DIR" \
    --legacy-teachers "$ROOT/teachers.json" \
    --backup-dir "$BACKUP_DIR"

# Импорт приложения создаёт/обновляет SQLite из проверенного JSON-зеркала.
# Запуск сервера запрещается, если база повреждена или имеет неподдерживаемую версию.
"$PYTHON_BIN" -m tools.healthcheck \
    --app-root "$ROOT" \
    --data-dir "$DATA_DIR"

echo "Запуск веб-интерфейса на http://$HOST:$PORT"
exec "$PYTHON_BIN" -m uvicorn web.backend.main:app --host "$HOST" --port "$PORT" --workers 1
