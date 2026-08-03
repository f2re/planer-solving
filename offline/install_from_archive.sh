#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_PATH="$(readlink -f "${BASH_SOURCE[0]}" 2>/dev/null || printf '%s' "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "$SCRIPT_PATH")" && pwd -P)"
INSTALL_ROOT="/opt/planner-solving"
ARCHIVE=""
SERVICE_USER=""
PORT=""
HOST=""
WORKERS=""
KEEP_RELEASES="3"
PYTHON_HINT=""
NO_SYSTEMD=0
ASSUME_YES=1
ALLOW_UNSIGNED=0
STRICT_PYTHON=0
LIST_PYTHON=0
REPAIR=0
PYTHON_SEARCH_ROOTS=()

INVOKING_USER="${PLANNER_INVOKING_USER:-${SUDO_USER:-$(id -un)}}"
INVOKING_HOME="${PLANNER_INVOKING_HOME:-}"
if [[ -z "$INVOKING_HOME" ]]; then
    INVOKING_HOME="$(getent passwd "$INVOKING_USER" 2>/dev/null | awk -F: 'NR==1{print $6}' || true)"
fi
INVOKING_VIRTUAL_ENV="${PLANNER_INVOKING_VIRTUAL_ENV:-${VIRTUAL_ENV:-}}"
INVOKING_PYENV_ROOT="${PLANNER_INVOKING_PYENV_ROOT:-${PYENV_ROOT:-${INVOKING_HOME:+$INVOKING_HOME/.pyenv}}}"
INVOKING_PATH="${PLANNER_INVOKING_PATH:-$PATH}"

usage() {
    cat <<'EOF_HELP'
Установка или обновление Planner Solving одним сценарием.

  sudo ./install-planner-solving.sh [параметры]

Параметры:
  --archive PATH           архив planner-solving-offline-*.tar.gz
  --install-dir PATH       каталог установки, по умолчанию /opt/planner-solving
  --service-user USER      пользователь systemd-службы
  --port PORT              порт; при обновлении прежнее значение сохраняется
  --host ADDRESS           адрес прослушивания; прежнее значение сохраняется
  --workers N              число процессов; прежнее значение сохраняется
  --python VALUE           Python, venv, bin, pyenv root/version/shim или bundled
  --python-search-root DIR дополнительный каталог поиска; можно повторять
  --strict-python          не использовать резервные Python после --python
  --list-python            показать найденные варианты и ничего не менять
  --repair                 полностью пересоздать выпуск, venv и службу
  --keep-releases N        число сохранённых выпусков, по умолчанию 3
  --no-systemd             не устанавливать службу
  --ask                    запросить подтверждение
  --allow-unsigned         аварийно разрешить архив без внешнего .sha256
EOF_HELP
}

need_value() {
    [[ $# -ge 2 && -n "${2:-}" ]] || { echo "Параметр $1 требует значение." >&2; exit 2; }
}

while (($#)); do
    case "$1" in
        --archive) need_value "$@"; ARCHIVE="$2"; shift 2 ;;
        --install-dir) need_value "$@"; INSTALL_ROOT="$2"; shift 2 ;;
        --service-user) need_value "$@"; SERVICE_USER="$2"; shift 2 ;;
        --port) need_value "$@"; PORT="$2"; shift 2 ;;
        --host) need_value "$@"; HOST="$2"; shift 2 ;;
        --workers) need_value "$@"; WORKERS="$2"; shift 2 ;;
        --python) need_value "$@"; PYTHON_HINT="$2"; shift 2 ;;
        --python-search-root) need_value "$@"; PYTHON_SEARCH_ROOTS+=("$2"); shift 2 ;;
        --strict-python) STRICT_PYTHON=1; shift ;;
        --list-python) LIST_PYTHON=1; shift ;;
        --repair) REPAIR=1; shift ;;
        --keep-releases) need_value "$@"; KEEP_RELEASES="$2"; shift 2 ;;
        --no-systemd) NO_SYSTEMD=1; shift ;;
        --ask) ASSUME_YES=0; shift ;;
        --allow-unsigned) ALLOW_UNSIGNED=1; shift ;;
        --help|-h) usage; exit 0 ;;
        *) echo "Неизвестный параметр: $1" >&2; usage; exit 2 ;;
    esac
done

if [[ -n "$ARCHIVE" ]]; then
    ARCHIVE="$(readlink -f "$ARCHIVE" 2>/dev/null || printf '%s' "$ARCHIVE")"
fi

if [[ $EUID -ne 0 ]]; then
    command -v sudo >/dev/null 2>&1 || {
        echo "Для установки в /opt требуются права root или команда sudo." >&2
        exit 2
    }
    reexec=(--install-dir "$INSTALL_ROOT" --keep-releases "$KEEP_RELEASES")
    [[ -n "$ARCHIVE" ]] && reexec+=(--archive "$ARCHIVE")
    [[ -n "$SERVICE_USER" ]] && reexec+=(--service-user "$SERVICE_USER")
    [[ -n "$PORT" ]] && reexec+=(--port "$PORT")
    [[ -n "$HOST" ]] && reexec+=(--host "$HOST")
    [[ -n "$WORKERS" ]] && reexec+=(--workers "$WORKERS")
    [[ -n "$PYTHON_HINT" ]] && reexec+=(--python "$PYTHON_HINT")
    for root in "${PYTHON_SEARCH_ROOTS[@]:-}"; do [[ -n "$root" ]] && reexec+=(--python-search-root "$root"); done
    [[ $NO_SYSTEMD -eq 1 ]] && reexec+=(--no-systemd)
    [[ $ASSUME_YES -eq 0 ]] && reexec+=(--ask)
    [[ $ALLOW_UNSIGNED -eq 1 ]] && reexec+=(--allow-unsigned)
    [[ $STRICT_PYTHON -eq 1 ]] && reexec+=(--strict-python)
    [[ $LIST_PYTHON -eq 1 ]] && reexec+=(--list-python)
    [[ $REPAIR -eq 1 ]] && reexec+=(--repair)
    exec sudo env \
        PLANNER_INVOKING_USER="$INVOKING_USER" \
        PLANNER_INVOKING_HOME="$INVOKING_HOME" \
        PLANNER_INVOKING_VIRTUAL_ENV="$INVOKING_VIRTUAL_ENV" \
        PLANNER_INVOKING_PYENV_ROOT="$INVOKING_PYENV_ROOT" \
        PLANNER_INVOKING_PATH="$INVOKING_PATH" \
        bash "$SCRIPT_PATH" "${reexec[@]}"
fi

export PLANNER_INVOKING_USER="$INVOKING_USER"
export PLANNER_INVOKING_HOME="$INVOKING_HOME"
export PLANNER_INVOKING_VIRTUAL_ENV="$INVOKING_VIRTUAL_ENV"
export PLANNER_INVOKING_PYENV_ROOT="$INVOKING_PYENV_ROOT"
export PLANNER_INVOKING_PATH="$INVOKING_PATH"

if [[ -z "$ARCHIVE" ]]; then
    shopt -s nullglob
    archives=("$SCRIPT_DIR"/planner-solving-offline-*.tar.gz)
    shopt -u nullglob
    ((${#archives[@]})) || {
        echo "Рядом со сценарием не найден planner-solving-offline-*.tar.gz" >&2
        exit 2
    }
    ARCHIVE="$(ls -1t "${archives[@]}" | head -n 1)"
fi
ARCHIVE="$(readlink -f "$ARCHIVE")"
[[ -f "$ARCHIVE" ]] || { echo "Архив не найден: $ARCHIVE" >&2; exit 2; }

hash_one() {
    local path="$1"
    if command -v sha256sum >/dev/null 2>&1; then sha256sum "$path" | awk '{print $1}'
    elif command -v busybox >/dev/null 2>&1 && busybox sha256sum "$path" >/dev/null 2>&1; then busybox sha256sum "$path" | awk '{print $1}'
    elif command -v openssl >/dev/null 2>&1; then openssl dgst -sha256 "$path" | awk '{print $NF}'
    elif command -v python3 >/dev/null 2>&1; then
        python3 - "$path" <<'PY'
import hashlib, sys
h=hashlib.sha256()
with open(sys.argv[1], 'rb') as stream:
    for chunk in iter(lambda: stream.read(1024*1024), b''): h.update(chunk)
print(h.hexdigest())
PY
    else
        echo "Не найден инструмент SHA-256." >&2
        return 2
    fi
}

checksum_file="$ARCHIVE.sha256"
if [[ ! -f "$checksum_file" && $ALLOW_UNSIGNED -eq 0 ]]; then
    echo "Отсутствует обязательный файл контрольной суммы: $checksum_file" >&2
    echo "Скопируйте рядом архив, .sha256 и install-planner-solving.sh." >&2
    exit 2
fi
if [[ -f "$checksum_file" ]]; then
    expected="$(awk 'NF{print $1; exit}' "$checksum_file")"
    actual="$(hash_one "$ARCHIVE")"
    [[ -n "$expected" && "$actual" == "$expected" ]] || {
        echo "Контрольная сумма архива не совпадает." >&2
        exit 2
    }
    echo "Контрольная сумма архива подтверждена."
else
    echo "ПРЕДУПРЕЖДЕНИЕ: установка неподписанного пакета разрешена явно." >&2
fi

if [[ -z "$SERVICE_USER" && -f /etc/systemd/system/planner-solving.service ]]; then
    SERVICE_USER="$(awk -F= '$1=="User"{print $2; exit}' /etc/systemd/system/planner-solving.service)"
fi
SERVICE_USER="${SERVICE_USER:-planner-solving}"

TEMP_DIR="$(mktemp -d -t planner-solving-install-XXXXXX)"
cleanup() { rm -rf "$TEMP_DIR"; }
trap cleanup EXIT
chmod 0755 "$TEMP_DIR"

while IFS= read -r entry; do
    case "$entry" in
        /*|../*|*/../*) echo "Недопустимый путь в архиве: $entry" >&2; exit 2 ;;
    esac
done < <(tar -tzf "$ARCHIVE")

tar --no-same-owner --no-same-permissions -xzf "$ARCHIVE" -C "$TEMP_DIR"
BUNDLE_ROOT="$(find "$TEMP_DIR" -mindepth 1 -maxdepth 1 -type d -name 'planner-solving-offline-*' | head -n 1)"
[[ -n "$BUNDLE_ROOT" && -f "$BUNDLE_ROOT/install_or_update.sh" ]] || {
    echo "В архиве отсутствует install_or_update.sh" >&2
    exit 2
}
while IFS= read -r link; do
    resolved="$(readlink -f "$link" 2>/dev/null || true)"
    case "$resolved" in "$BUNDLE_ROOT"/*) ;; *) echo "Небезопасная ссылка в архиве: $link" >&2; exit 2 ;; esac
done < <(find "$BUNDLE_ROOT" -type l 2>/dev/null)

args=(--install-dir "$INSTALL_ROOT" --service-user "$SERVICE_USER" --keep-releases "$KEEP_RELEASES")
[[ -n "$PORT" ]] && args+=(--port "$PORT")
[[ -n "$HOST" ]] && args+=(--host "$HOST")
[[ -n "$WORKERS" ]] && args+=(--workers "$WORKERS")
[[ -n "$PYTHON_HINT" ]] && args+=(--python "$PYTHON_HINT")
for root in "${PYTHON_SEARCH_ROOTS[@]:-}"; do [[ -n "$root" ]] && args+=(--python-search-root "$root"); done
[[ $NO_SYSTEMD -eq 1 ]] && args+=(--no-systemd)
[[ $ASSUME_YES -eq 1 ]] && args+=(--yes)
[[ $STRICT_PYTHON -eq 1 ]] && args+=(--strict-python)
[[ $LIST_PYTHON -eq 1 ]] && args+=(--list-python)
[[ $REPAIR -eq 1 ]] && args+=(--repair)

bash "$BUNDLE_ROOT/install_or_update.sh" "${args[@]}"
[[ $LIST_PYTHON -eq 1 ]] && exit 0

echo
if [[ $NO_SYSTEMD -eq 0 && -x "$INSTALL_ROOT/state/doctor.sh" ]]; then
    "$INSTALL_ROOT/state/doctor.sh" --install-dir "$INSTALL_ROOT" --port "${PORT:-8001}" --output "$INSTALL_ROOT/state/last-doctor-report.txt" || echo "ПРЕДУПРЕЖДЕНИЕ: диагностика после установки обнаружила замечания." >&2
fi

echo
echo "Planner Solving установлен в $INSTALL_ROOT"
echo "Активный выпуск: $INSTALL_ROOT/current"
echo "Рабочий venv: $INSTALL_ROOT/current/.venv"
echo "Управляемый Python: $(cat "$INSTALL_ROOT/current/.planner-runtime" 2>/dev/null || echo не определён)"
echo "Данные: $INSTALL_ROOT/shared"
echo "Найденные Python/venv: sudo planner-solving-python"
echo "Диагностика: sudo planner-solving-doctor"
echo "Журнал: sudo journalctl -u planner-solving -n 120 --no-pager"
