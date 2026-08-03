#!/usr/bin/env bash
set -Eeuo pipefail
BUNDLE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$BUNDLE_ROOT/common.sh"

INSTALL_ROOT=""
LEGACY_DIR=""
SERVICE_USER="${SUDO_USER:-$(id -un)}"
SERVICE_GROUP=""
PORT="8001"
PYTHON_BIN="${PYTHON_BIN:-}"  # пустой — будет определён через resolve_python_bin
NO_SYSTEMD=0
ASSUME_YES=0

usage() {
    cat <<'EOF'
Установка или обновление Planner Solving из офлайн-пакета.

  sudo ./install_or_update.sh [параметры]

Параметры:
  --install-dir PATH   каталог установки (по умолчанию /opt/planner-solving)
  --legacy-dir PATH    прежняя установка, данные из которой надо перенести
  --service-user USER  пользователь systemd-службы
  --port PORT          порт веб-интерфейса, по умолчанию 8001
  --python PATH        Python 3.11 той же архитектуры, что использован при сборке
  --no-systemd         не устанавливать и не запускать systemd-службу
  --yes                не запрашивать подтверждение
EOF
}

while (($#)); do
    case "$1" in
        --install-dir) INSTALL_ROOT="$2"; shift 2 ;;
        --legacy-dir) LEGACY_DIR="$2"; shift 2 ;;
        --service-user) SERVICE_USER="$2"; shift 2 ;;
        --port) PORT="$2"; shift 2 ;;
        --python) PYTHON_BIN="$2"; shift 2 ;;
        --no-systemd) NO_SYSTEMD=1; shift ;;
        --yes|-y) ASSUME_YES=1; shift ;;
        --help|-h) usage; exit 0 ;;
        *) die "Неизвестный параметр: $1" ;;
    esac
done

if [[ -z "$INSTALL_ROOT" ]]; then
    if [[ $EUID -eq 0 ]]; then INSTALL_ROOT="/opt/planner-solving"; else INSTALL_ROOT="$HOME/.local/opt/planner-solving"; fi
fi
INSTALL_ROOT="$(mkdir -p "$INSTALL_ROOT" && cd "$INSTALL_ROOT" && pwd)"

# ---------------------------------------------------------------------------
# Определяем Python: если пользователь не указал --python, ищем через
# resolve_python_bin у SERVICE_USER (pyenv, пользовательский venv, системный).
# ---------------------------------------------------------------------------
if [[ -z "$PYTHON_BIN" ]]; then
    PYTHON_BIN="$(resolve_python_bin "$SERVICE_USER")"
    log "Обнаружен Python пользователя $SERVICE_USER: $PYTHON_BIN"
fi
require_command "$PYTHON_BIN"
log "Используется Python: $($PYTHON_BIN --version 2>&1) — $PYTHON_BIN"

require_command tar
[[ -f "$BUNDLE_ROOT/manifest.json" ]] || die "manifest.json не найден. Запускайте сценарий из распакованного офлайн-пакета."
"$PYTHON_BIN" "$BUNDLE_ROOT/verify_bundle.py" "$BUNDLE_ROOT"

readarray -t META < <("$PYTHON_BIN" - "$BUNDLE_ROOT/manifest.json" <<'PY'
import json, sys
from pathlib import Path
m=json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
print(m["app_version"])
print(m["python"]["major"])
print(m["python"]["minor"])
print(m["architecture"])
print(m["platform"])
PY
)
VERSION="${META[0]}"; EXPECTED_MAJOR="${META[1]}"; EXPECTED_MINOR="${META[2]}"; EXPECTED_ARCH="${META[3]}"; EXPECTED_SYSTEM="${META[4]}"
readarray -t RUNTIME < <("$PYTHON_BIN" - <<'PY'
import platform, sys
print(sys.version_info.major)
print(sys.version_info.minor)
print(platform.machine().lower())
print(platform.system().lower())
PY
)
[[ "${RUNTIME[0]}" == "$EXPECTED_MAJOR" && "${RUNTIME[1]}" == "$EXPECTED_MINOR" ]] || die "Пакет собран для Python ${EXPECTED_MAJOR}.${EXPECTED_MINOR}, найден ${RUNTIME[0]}.${RUNTIME[1]}."
[[ "${RUNTIME[2]}" == "$EXPECTED_ARCH" ]] || die "Архитектура пакета $EXPECTED_ARCH, архитектура машины ${RUNTIME[2]}."
[[ "${RUNTIME[3]}" == "$EXPECTED_SYSTEM" ]] || warn "Пакет собран для $EXPECTED_SYSTEM, текущая система ${RUNTIME[3]}."
[[ "$PORT" =~ ^[0-9]+$ ]] && ((PORT >= 1 && PORT <= 65535)) || die "Некорректный порт: $PORT"

if [[ $ASSUME_YES -eq 0 ]]; then
    printf 'Установить Planner Solving %s в %s? [y/N] ' "$VERSION" "$INSTALL_ROOT"
    read -r answer
    [[ "$answer" =~ ^[YyДд]$ ]] || exit 0
fi

RELEASES="$INSTALL_ROOT/releases"
SHARED="$INSTALL_ROOT/shared"
STATE="$INSTALL_ROOT/state"
BACKUPS="$SHARED/backups"
mkdir -p "$RELEASES" "$SHARED/data" "$SHARED/input" "$SHARED/output" "$BACKUPS" "$STATE"
[[ -f "$SHARED/teachers.json" ]] || printf '[]\n' > "$SHARED/teachers.json"
[[ -f "$SHARED/config.json" ]] || printf '{}\n' > "$SHARED/config.json"

if [[ -n "$LEGACY_DIR" ]]; then
    LEGACY_DIR="$(cd "$LEGACY_DIR" && pwd)"
    log "Перенос данных из прежней установки: $LEGACY_DIR"
    if [[ ! -f "$SHARED/data/workspaces.json" && -f "$LEGACY_DIR/data/workspaces.json" ]]; then
        cp -a "$LEGACY_DIR/data/workspaces.json" "$SHARED/data/workspaces.json"
    fi
    if [[ -s "$LEGACY_DIR/teachers.json" && $(cat "$SHARED/teachers.json") == "[]" ]]; then
        cp -a "$LEGACY_DIR/teachers.json" "$SHARED/teachers.json"
    fi
    [[ -f "$LEGACY_DIR/config.json" ]] && cp -a "$LEGACY_DIR/config.json" "$SHARED/config.json"
    if [[ -d "$LEGACY_DIR/output" ]]; then cp -an "$LEGACY_DIR/output/." "$SHARED/output/" 2>/dev/null || true; fi
fi

STAMP="$(date +%Y%m%d-%H%M%S)"
RELEASE="$RELEASES/${VERSION}-${STAMP}"
[[ ! -e "$RELEASE" ]] || die "Каталог выпуска уже существует: $RELEASE"
log "Подготовка выпуска: $RELEASE"
mkdir -p "$RELEASE"
cp -a "$BUNDLE_ROOT/app/." "$RELEASE/"
cp -a "$BUNDLE_ROOT/manifest.json" "$RELEASE/.offline-manifest.json"

# ---------------------------------------------------------------------------
# Создаём venv и устанавливаем зависимости ОТ ИМЕНИ SERVICE_USER.
# Это критически важно: pyenv/venv пользователя недоступен для root,
# а файлы, созданные root-ом, будут недоступны SERVICE_USER при запуске.
# ---------------------------------------------------------------------------
_create_venv() {
    "$PYTHON_BIN" -m venv "$RELEASE/.venv" && \
    "$RELEASE/.venv/bin/python" -m pip install --no-index \
        --find-links "$BUNDLE_ROOT/wheelhouse" \
        --requirement "$RELEASE/requirements-runtime.txt"
}

if [[ $EUID -eq 0 && "$SERVICE_USER" != "root" ]]; then
    # Запускаем создание venv от имени пользователя-службы
    chown -R "$SERVICE_USER" "$RELEASE"
    if ! sudo -u "$SERVICE_USER" \
        PYTHON_BIN="$PYTHON_BIN" \
        RELEASE="$RELEASE" \
        BUNDLE_ROOT="$BUNDLE_ROOT" \
        bash -c '
            set -Eeuo pipefail
            "$PYTHON_BIN" -m venv "$RELEASE/.venv" || exit 1
            "$RELEASE/.venv/bin/python" -m pip install --no-index \
                --find-links "$BUNDLE_ROOT/wheelhouse" \
                --requirement "$RELEASE/requirements-runtime.txt"
        '; then
        rm -rf "$RELEASE"
        die "Не удалось создать виртуальное окружение от имени $SERVICE_USER. Убедитесь, что Python $PYTHON_BIN доступен пользователю $SERVICE_USER и содержит модуль venv."
    fi
else
    if ! _create_venv; then
        rm -rf "$RELEASE"
        die "Не удалось создать виртуальное окружение. Установите пакет python${EXPECTED_MAJOR}.${EXPECTED_MINOR}-venv."
    fi
fi

rm -rf "$RELEASE/data" "$RELEASE/input" "$RELEASE/output"
ln -s "$SHARED/data" "$RELEASE/data"
ln -s "$SHARED/input" "$RELEASE/input"
ln -s "$SHARED/output" "$RELEASE/output"
rm -f "$RELEASE/teachers.json" "$RELEASE/config.json"
ln -s "$SHARED/teachers.json" "$RELEASE/teachers.json"
ln -s "$SHARED/config.json" "$RELEASE/config.json"
chmod -R a+rX "$RELEASE"

PREVIOUS=""
[[ -L "$INSTALL_ROOT/current" ]] && PREVIOUS="$(readlink -f "$INSTALL_ROOT/current")"

if [[ $NO_SYSTEMD -eq 0 && $EUID -ne 0 ]]; then
    warn "Без прав root systemd-служба не устанавливается. Используется режим --no-systemd."
    NO_SYSTEMD=1
fi
if [[ $NO_SYSTEMD -eq 0 ]]; then
    id "$SERVICE_USER" >/dev/null 2>&1 || die "Пользователь службы не существует: $SERVICE_USER"
    SERVICE_GROUP="$(id -gn "$SERVICE_USER")"
fi

[[ $NO_SYSTEMD -eq 1 ]] || service_stop
BACKUP="$(backup_shared "$SHARED" "$BACKUPS" "before-${VERSION}")"
log "Резервная копия: $BACKUP"

rollback_failed_update() {
    local code=$?
    warn "Обновление не завершено, выполняется автоматический откат."
    if [[ $NO_SYSTEMD -eq 0 ]]; then service_stop || true; fi
    if [[ -n "$PREVIOUS" && -d "$PREVIOUS" ]]; then
        atomic_link "$PREVIOUS" "$INSTALL_ROOT/current"
    else
        rm -f "$INSTALL_ROOT/current"
    fi
    restore_shared "$SHARED" "$BACKUP"
    if [[ $NO_SYSTEMD -eq 0 ]]; then
        set_shared_owner "$SHARED" "$SERVICE_USER:$SERVICE_GROUP"
        if [[ -n "$PREVIOUS" ]]; then
            service_start || true
        else
            systemctl disable planner-solving.service >/dev/null 2>&1 || true
            rm -f /etc/systemd/system/planner-solving.service
            systemctl daemon-reload >/dev/null 2>&1 || true
            systemctl start planner-web.service >/dev/null 2>&1 || true
        fi
    fi
    exit "$code"
}
trap rollback_failed_update ERR

_run_as_service_user() {
    # Запускает команду от имени SERVICE_USER, если мы root.
    # Использование: _run_as_service_user <команда> [аргументы...]
    if [[ $EUID -eq 0 && "$SERVICE_USER" != "root" ]]; then
        sudo -u "$SERVICE_USER" \
            env PYTHONPATH="$RELEASE" \
            bash -c 'cd "$1" && shift && exec "$@"' _ "$RELEASE" "$@"
    else
        (cd "$RELEASE" && PYTHONPATH="$RELEASE" "$@")
    fi
}

_run_as_service_user "$RELEASE/.venv/bin/python" -m tools.migrate \
    --data-dir "$SHARED/data" --legacy-teachers "$SHARED/teachers.json" \
    --backup-dir "$BACKUPS/migrations"
_run_as_service_user "$RELEASE/.venv/bin/python" -m tools.healthcheck \
    --app-root "$RELEASE" --data-dir "$SHARED/data"

atomic_link "$RELEASE" "$INSTALL_ROOT/current"

cat > "$STATE/run.sh" <<EOF
#!/usr/bin/env bash
set -Eeuo pipefail
cd "$INSTALL_ROOT/current"
export PYTHONPATH="$INSTALL_ROOT/current"
export PYTHONDONTWRITEBYTECODE=1
exec "$INSTALL_ROOT/current/.venv/bin/python" -m uvicorn web.backend.main:app --host 0.0.0.0 --port "$PORT" --workers 1
EOF
chmod 0755 "$STATE/run.sh"

if [[ $NO_SYSTEMD -eq 0 ]]; then
    set_shared_owner "$SHARED" "$SERVICE_USER:$SERVICE_GROUP"
    cat > /etc/systemd/system/planner-solving.service <<EOF
[Unit]
Description=Planner Solving offline service
After=network.target

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_GROUP
WorkingDirectory=$INSTALL_ROOT/current
Environment=PYTHONPATH=$INSTALL_ROOT/current
Environment=PYTHONDONTWRITEBYTECODE=1
ExecStart=$INSTALL_ROOT/current/.venv/bin/python -m uvicorn web.backend.main:app --host 0.0.0.0 --port $PORT --workers 1
Restart=on-failure
RestartSec=5
TimeoutStopSec=30
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ReadWritePaths=$INSTALL_ROOT/shared

[Install]
WantedBy=multi-user.target
EOF
    service_start
    if ! wait_for_health "$PYTHON_BIN" "$PORT" 45; then
        warn "Служба запущена, но /api/health не отвечает."
        false
    fi
    systemctl disable planner-web.service >/dev/null 2>&1 || true
fi

write_update_state "$STATE/last-update.json" "$PREVIOUS" "$RELEASE" "$BACKUP" "$VERSION"
trap - ERR
log "Установка версии $VERSION завершена."
if [[ $NO_SYSTEMD -eq 1 ]]; then
    log "Запуск: $STATE/run.sh"
else
    log "Интерфейс: http://$(hostname -I 2>/dev/null | awk '{print $1}' || echo 127.0.0.1):$PORT"
fi
