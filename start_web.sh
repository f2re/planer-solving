#!/bin/bash

# Ensure we are in the project root
cd "$(dirname "$0")"

# Set up pyenv environment for the script
export PYENV_ROOT="$HOME/.pyenv"
export PATH="$PYENV_ROOT/bin:$PATH"
eval "$(pyenv init -)"

echo "Запуск веб-интерфейса планировщика на http://0.0.0.0:8000"
# Use python -m uvicorn to ensure we use the version from the current pyenv environment
python -m uvicorn web.backend.main:app --host 0.0.0.0 --port 8000 --workers 1