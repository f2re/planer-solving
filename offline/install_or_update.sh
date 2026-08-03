#!/usr/bin/env bash
set -Eeuo pipefail

BUNDLE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
source "$BUNDLE_ROOT/common.sh"
source "$BUNDLE_ROOT/python_discovery.sh"

INSTALL_ROOT="/opt/planner-solving"
LEGACY_DIR=""
SERVICE_USER="planner-solving"
PORT="8001"
HOST="0.0.0.0"
WORKERS="1"
PYTHON_HINT="${PYTHON_BIN:-${PLANNER_PYTHON:-}}"
NO_SYSTEMD=0
ASSUME_YES=0
KEEP_RELEASES=3
LIST_PYTHON=0
STRICT_PYTHON=0
REPAIR=0
PYTHON_SEARCH_ROOTS=()
SERVICE_USER_SET=0
PORT_SET=0
HOST_SET=0
WORKERS_SET=0

usage() {
    cat <<'EOF_HELP'
Установка, обновление или восстановление Planner Solving.

  sudo ./install_or_update.sh [параметры]

Параметры:
  --install-dir PATH       каталог установки, по умолчанию /opt/planner-solving
  --legacy-dir PATH        прежняя плоская установка для переноса данных
  --service-user USER      системный пользователь, по умолчанию planner-solving
  --port PORT              порт, по умолчанию 8001; при обновлении сохраняется
  --host ADDRESS           адрес прослушивания; при обновлении сохраняется
  --workers N              число процессов Uvicorn; при обновлении сохраняется
  --python VALUE           Python, venv, bin, pyenv root/version/shim или bundled
  --python-search-root DIR дополнительный каталог поиска; можно повторять
  --strict-python          не использовать резервные варианты после --python
  --list-python            показать все найденные Python/venv и ничего не менять
  --repair                 переустановить выпуск, venv и systemd, сохранив данные
  --keep-releases N        число сохранённых выпусков, по умолчанию 3
  --no-systemd             не устанавливать и не запускать службу
  --yes                    не запрашивать подтверждение
EOF_HELP
}

need_value() {
    [[ $# -ge 2 && -n "${2:-}" ]] || die "Параметр $1 требует значение."
}

while (($#)); do
    case "$1" in
        --install-dir) need_value "$@"; INSTALL_ROOT="$2"; shift 2 ;;
        --legacy-dir) need_value "$@"; LEGACY_DIR="$2"; shift 2 ;;
        --service-user) need_value "$@"; SERVICE_USER="$2"; SERVICE_USER_SET=1; shift 2 ;;
        --port) need_value "$@"; PORT="$2"; PORT_SET=1; shift 2 ;;
        --host) need_value "$@"; HOST="$2"; HOST_SET=1; shift 2 ;;
        --workers) need_value "$@"; WORKERS="$2"; WORKERS_SET=1; shift 2 ;;
        --python) need_value "$@"; PYTHON_HINT="$2"; shift 2 ;;
        --python-search-root) need_value "$@"; PYTHON_SEARCH_ROOTS+=("$2"); shift 2 ;;
        --strict-python) STRICT_PYTHON=1; shift ;;
        --list-python) LIST_PYTHON=1; shift ;;
        --repair) REPAIR=1; shift ;;
        --keep-releases) need_value "$@"; KEEP_RELEASES="$2"; shift 2 ;;
        --no-systemd) NO_SYSTEMD=1; shift ;;
        --yes|-y) ASSUME_YES=1; shift ;;
        --help|-h) usage; exit 0 ;;
        *) die "Неизвестный параметр: $1" ;;
    esac
done

EXISTING_ENV=/etc/default/planner-solving
if [[ -f "$EXISTING_ENV" ]]; then
    [[ $PORT_SET -eq 1 ]] || PORT="$(read_assignment "$EXISTING_ENV" PLANNER_PORT)" || true
    [[ $HOST_SET -eq 1 ]] || HOST="$(read_assignment "$EXISTING_ENV" PLANNER_HOST)" || true
    [[ $WORKERS_SET -eq 1 ]] || WORKERS="$(read_assignment "$EXISTING_ENV" PLANNER_WORKERS)" || true
fi
PORT="${PORT:-8001}"
HOST="${HOST:-0.0.0.0}"
WORKERS="${WORKERS:-1}"
if [[ $SERVICE_USER_SET -eq 0 && -f /etc/systemd/system/planner-solving.service ]]; then
    existing_user="$(awk -F= '$1=="User"{print $2; exit}' /etc/systemd/system/planner-solving.service)"
    [[ -n "$existing_user" ]] && SERVICE_USER="$existing_user"
fi

[[ "$PORT" =~ ^[0-9]+$ ]] && ((PORT >= 1 && PORT <= 65535)) || die "Некорректный порт: $PORT"
[[ "$WORKERS" =~ ^[0-9]+$ ]] && ((WORKERS >= 1 && WORKERS <= 16)) || die "Некорректное число процессов: $WORKERS"
[[ "$KEEP_RELEASES" =~ ^[0-9]+$ ]] && ((KEEP_RELEASES >= 2 && KEEP_RELEASES <= 20)) || die "Некорректное число хранимых выпусков: $KEEP_RELEASES"

if [[ $EUID -ne 0 && "$INSTALL_ROOT" == /opt/* ]]; then
    die "Установка в $INSTALL_ROOT требует root. Запустите внешний install-planner-solving.sh через sudo."
fi
if [[ $NO_SYSTEMD -eq 0 && $EUID -ne 0 ]]; then
    warn "Без root systemd недоступен; включён режим --no-systemd."
    NO_SYSTEMD=1
fi
if [[ $NO_SYSTEMD -eq 0 ]] && ! systemd_available; then
    warn "systemd не является системой инициализации этого окружения; служба не устанавливается."
    NO_SYSTEMD=1
fi

require_command tar
require_command sed
require_command find
[[ -f "$BUNDLE_ROOT/manifest.json" ]] || die "manifest.json не найден. Запускайте сценарий из распакованного автономного пакета."
[[ -d "$BUNDLE_ROOT/wheelhouse" ]] || die "wheelhouse не найден в автономном пакете."
[[ -x "$BUNDLE_ROOT/verify_bundle.sh" ]] || die "verify_bundle.sh отсутствует в пакете."
[[ -f "$BUNDLE_ROOT/python_runtime.py" ]] || die "python_runtime.py отсутствует в пакете."
[[ -f "$BUNDLE_ROOT/python_discovery.sh" ]] || die "python_discovery.sh отсутствует в пакете."
"$BUNDLE_ROOT/verify_bundle.sh" --quiet "$BUNDLE_ROOT"

MANIFEST_COMPACT="$(tr -d '\n\r' < "$BUNDLE_ROOT/manifest.json")"
PYTHON_OBJECT="$(printf '%s' "$MANIFEST_COMPACT" | sed -n 's/.*"python"[[:space:]]*:[[:space:]]*{\([^}]*\)}.*/\1/p')"
manifest_value() {
    local key="$1"
    printf '%s' "$MANIFEST_COMPACT" | sed -n 's/.*"'"$key"'"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p'
}
python_manifest_value() {
    local key="$1"
    printf '%s' "$PYTHON_OBJECT" | sed -n 's/.*"'"$key"'"[[:space:]]*:[[:space:]]*\([0-9][0-9]*\).*/\1/p'
}
EXPECTED_MAJOR="$(python_manifest_value major)"
EXPECTED_MINOR="$(python_manifest_value minor)"
VERSION="$(manifest_value app_version)"
EXPECTED_ARCH="$(manifest_value architecture)"
EXPECTED_SYSTEM="$(manifest_value platform)"
[[ -n "$VERSION" && -n "$EXPECTED_MAJOR" && -n "$EXPECTED_MINOR" ]] || die "manifest.json повреждён или имеет неизвестный формат."

if ((${#PYTHON_SEARCH_ROOTS[@]})); then
    joined="$(IFS=:; printf '%s' "${PYTHON_SEARCH_ROOTS[*]}")"
    export PLANNER_PYTHON_SEARCH_ROOTS="${PLANNER_PYTHON_SEARCH_ROOTS:+$PLANNER_PYTHON_SEARCH_ROOTS:}$joined"
fi
EMBEDDED_PYTHON=""
[[ -x "$BUNDLE_ROOT/python-runtime/python" ]] && EMBEDDED_PYTHON="$BUNDLE_ROOT/python-runtime/python"
if [[ "$PYTHON_HINT" == bundled || "$PYTHON_HINT" == embedded ]]; then
    [[ -n "$EMBEDDED_PYTHON" ]] || die "В этом пакете нет встроенного Python runtime."
    PYTHON_HINT="$EMBEDDED_PYTHON"
    STRICT_PYTHON=1
fi

if [[ $LIST_PYTHON -eq 1 ]]; then
    echo "Требование пакета: CPython ${EXPECTED_MAJOR}.${EXPECTED_MINOR}; архитектура ${EXPECTED_ARCH:-не указана}"
    resolve_python_runtime "$PYTHON_HINT" "$EXPECTED_MAJOR" "$EXPECTED_MINOR" "$INSTALL_ROOT" "$SERVICE_USER" "$EMBEDDED_PYTHON" 1 "$STRICT_PYTHON" || exit 2
    exit 0
fi

mkdir -p "$INSTALL_ROOT/state"
acquire_install_lock "$INSTALL_ROOT/state"
INSTALL_FINISHED=0
CRITICAL_STARTED=0
ROLLBACK_RUNNING=0
PARTIAL_RELEASE=""
EXPORT_WORK=""
BACKUP=""
PREVIOUS=""
OLD_ACTIVE_UNITS=()
UNIT_BACKUP=""
DEFAULT_BACKUP=""
HAD_UNIT=0
HAD_DEFAULT=0

rollback_installation() {
    [[ $ROLLBACK_RUNNING -eq 0 ]] || return 0
    ROLLBACK_RUNNING=1
    warn "Установка не завершена; возвращается прежнее состояние."
    if [[ $NO_SYSTEMD -eq 0 ]]; then
        service_stop || true
    fi
    if [[ -n "$PREVIOUS" && -d "$PREVIOUS" ]]; then
        atomic_link "$PREVIOUS" "$INSTALL_ROOT/current" || true
    elif [[ -L "$INSTALL_ROOT/current" ]]; then
        rm -f "$INSTALL_ROOT/current"
    fi
    if [[ -n "$BACKUP" && -f "$BACKUP" ]]; then
        restore_shared "$INSTALL_ROOT/shared" "$BACKUP" || true
        if [[ -n "${SERVICE_GROUP:-}" ]]; then
            set_shared_owner "$INSTALL_ROOT/shared" "$SERVICE_USER:$SERVICE_GROUP" || true
        fi
    fi
    if [[ $NO_SYSTEMD -eq 0 ]]; then
        if [[ $HAD_UNIT -eq 1 && -f "$UNIT_BACKUP" ]]; then
            cp -a "$UNIT_BACKUP" /etc/systemd/system/planner-solving.service || true
        elif [[ $HAD_UNIT -eq 0 ]]; then
            rm -f /etc/systemd/system/planner-solving.service
        fi
        if [[ $HAD_DEFAULT -eq 1 && -f "$DEFAULT_BACKUP" ]]; then
            cp -a "$DEFAULT_BACKUP" /etc/default/planner-solving || true
        elif [[ $HAD_DEFAULT -eq 0 ]]; then
            rm -f /etc/default/planner-solving
        fi
        systemctl daemon-reload >/dev/null 2>&1 || true
        for unit in "${OLD_ACTIVE_UNITS[@]:-}"; do
            [[ -n "$unit" ]] && systemctl start "$unit" >/dev/null 2>&1 || true
        done
    fi
}

cleanup_installation() {
    local code=$?
    trap - EXIT
    if [[ $code -ne 0 && $INSTALL_FINISHED -eq 0 && $CRITICAL_STARTED -eq 1 ]]; then
        rollback_installation
    fi
    [[ -n "$EXPORT_WORK" ]] && rm -rf "$EXPORT_WORK" 2>/dev/null || true
    if [[ $INSTALL_FINISHED -eq 0 && -n "$PARTIAL_RELEASE" && -d "$PARTIAL_RELEASE" ]]; then
        rm -rf "$PARTIAL_RELEASE" 2>/dev/null || true
    fi
    [[ -n "$UNIT_BACKUP" ]] && rm -f "$UNIT_BACKUP" 2>/dev/null || true
    [[ -n "$DEFAULT_BACKUP" ]] && rm -f "$DEFAULT_BACKUP" 2>/dev/null || true
    release_install_lock
    exit "$code"
}
trap cleanup_installation EXIT

if [[ $NO_SYSTEMD -eq 0 ]]; then
    if ! id "$SERVICE_USER" >/dev/null 2>&1; then
        NOLOGIN_SHELL="$(command -v nologin 2>/dev/null || command -v false 2>/dev/null || echo /bin/false)"
        if command -v useradd >/dev/null 2>&1; then
            useradd --system --user-group --home-dir "$INSTALL_ROOT/shared/home" --shell "$NOLOGIN_SHELL" "$SERVICE_USER"
        elif command -v adduser >/dev/null 2>&1; then
            adduser --system --group --home "$INSTALL_ROOT/shared/home" --no-create-home "$SERVICE_USER"
        else
            die "Не удалось создать системного пользователя $SERVICE_USER."
        fi
    fi
    SERVICE_GROUP="$(id -gn "$SERVICE_USER")"
else
    SERVICE_USER="$(id -un)"
    SERVICE_GROUP="$(id -gn)"
fi

if ! resolve_python_runtime "$PYTHON_HINT" "$EXPECTED_MAJOR" "$EXPECTED_MINOR" "$INSTALL_ROOT" "$SERVICE_USER" "$EMBEDDED_PYTHON" 0 "$STRICT_PYTHON"; then
    echo >&2
    echo "Проверенные варианты Python и venv:" >&2
    python_print_attempts >&2
    echo >&2
    die "Не найден рабочий CPython ${EXPECTED_MAJOR}.${EXPECTED_MINOR}. Параметр --python принимает исполняемый файл, корень venv, каталог bin, корень/версию pyenv, shim или значение bundled."
fi
if [[ -n "$PYTHON_HINT" && "$PYTHON_SELECTED_SOURCE" != "параметр --python"* ]]; then
    warn "Указанный --python не подошёл; выбран резервный вариант: $PYTHON_SELECTED_SOURCE"
fi
log "Исходный Python: $PYTHON_SELECTED"
log "Источник Python: $PYTHON_SELECTED_SOURCE"
log "Версия/архитектура: $PYTHON_SELECTED_VERSION / $PYTHON_SELECTED_ARCH"
[[ "$PYTHON_SELECTED_IS_VENV" == 1 ]] && log "Найдено исходное виртуальное окружение: $(cd "$(dirname "$PYTHON_SELECTED")/.." 2>/dev/null && pwd -P || true)"
[[ -n "$PYTHON_SELECTED_RUN_USER" ]] && log "Проверка исходного Python выполнена от имени: $PYTHON_SELECTED_RUN_USER"
[[ -n "$PYTHON_SELECTED_LD_LIBRARY_PATH" ]] && log "Восстановлен путь к libpython: $PYTHON_SELECTED_LD_LIBRARY_PATH"
[[ -z "$EXPECTED_ARCH" || "$PYTHON_SELECTED_ARCH" == "$EXPECTED_ARCH" ]] || die "Архитектура Python $PYTHON_SELECTED_ARCH не совпадает с пакетом $EXPECTED_ARCH."

mkdir -p "$INSTALL_ROOT"
INSTALL_ROOT="$(cd "$INSTALL_ROOT" && pwd -P)"
RELEASES="$INSTALL_ROOT/releases"
RUNTIMES="$INSTALL_ROOT/runtime"
SHARED="$INSTALL_ROOT/shared"
STATE="$INSTALL_ROOT/state"
BACKUPS="$SHARED/backups"
mkdir -p "$RELEASES" "$RUNTIMES" "$SHARED/data" "$SHARED/input" "$SHARED/output" "$SHARED/home" "$SHARED/cache" "$BACKUPS" "$STATE"
chmod 0755 "$INSTALL_ROOT" "$RELEASES" "$RUNTIMES" "$STATE"
[[ -f "$SHARED/teachers.json" ]] || printf '[]\n' > "$SHARED/teachers.json"
[[ -f "$SHARED/config.json" ]] || printf '{}\n' > "$SHARED/config.json"
set_shared_owner "$SHARED" "$SERVICE_USER:$SERVICE_GROUP"

if [[ -z "$LEGACY_DIR" && ! -e "$INSTALL_ROOT/current" ]]; then
    if [[ -f "$INSTALL_ROOT/VERSION" || -d "$INSTALL_ROOT/data" || -f "$INSTALL_ROOT/teachers.json" ]]; then
        LEGACY_DIR="$INSTALL_ROOT"
        log "Обнаружена прежняя плоская установка: $LEGACY_DIR"
    fi
fi

prepare_managed_runtime() {
    local selected_real embedded_real selected_runtime="" source_dir="" runtime_dir=""
    local runtime_id runtime_version runtime_arch target script_copy

    selected_real="$(canonical_path "$PYTHON_SELECTED")"
    embedded_real="${EMBEDDED_PYTHON:+$(canonical_path "$EMBEDDED_PYTHON")}"

    if [[ "$selected_real" == "$RUNTIMES"/*/python ]]; then
        selected_runtime="$(dirname "$selected_real")"
        if [[ -x "$selected_runtime/python" && -f "$selected_runtime/runtime.json" ]]; then
            MANAGED_RUNTIME="$selected_runtime"
            MANAGED_PYTHON="$selected_runtime/python"
            return 0
        fi
    fi

    EXPORT_WORK="$(mktemp -d -t planner-python-runtime-XXXXXX)"
    runtime_dir="$EXPORT_WORK/runtime"
    if [[ -n "$embedded_real" && "$selected_real" == "$embedded_real" ]]; then
        source_dir="$BUNDLE_ROOT/python-runtime"
        cp -a "$source_dir" "$runtime_dir"
    else
        script_copy="$EXPORT_WORK/python_runtime.py"
        cp "$BUNDLE_ROOT/python_runtime.py" "$script_copy"
        chmod 0755 "$script_copy"
        if [[ -n "$PYTHON_SELECTED_RUN_USER" && $EUID -eq 0 && "$PYTHON_SELECTED_RUN_USER" != root ]]; then
            chown -R "$PYTHON_SELECTED_RUN_USER" "$EXPORT_WORK"
        fi
        python_exec_selected "$script_copy" export --destination "$runtime_dir" >/dev/null
    fi
    [[ -x "$runtime_dir/python" && -f "$runtime_dir/runtime.json" ]] || die "Не удалось подготовить управляемый Python runtime."
    if find "$runtime_dir" -type l -print -quit | grep -q .; then
        die "Подготовленный runtime содержит символические ссылки и не может быть безопасно установлен."
    fi
    runtime_id="$(sed -n 's/^[[:space:]]*"runtime_id"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$runtime_dir/runtime.json" | head -n1)"
    runtime_version="$(sed -n 's/^[[:space:]]*"version"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$runtime_dir/runtime.json" | head -n1)"
    runtime_arch="$(sed -n 's/^[[:space:]]*"architecture"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$runtime_dir/runtime.json" | head -n1)"
    [[ -n "$runtime_id" ]] || runtime_id="$(hash_file "$runtime_dir/prefix/bin/python${EXPECTED_MAJOR}.${EXPECTED_MINOR}" | cut -c1-16)"
    runtime_version="${runtime_version:-$PYTHON_SELECTED_VERSION}"
    runtime_arch="${runtime_arch:-$PYTHON_SELECTED_ARCH}"
    target="$RUNTIMES/python-${runtime_version}-${runtime_arch}-${runtime_id}"

    if [[ -x "$target/python" ]] && "$target/python" -c 'import ensurepip,ssl,sqlite3,sys,venv; raise SystemExit(0)' >/dev/null 2>&1; then
        rm -rf "$runtime_dir"
    else
        rm -rf "$target"
        mv "$runtime_dir" "$target"
    fi
    chown -R root:"$SERVICE_GROUP" "$target" 2>/dev/null || true
    chmod -R a+rX "$target"
    "$target/python" -c 'import ensurepip,platform,ssl,sqlite3,sys,venv; print(sys.version.split()[0], platform.machine())' >/dev/null || die "Скопированный runtime не запускается на этой машине: $target"
    MANAGED_RUNTIME="$target"
    MANAGED_PYTHON="$target/python"
}
MANAGED_RUNTIME=""
MANAGED_PYTHON=""
prepare_managed_runtime
log "Управляемый Python runtime: $MANAGED_RUNTIME"
log "Исполняемый файл runtime: $MANAGED_PYTHON"

"$MANAGED_PYTHON" "$BUNDLE_ROOT/verify_bundle.py" "$BUNDLE_ROOT" >/dev/null || die "Внутренний manifest автономного пакета не прошёл проверку."

if [[ -n "$LEGACY_DIR" ]]; then
    LEGACY_DIR="$(cd "$LEGACY_DIR" && pwd -P)"
    log "Перенос данных из прежней установки: $LEGACY_DIR"
    if [[ ! -f "$SHARED/data/workspaces.json" && -f "$LEGACY_DIR/data/workspaces.json" ]]; then
        cp -a "$LEGACY_DIR/data/workspaces.json" "$SHARED/data/workspaces.json"
    fi
    if [[ -s "$LEGACY_DIR/teachers.json" && $(cat "$SHARED/teachers.json") == "[]" ]]; then
        cp -a "$LEGACY_DIR/teachers.json" "$SHARED/teachers.json"
    fi
    [[ -f "$LEGACY_DIR/config.json" ]] && cp -a "$LEGACY_DIR/config.json" "$SHARED/config.json"
    [[ -d "$LEGACY_DIR/output" ]] && cp -an "$LEGACY_DIR/output/." "$SHARED/output/" 2>/dev/null || true
    set_shared_owner "$SHARED" "$SERVICE_USER:$SERVICE_GROUP"
fi

STAMP="$(date +%Y%m%d-%H%M%S)"
RELEASE="$RELEASES/${VERSION}-${STAMP}"
PARTIAL_RELEASE="$RELEASE"
[[ ! -e "$RELEASE" ]] || die "Каталог выпуска уже существует: $RELEASE"
log "Подготовка выпуска: $RELEASE"
mkdir -p "$RELEASE"
cp -a "$BUNDLE_ROOT/app/." "$RELEASE/"
cp -a "$BUNDLE_ROOT/manifest.json" "$RELEASE/.offline-manifest.json"
printf '%s\n' "$MANAGED_RUNTIME" > "$RELEASE/.planner-runtime"

configure_venv_launcher() {
    local venv="$1" runtime="$2" xy="${EXPECTED_MAJOR}.${EXPECTED_MINOR}" source_bin executable first_line
    source_bin="$venv/bin/python$xy"
    [[ -x "$source_bin" ]] || source_bin="$venv/bin/python3"
    [[ -x "$source_bin" ]] || source_bin="$venv/bin/python"
    [[ -x "$source_bin" ]] || die "В созданном venv отсутствует Python."
    cp -L "$source_bin" "$venv/bin/python.real"
    chmod 0755 "$venv/bin/python.real"
    rm -f "$venv/bin/python" "$venv/bin/python3" "$venv/bin/python$xy"
    printf '%s\n' "$runtime" > "$venv/.planner-runtime"
    cat > "$venv/bin/python" <<'EOF_LAUNCHER'
#!/bin/sh
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
VENV=$(CDPATH= cd -- "$HERE/.." && pwd)
RUNTIME=$(cat "$VENV/.planner-runtime")
export LD_LIBRARY_PATH="$RUNTIME/prefix/lib:$RUNTIME/prefix/lib64${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export PYTHONNOUSERSITE=1
export PYTHONDONTWRITEBYTECODE=1
unset PYTHONHOME
exec "$HERE/python.real" "$@"
EOF_LAUNCHER
    chmod 0755 "$venv/bin/python"
    ln -s python "$venv/bin/python3"
    ln -s python "$venv/bin/python$xy"

    for executable in "$venv/bin/"*; do
        [[ -f "$executable" && "$executable" != "$venv/bin/python.real" ]] || continue
        IFS= read -r first_line < "$executable" || true
        if [[ "$first_line" == "#!$venv/bin/python.real"* ]]; then
            tail -n +2 "$executable" > "$executable.body"
            { printf '#!%s\n' "$venv/bin/python"; cat "$executable.body"; } > "$executable.new"
            chmod --reference="$executable" "$executable.new" 2>/dev/null || chmod 0755 "$executable.new"
            mv "$executable.new" "$executable"
            rm -f "$executable.body"
        fi
    done
}

log "Создание нового изолированного venv выпуска"
"$MANAGED_PYTHON" -m venv --copies "$RELEASE/.venv" || die "Управляемый Python не смог создать venv."
RAW_VENV_PYTHON="$RELEASE/.venv/bin/python"
[[ -x "$RAW_VENV_PYTHON" ]] || die "В новом venv отсутствует Python: $RAW_VENV_PYTHON"
env -u PYTHONHOME PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 LD_LIBRARY_PATH="$MANAGED_RUNTIME/prefix/lib:$MANAGED_RUNTIME/prefix/lib64${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" "$RAW_VENV_PYTHON" -m pip install --disable-pip-version-check --no-cache-dir --no-index --find-links "$BUNDLE_ROOT/wheelhouse" --requirement "$RELEASE/requirements-runtime.txt" || die "Зависимости не установлены из wheelhouse. Проверьте версию Python, архитектуру и полноту пакета."
configure_venv_launcher "$RELEASE/.venv" "$MANAGED_RUNTIME"
VENV_PYTHON="$RELEASE/.venv/bin/python"

SITE_PACKAGES="$($VENV_PYTHON - <<'PY_SITE'
import site
paths = site.getsitepackages()
if not paths:
    raise SystemExit('site-packages не найден')
print(paths[0])
PY_SITE
)"
printf '%s\n' "$RELEASE" > "$SITE_PACKAGES/planner-solving-app.pth"
chmod 0644 "$SITE_PACKAGES/planner-solving-app.pth"

rm -rf "$RELEASE/data" "$RELEASE/input" "$RELEASE/output"
ln -s "$SHARED/data" "$RELEASE/data"
ln -s "$SHARED/input" "$RELEASE/input"
ln -s "$SHARED/output" "$RELEASE/output"
rm -f "$RELEASE/teachers.json" "$RELEASE/config.json"
ln -s "$SHARED/teachers.json" "$RELEASE/teachers.json"
ln -s "$SHARED/config.json" "$RELEASE/config.json"
chown -R root:"$SERVICE_GROUP" "$RELEASE" 2>/dev/null || true
chmod -R a+rX "$RELEASE"

run_as_user "$SERVICE_USER" env PYTHONPATH="$RELEASE" PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 PLANNER_BASE_DIR="$RELEASE" "$VENV_PYTHON" -m tools.service_preflight --app-root "$RELEASE" --shared-dir "$SHARED" || die "Пользователь $SERVICE_USER не может использовать новый venv: $RELEASE/.venv"

PREVIOUS="$(readlink -f "$INSTALL_ROOT/current" 2>/dev/null || true)"
if [[ $NO_SYSTEMD -eq 0 ]]; then
    for unit in planner-solving.service planner-web.service; do
        systemctl is-active --quiet "$unit" 2>/dev/null && OLD_ACTIVE_UNITS+=("$unit") || true
    done
    if [[ -f /etc/systemd/system/planner-solving.service ]]; then
        HAD_UNIT=1
        UNIT_BACKUP="$(mktemp -t planner-solving-unit-XXXXXX)"
        cp -a /etc/systemd/system/planner-solving.service "$UNIT_BACKUP"
    fi
    if [[ -f /etc/default/planner-solving ]]; then
        HAD_DEFAULT=1
        DEFAULT_BACKUP="$(mktemp -t planner-solving-default-XXXXXX)"
        cp -a /etc/default/planner-solving "$DEFAULT_BACKUP"
    fi
fi

if [[ $ASSUME_YES -eq 0 ]]; then
    echo "Будет установлен Planner Solving $VERSION"
    echo "Каталог: $INSTALL_ROOT"
    echo "Новый venv: $RELEASE/.venv"
    echo "Python runtime: $MANAGED_RUNTIME"
    [[ -n "$PREVIOUS" ]] && echo "Текущий выпуск: $PREVIOUS"
    printf 'Продолжить? [y/N] '
    read -r answer
    [[ "$answer" =~ ^[YyДд]$ ]] || exit 0
fi

CRITICAL_STARTED=1
[[ $NO_SYSTEMD -eq 1 ]] || service_stop
if ! port_available "$VENV_PYTHON" "$HOST" "$PORT"; then
    die "Порт $HOST:$PORT занят другим процессом. Освободите порт или задайте --port."
fi
BACKUP="$(backup_shared "$SHARED" "$BACKUPS" "before-${VERSION}")"
log "Резервная копия данных: $BACKUP"
set_shared_owner "$SHARED" "$SERVICE_USER:$SERVICE_GROUP"

run_as_user "$SERVICE_USER" env PYTHONPATH="$RELEASE" PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 PLANNER_BASE_DIR="$RELEASE" "$VENV_PYTHON" -m tools.migrate --data-dir "$SHARED/data" --legacy-teachers "$SHARED/teachers.json" --backup-dir "$BACKUPS/migrations"
run_as_user "$SERVICE_USER" env PYTHONPATH="$RELEASE" PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 PLANNER_BASE_DIR="$RELEASE" "$VENV_PYTHON" -m tools.healthcheck --app-root "$RELEASE" --data-dir "$SHARED/data"

atomic_link "$RELEASE" "$INSTALL_ROOT/current"
install -m 0755 "$BUNDLE_ROOT/runtime.sh" "$STATE/run-service.sh"
install -m 0755 "$BUNDLE_ROOT/doctor.sh" "$STATE/doctor.sh"
install -m 0644 "$BUNDLE_ROOT/common.sh" "$STATE/common.sh"
install -m 0755 "$BUNDLE_ROOT/python_discovery.sh" "$STATE/python-discovery.sh"

cat > "$STATE/run.sh" <<EOF_RUN
#!/usr/bin/env bash
set -Eeuo pipefail
export PLANNER_INSTALL_ROOT="$INSTALL_ROOT"
export PLANNER_HOST="$HOST"
export PLANNER_PORT="$PORT"
export PLANNER_WORKERS="$WORKERS"
exec "$STATE/run-service.sh" "\$@"
EOF_RUN
chmod 0755 "$STATE/run.sh"

cat > "$STATE/admin.sh" <<EOF_ADMIN
#!/usr/bin/env bash
set -Eeuo pipefail
CURRENT="\$(readlink -f "$INSTALL_ROOT/current")"
cd "\$CURRENT"
export PYTHONPATH="\$CURRENT"
export PYTHONNOUSERSITE=1
unset PYTHONHOME
exec "\$CURRENT/.venv/bin/python" -m tools.user_admin \
  --data-dir "$SHARED/data" --legacy-teachers "$SHARED/teachers.json" "\$@"
EOF_ADMIN
chmod 0755 "$STATE/admin.sh"

cat > "$STATE/python-info.sh" <<EOF_INFO
#!/usr/bin/env bash
set -Eeuo pipefail
source "$STATE/common.sh"
source "$STATE/python-discovery.sh"
CURRENT="\$(readlink -f "$INSTALL_ROOT/current")"
MAJOR="$EXPECTED_MAJOR"
MINOR="$EXPECTED_MINOR"
SERVICE_USER="$SERVICE_USER"
export PLANNER_INVOKING_USER="\${SUDO_USER:-\${USER:-}}"
export PLANNER_INVOKING_HOME="\$(getent passwd "\${PLANNER_INVOKING_USER:-root}" 2>/dev/null | awk -F: 'NR==1{print \$6}')"
echo "Активный выпуск: \$CURRENT"
echo "Рабочий venv: \$CURRENT/.venv"
echo "Управляемый runtime: \$(cat "\$CURRENT/.planner-runtime" 2>/dev/null || true)"
echo "Кандидаты CPython \$MAJOR.\$MINOR:"
resolve_python_runtime "" "\$MAJOR" "\$MINOR" "$INSTALL_ROOT" "\$SERVICE_USER" "" 1 0
EOF_INFO
chmod 0755 "$STATE/python-info.sh"

mkdir -p /usr/local/bin 2>/dev/null || true
ln -sfn "$STATE/admin.sh" /usr/local/bin/planner-solving-admin 2>/dev/null || true
ln -sfn "$STATE/doctor.sh" /usr/local/bin/planner-solving-doctor 2>/dev/null || true
ln -sfn "$STATE/python-info.sh" /usr/local/bin/planner-solving-python 2>/dev/null || true

if [[ $NO_SYSTEMD -eq 0 ]]; then
    mkdir -p /etc/default /etc/systemd/system
    cat > /etc/default/planner-solving <<EOF_ENV
PLANNER_INSTALL_ROOT="$INSTALL_ROOT"
PLANNER_HOST="$HOST"
PLANNER_PORT="$PORT"
PLANNER_WORKERS="$WORKERS"
PLANNER_HOME="$SHARED/home"
PLANNER_CACHE_DIR="$SHARED/cache"
EOF_ENV
    chmod 0644 /etc/default/planner-solving

    cat > /etc/systemd/system/planner-solving.service <<EOF_UNIT
[Unit]
Description=Planner Solving
Documentation=file://$INSTALL_ROOT/current/docs/TROUBLESHOOTING.md
Wants=network-online.target
After=network-online.target local-fs.target
ConditionPathExists=$INSTALL_ROOT/current/.venv/bin/python

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_GROUP
WorkingDirectory=$INSTALL_ROOT/current
EnvironmentFile=-/etc/default/planner-solving
Environment=PYTHONDONTWRITEBYTECODE=1
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONNOUSERSITE=1
ExecStartPre=$STATE/run-service.sh --check
ExecStart=$STATE/run-service.sh
Restart=on-failure
RestartSec=5
TimeoutStartSec=120
TimeoutStopSec=30
KillSignal=SIGINT
UMask=0027
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=read-only
ReadWritePaths=$SHARED

[Install]
WantedBy=multi-user.target
EOF_UNIT
    if command -v systemd-analyze >/dev/null 2>&1; then
        systemd-analyze verify /etc/systemd/system/planner-solving.service || warn "systemd-analyze сообщил о несовместимой директиве; фактический запуск будет проверен ниже."
    fi
    service_start || {
        systemctl status planner-solving.service --no-pager -l >&2 2>/dev/null || true
        journalctl -u planner-solving.service -n 120 --no-pager >&2 2>/dev/null || true
        die "systemd не смог запустить planner-solving.service."
    }
    if ! wait_for_health "$VENV_PYTHON" "$PORT" 75; then
        journalctl -u planner-solving.service -n 120 --no-pager >&2 2>/dev/null || true
        die "Служба запущена, но /api/health не отвечает."
    fi
    systemctl disable planner-web.service >/dev/null 2>&1 || true
fi

write_update_state "$STATE/last-update.json" "$PREVIOUS" "$RELEASE" "$BACKUP" "$VERSION" "$VENV_PYTHON"

mapfile -t OLD_RELEASES < <(find "$RELEASES" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' | sort -nr | awk '{print $2}')
for ((index=KEEP_RELEASES; index<${#OLD_RELEASES[@]}; index++)); do
    candidate="${OLD_RELEASES[$index]}"
    [[ "$candidate" == "$RELEASE" || "$candidate" == "$PREVIOUS" ]] && continue
    rm -rf "$candidate"
done

INSTALL_FINISHED=1
PARTIAL_RELEASE=""
if [[ $REPAIR -eq 1 ]]; then
    log "Восстановление версии $VERSION завершено."
else
    log "Установка/обновление версии $VERSION завершено."
fi
log "Активный выпуск: $INSTALL_ROOT/current -> $RELEASE"
log "Управляемый Python: $MANAGED_PYTHON"
log "Виртуальное окружение: $INSTALL_ROOT/current/.venv"
log "Список найденных Python/venv: sudo planner-solving-python"
log "Постоянные данные: $SHARED"
if [[ $NO_SYSTEMD -eq 1 ]]; then
    log "Запуск без systemd: $STATE/run.sh"
else
    SERVER_IP="$(hostname -I 2>/dev/null | awk 'NF {print $1; exit}')"
    SERVER_IP="${SERVER_IP:-127.0.0.1}"
    log "Интерфейс: http://$SERVER_IP:$PORT"
    log "Диагностика: sudo planner-solving-doctor"
fi
