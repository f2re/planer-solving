#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
OUTPUT="dist"
ARGS=("$@")

for ((index=0; index<${#ARGS[@]}; index++)); do
    if [[ "${ARGS[$index]}" == "--output" && $((index+1)) -lt ${#ARGS[@]} ]]; then
        OUTPUT="${ARGS[$((index+1))]}"
    elif [[ "${ARGS[$index]}" == --output=* ]]; then
        OUTPUT="${ARGS[$index]#--output=}"
    fi
done

"$PYTHON_BIN" "$ROOT/offline/build_bundle.py" --root "$ROOT" "$@"
mkdir -p "$OUTPUT"
cp "$ROOT/offline/install_from_archive.sh" "$OUTPUT/install-planner-solving.sh"
chmod 0755 "$OUTPUT/install-planner-solving.sh"
cat > "$OUTPUT/README-INSTALL.txt" <<'EOF'
PLANNER SOLVING — АВТОНОМНАЯ УСТАНОВКА

Скопируйте на целевой компьютер все файлы из этого каталога:

  planner-solving-offline-*.tar.gz
  planner-solving-offline-*.tar.gz.sha256
  install-planner-solving.sh
  README-INSTALL.txt

Установка или обновление:

  chmod +x install-planner-solving.sh
  sudo ./install-planner-solving.sh

По умолчанию приложение устанавливается в /opt/planner-solving,
создаётся служба planner-solving.service и выполняется проверка запуска.
Сеть на целевом компьютере не требуется.

Проверка после установки:

  sudo planner-solving-doctor
  systemctl status planner-solving --no-pager -l
  curl -fsS http://127.0.0.1:8001/api/health

Другой порт:

  sudo ./install-planner-solving.sh --port 8010

Явный Python:

  sudo ./install-planner-solving.sh --python /usr/bin/python3.11

Версия Python указана в имени архива: py311 означает Python 3.11.
Нужен модуль venv соответствующей версии. Все библиотеки уже включены
в wheelhouse архива и устанавливаются без Интернета.

Данные сохраняются в /opt/planner-solving/shared и не заменяются при
обновлении. При ошибке установщик автоматически возвращает прежний выпуск.

Подробности после установки:

  /opt/planner-solving/current/docs/INSTALLATION.md
  /opt/planner-solving/current/docs/TROUBLESHOOTING.md
EOF
printf 'Создан установщик: %s\n' "$OUTPUT/install-planner-solving.sh"
printf 'Создана краткая инструкция: %s\n' "$OUTPUT/README-INSTALL.txt"
