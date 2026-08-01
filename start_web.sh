#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

if [[ -n "${PLANNER_PYTHON:-}" ]]; then
    PYTHON_BIN="$PLANNER_PYTHON"
elif [[ -x "$ROOT/.venv/bin/python" ]]; then
    PYTHON_BIN="$ROOT/.venv/bin/python"
else
    PYTHON_BIN="${PYTHON_BIN:-python3}"
fi

export PYTHONPATH="$ROOT"
DATA_DIR="${PLANNER_DATA_DIR:-$ROOT/data}"
BACKUP_DIR="${PLANNER_BACKUP_DIR:-$ROOT/data/backups/migrations}"
PORT="${PLANNER_PORT:-8001}"
HOST="${PLANNER_HOST:-0.0.0.0}"

"$PYTHON_BIN" -m tools.migrate \
    --data-dir "$DATA_DIR" \
    --legacy-teachers "$ROOT/teachers.json" \
    --backup-dir "$BACKUP_DIR"

echo "Запуск веб-интерфейса на http://$HOST:$PORT"
exec "$PYTHON_BIN" -m uvicorn web.backend.main:app --host "$HOST" --port "$PORT" --workers 1
