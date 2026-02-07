#!/bin/bash


# Путь к uvicorn в локальной папке пользователя (если не в PATH)
UVICORN_BIN="~/.local/bin/uvicorn"


echo "Запуск веб-интерфейса планировщика на http://0.0.0.0:8000"
exec "$UVICORN_BIN" web.backend.main:app --host 0.0.0.0 --port 8000 --workers 1
