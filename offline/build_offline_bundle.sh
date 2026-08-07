#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
OUTPUT="dist"
ARGS=("$@")

for ((index=0; index<${#ARGS[@]}; index++)); do
    if [[ "${ARGS[$index]}" == "--output" && $((index + 1)) -lt ${#ARGS[@]} ]]; then
        OUTPUT="${ARGS[$((index + 1))]}"
    elif [[ "${ARGS[$index]}" == --output=* ]]; then
        OUTPUT="${ARGS[$index]#--output=}"
    elif [[ "${ARGS[$index]}" == "--python" && $((index + 1)) -lt ${#ARGS[@]} ]]; then
        PYTHON_BIN="${ARGS[$((index + 1))]}"
    elif [[ "${ARGS[$index]}" == --python=* ]]; then
        PYTHON_BIN="${ARGS[$index]#--python=}"
    fi
done

"$PYTHON_BIN" "$ROOT/offline/build_bundle.py" --root "$ROOT" "$@"
mkdir -p "$OUTPUT"
cp "$ROOT/offline/install_from_archive.sh" "$OUTPUT/install-planner-solving.sh"
chmod 0755 "$OUTPUT/install-planner-solving.sh"
cat > "$OUTPUT/README-INSTALL.txt" <<'EOF_README'
БОРИС ПО ПАРАМ — АВТОНОМНАЯ УСТАНОВКА

Скопируйте на целевой компьютер все файлы из каталога dist:

  planner-solving-offline-*.tar.gz
  planner-solving-offline-*.tar.gz.sha256
  install-planner-solving.sh
  README-INSTALL.txt

Имена planner-solving в путях, службах и файлах пакета сохранены как
технические идентификаторы для совместимости существующих установок.

Обычная установка или безопасное обновление:

  chmod +x install-planner-solving.sh
  sudo ./install-planner-solving.sh

Пакет с суффиксом -runtime включает собственный CPython. Поэтому на
целевой Astra Linux не требуется заранее устанавливать Python 3.11/3.12.
Если встроенный runtime несовместим с glibc машины, установщик проверит:

  * текущий venv «Борис по парам»;
  * предыдущие выпуски и управляемые runtime;
  * активный VIRTUAL_ENV;
  * pyenv исходного пользователя, root и других пользователей;
  * каталоги venv, asdf, conda, /usr, /usr/local и /opt;
  * явно переданный файл или каталог --python.

Посмотреть все найденные варианты, ничего не меняя:

  sudo ./install-planner-solving.sh --list-python

Разрешены такие значения --python:

  /usr/bin/python3.12
  /путь/к/venv
  /путь/к/venv/bin
  /home/user/.pyenv
  /home/user/.pyenv/bin/pyenv
  /home/user/.pyenv/versions/3.12.12
  /home/user/.pyenv/shims/python3.12
  bundled

Если pyenv-Python не видит libpython*.so, установщик автоматически ищет
библиотеку рядом с версией pyenv и запускает его с правильным
LD_LIBRARY_PATH. После этого Python переносится в /opt и systemd больше не
зависит от /home, pyenv, .bashrc или пользовательского PATH.

Восстановление установленной версии:

  sudo ./install-planner-solving.sh --repair

После установки:

  sudo planner-solving-python
  sudo planner-solving-doctor
  systemctl status planner-solving --no-pager -l
  curl -fsS http://127.0.0.1:8001/api/health

Каталоги:

  /opt/planner-solving/current        активный выпуск
  /opt/planner-solving/current/.venv  рабочий venv
  /opt/planner-solving/runtime        управляемые Python runtime
  /opt/planner-solving/shared         постоянные данные

При ошибке обновления код, данные, unit-файл и прежняя служба возвращаются
автоматически.
EOF_README
printf 'Создан установщик: %s\n' "$OUTPUT/install-planner-solving.sh"
printf 'Создана краткая инструкция: %s\n' "$OUTPUT/README-INSTALL.txt"
