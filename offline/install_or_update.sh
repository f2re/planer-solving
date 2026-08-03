#!/usr/bin/env bash
set -Eeuo pipefail
BUNDLE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$BUNDLE_ROOT/common.sh"

INSTALL_ROOT="/opt/planner-solving"
LEGACY_DIR=""
SERVICE_USER="planner-solving"
SERVICE_GROUP=""
PORT="8001"
HOST="0.0.0.0"
WORKERS="1"
PYTHON_BIN="${PYTHON_BIN:-}"
NO_SYSTEMD=0
ASSUME_YES=0
KEEP_RELEASES=3

usage() {
    cat <<'EOF'
Установка или обновление Planner Solving из автономного пакета.

  sudo ./install_or_update.sh [параметры]

Параметры:
  --install-dir PATH   каталог установки, по умолчанию /opt/planner-solving
  --legacy-dir PATH    прежняя установка, данные из которой надо перенести
  --service-user USER  системный пользователь, по умолчанию planner-solving
  --port PORT          порт веб-интерфейса, по умолчанию 8001
  --host ADDRESS       адрес прослушивания, по умолчанию 0.0.0.0
  --workers N          число процессов Uvicorn, по умолчанию 1
  --python PATH        Python точной версии, указанной в manifest.json
  --keep-releases N    сколько последних выпусков хранить, по умолчанию 3
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
        --host) HOST="$2"; shift 2 ;;
        --workers) WORKERS="$2"; shift 2 ;;
        --python) PYTHON_BIN="$2"; shift 2 ;;
        --keep-releases) KEEP_RELEASES="$2"; shift 2 ;;
        --no-systemd) NO_SYSTEMD=1; shift ;;
        --yes|-y) ASSUME_YES=1; shift ;;
        --help|-h) usage; exit 0 ;;
        *) die "Неизвестный параметр: $1" ;;
    esac
done

[[ "$PORT" =~ ^[0-9]+$ ]] && ((PORT >= 1 && PORT <= 65535)) || die "Некорректный порт: $PORT"
[[ "$WORKERS" =~ ^[0-9]+$ ]] && ((WORKERS >= 1 && WORKERS <= 16)) || die "Некорректное число процессов: $WORKERS"
[[ "$KEEP_RELEASES" =~ ^[0-9]+$ ]] && ((KEEP_RELEASES >= 2 && KEEP_RELEASES <= 20)) || die "Некорректное число хранимых выпусков: $KEEP_RELEASES"

if [[ $EUID -ne 0 && "$INSTALL_ROOT" == /opt/* ]]; then
    die "Установка в $INSTALL_ROOT требует root. Запустите: sudo ./install-planner-solving.sh"
fi
if [[ $NO_SYSTEMD -eq 0 && $EUID -ne 0 ]]; then
    warn "Без root systemd-служба недоступна; включён режим --no-systemd."
    NO_SYSTEMD=1
fi

require_command tar
require_command sed
require_command find
[[ -f "$BUNDLE_ROOT/manifest.json" ]] || die "manifest.json не найден. Запускайте сценарий из распакованного автономного пакета."
[[ -d "$BUNDLE_ROOT/wheelhouse" ]] || die "wheelhouse не найден в автономном пакете."

manifest_value() {
    local key="$1"
    sed -n "s/^[[:space:]]*\"$key\":[[:space:]]*\"\{0,1\}\([^\",}]*\)\"\{0,1\}.*/\1/p" "$BUNDLE_ROOT/manifest.json" | head -n 1
}
python_manifest_value() {
    local key="$1"
    sed -n '/"python"[[:space:]]*:[[:space:]]*{/,/}/s/^[[:space:]]*"'"$key"'"[[:space:]]*:[[:space:]]*\([0-9][0-9]*\).*/\1/p' "$BUNDLE_ROOT/manifest.json" | head -n 1
}

EXPECTED_MAJOR="$(python_manifest_value major)"
EXPECTED_MINOR="$(python_manifest_value minor)"
VERSION="$(manifest_value app_version)"
EXPECTED_ARCH="$(manifest_value architecture)"
EXPECTED_SYSTEM="$(manifest_value platform)"
[[ -n "$VERSION" && -n "$EXPECTED_MAJOR" && -n "$EXPECTED_MINOR" ]] || die "manifest.json повреждён или имеет неизвестный формат."

if [[ -z "$PYTHON_BIN" ]]; then
    PYTHON_BIN="$(resolve_python_bin "$SERVICE_USER" "$EXPECTED_MAJOR" "$EXPECTED_MINOR" "$INSTALL_ROOT")"
fi
require_command "$PYTHON_BIN"
export PYTHON_BIN
log "Используется Python: $($PYTHON_BIN --version 2>&1) — $PYTHON_BIN"
"$PYTHON_BIN" "$BUNDLE_ROOT/verify_bundle.py" "$BUNDLE_ROOT"

readarray -t RUNTIME < <("$PYTHON_BIN" - <<'PY'
import platform, sys
print(sys.version_info.major)
print(sys.version_info.minor)
print(platform.machine().lower())
print(platform.system().lower())
PY
)
[[ "${RUNTIME[0]}" == "$EXPECTED_MAJOR" && "${RUNTIME[1]}" == "$EXPECTED_MINOR" ]] || die "Пакет собран для Python ${EXPECTED_MAJOR}.${EXPECTED_MINOR}, найден ${RUNTIME[0]}.${RUNTIME[1]}."
[[ -z "$EXPECTED_ARCH" || "${RUNTIME[2]}" == "$EXPECTED_ARCH" ]] || die "Архитектура пакета $EXPECTED_ARCH, архитектура машины ${RUNTIME[2]}."
[[ -z "$EXPECTED_SYSTEM" || "${RUNTIME[3]}" == "$EXPECTED_SYSTEM" ]] || warn "Пакет собран для $EXPECTED_SYSTEM, текущая система ${RUNTIME[3]}."

if [[ $ASSUME_YES -eq 0 ]]; then
    printf 'Установить Planner Solving %s в %s? [y/N] ' "$VERSION" "$INSTALL_ROOT"
    read -r answer
    [[ "$answer" =~ ^[YyДд]$ ]] || exit 0
fi

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

mkdir -p "$INSTALL_ROOT"
INSTALL_ROOT="$(cd "$INSTALL_ROOT" && pwd)"
RELEASES="$INSTALL_ROOT/releases"
SHARED="$INSTALL_ROOT/shared"
STATE="$INSTALL_ROOT/state"
BACKUPS="$SHARED/backups"
mkdir -p "$RELEASES" "$SHARED/data" "$SHARED/input" "$SHARED/output" "$SHARED/home" "$SHARED/cache" "$BACKUPS" "$STATE"
chmod 0755 "$INSTALL_ROOT" "$RELEASES" "$STATE"
[[ -f "$SHARED/teachers.json" ]] || printf '[]\n' > "$SHARED/teachers.json"
[[ -f "$SHARED/config.json" ]] || printf '{}\n' > "$SHARED/config.json"
set_shared_owner "$SHARED" "$SERVICE_USER:$SERVICE_GROUP"

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
    [[ -d "$LEGACY_DIR/output" ]] && cp -an "$LEGACY_DIR/output/." "$SHARED/output/" 2>/dev/null || true
    set_shared_owner "$SHARED" "$SERVICE_USER:$SERVICE_GROUP"
fi

STAMP="$(date +%Y%m%d-%H%M%S)"
RELEASE="$RELEASES/${VERSION}-${STAMP}"
[[ ! -e "$RELEASE" ]] || die "Каталог выпуска уже существует: $RELEASE"
log "Подготовка выпуска: $RELEASE"
mkdir -p "$RELEASE"
cp -a "$BUNDLE_ROOT/app/." "$RELEASE/"
cp -a "$BUNDLE_ROOT/manifest.json" "$RELEASE/.offline-manifest.json"

log "Создание изолированного виртуального окружения"
if ! "$PYTHON_BIN" -m venv --copies "$RELEASE/.venv"; then
    rm -rf "$RELEASE"
    die "Не удалось создать venv. Установите пакет python${EXPECTED_MAJOR}.${EXPECTED_MINOR}-venv или укажите рабочий Python через --python."
fi
if ! "$RELEASE/.venv/bin/python" -m pip install \
    --disable-pip-version-check \
    --no-cache-dir \
    --no-index \
    --find-links "$BUNDLE_ROOT/wheelhouse" \
    --requirement "$RELEASE/requirements-runtime.txt"; then
    rm -rf "$RELEASE"
    die "Зависимости не установлены из wheelhouse. Проверьте соответствие Python, архитектуры и пакета."
fi

# Добавляем корень неизменяемого выпуска в sys.path самого venv. Благодаря
# этому штатные команды `python -m tools...` работают из любого каталога,
# а не только после ручного `cd` в текущий выпуск.
SITE_PACKAGES="$("$RELEASE/.venv/bin/python" - <<'PY'
import site
paths = site.getsitepackages()
if not paths:
    raise SystemExit("site-packages не найден")
print(paths[0])
PY
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

# Проверяем, что именно пользователь службы видит venv и все библиотеки.
if ! run_as_user "$SERVICE_USER" env \
    PYTHONPATH="$RELEASE" \
    PYTHONNOUSERSITE=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PLANNER_BASE_DIR="$RELEASE" \
    "$RELEASE/.venv/bin/python" -m tools.service_preflight \
        --app-root "$RELEASE" \
        --shared-dir "$SHARED"; then
    rm -rf "$RELEASE"
    die "Пользователь $SERVICE_USER не может запустить Python или импортировать зависимости из $RELEASE/.venv. Не используйте закрытый Python из домашнего каталога; укажите системный Python через --python."
fi

PREVIOUS=""
[[ -L "$INSTALL_ROOT/current" ]] && PREVIOUS="$(readlink -f "$INSTALL_ROOT/current")"
HAD_UNIT=0
[[ -f /etc/systemd/system/planner-solving.service ]] && HAD_UNIT=1

[[ $NO_SYSTEMD -eq 1 ]] || service_stop
BACKUP="$(backup_shared "$SHARED" "$BACKUPS" "before-${VERSION}")"
log "Резервная копия: $BACKUP"
set_shared_owner "$SHARED" "$SERVICE_USER:$SERVICE_GROUP"

rollback_failed_update() {
    local code=$?
    warn "Обновление не завершено, выполняется автоматический откат."
    [[ $NO_SYSTEMD -eq 1 ]] || service_stop || true
    if [[ -n "$PREVIOUS" && -d "$PREVIOUS" ]]; then
        atomic_link "$PREVIOUS" "$INSTALL_ROOT/current"
    else
        rm -f "$INSTALL_ROOT/current"
    fi
    restore_shared "$SHARED" "$BACKUP"
    set_shared_owner "$SHARED" "$SERVICE_USER:$SERVICE_GROUP"
    if [[ $NO_SYSTEMD -eq 0 ]]; then
        if [[ -n "$PREVIOUS" ]]; then
            service_start || true
        elif [[ $HAD_UNIT -eq 0 ]]; then
            systemctl disable planner-solving.service >/dev/null 2>&1 || true
            rm -f /etc/systemd/system/planner-solving.service /etc/default/planner-solving
            systemctl daemon-reload >/dev/null 2>&1 || true
        fi
    fi
    exit "$code"
}
trap rollback_failed_update ERR

run_as_user "$SERVICE_USER" env \
    PYTHONPATH="$RELEASE" \
    PYTHONNOUSERSITE=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PLANNER_BASE_DIR="$RELEASE" \
    "$RELEASE/.venv/bin/python" -m tools.migrate \
        --data-dir "$SHARED/data" \
        --legacy-teachers "$SHARED/teachers.json" \
        --backup-dir "$BACKUPS/migrations"
run_as_user "$SERVICE_USER" env \
    PYTHONPATH="$RELEASE" \
    PYTHONNOUSERSITE=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PLANNER_BASE_DIR="$RELEASE" \
    "$RELEASE/.venv/bin/python" -m tools.healthcheck \
        --app-root "$RELEASE" \
        --data-dir "$SHARED/data"

atomic_link "$RELEASE" "$INSTALL_ROOT/current"

install -m 0755 "$BUNDLE_ROOT/runtime.sh" "$STATE/run-service.sh"
install -m 0755 "$BUNDLE_ROOT/doctor.sh" "$STATE/doctor.sh"
cat > "$STATE/run.sh" <<EOF
#!/usr/bin/env bash
set -Eeuo pipefail
export PLANNER_INSTALL_ROOT="$INSTALL_ROOT"
export PLANNER_HOST="$HOST"
export PLANNER_PORT="$PORT"
export PLANNER_WORKERS="$WORKERS"
exec "$STATE/run-service.sh" "\$@"
EOF
chmod 0755 "$STATE/run.sh"
cat > "$STATE/admin.sh" <<EOF
#!/usr/bin/env bash
set -Eeuo pipefail
CURRENT="\$(readlink -f "$INSTALL_ROOT/current")"
cd "\$CURRENT"
export PYTHONPATH="\$CURRENT"
export PYTHONNOUSERSITE=1
unset PYTHONHOME
exec "\$CURRENT/.venv/bin/python" -m tools.user_admin \
  --data-dir "$SHARED/data" \
  --legacy-teachers "$SHARED/teachers.json" "\$@"
EOF
chmod 0755 "$STATE/admin.sh"
ln -sfn "$STATE/admin.sh" /usr/local/bin/planner-solving-admin 2>/dev/null || true
ln -sfn "$STATE/doctor.sh" /usr/local/bin/planner-solving-doctor 2>/dev/null || true

if [[ $NO_SYSTEMD -eq 0 ]]; then
    mkdir -p /etc/default /etc/systemd/system
    cat > /etc/default/planner-solving <<EOF
PLANNER_INSTALL_ROOT="$INSTALL_ROOT"
PLANNER_HOST="$HOST"
PLANNER_PORT="$PORT"
PLANNER_WORKERS="$WORKERS"
PLANNER_HOME="$SHARED/home"
PLANNER_CACHE_DIR="$SHARED/cache"
EOF
    chmod 0644 /etc/default/planner-solving

    cat > /etc/systemd/system/planner-solving.service <<EOF
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
TimeoutStartSec=90
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
EOF
    if command -v systemd-analyze >/dev/null 2>&1; then
        systemd-analyze verify /etc/systemd/system/planner-solving.service
    fi
    service_start
    if ! wait_for_health "$RELEASE/.venv/bin/python" "$PORT" 60; then
        warn "Служба запущена, но /api/health не отвечает."
        journalctl -u planner-solving.service -n 80 --no-pager >&2 2>/dev/null || true
        false
    fi
    systemctl disable planner-web.service >/dev/null 2>&1 || true
fi

write_update_state "$STATE/last-update.json" "$PREVIOUS" "$RELEASE" "$BACKUP" "$VERSION"
trap - ERR

# Оставляем текущий и несколько предыдущих выпусков для ручного отката.
mapfile -t OLD_RELEASES < <(find "$RELEASES" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' | sort -nr | awk '{print $2}')
for ((index=KEEP_RELEASES; index<${#OLD_RELEASES[@]}; index++)); do
    candidate="${OLD_RELEASES[$index]}"
    [[ "$candidate" == "$RELEASE" || "$candidate" == "$PREVIOUS" ]] && continue
    rm -rf "$candidate"
done

log "Установка версии $VERSION завершена."
if [[ $NO_SYSTEMD -eq 1 ]]; then
    log "Запуск: $STATE/run.sh"
else
    SERVER_IP="$(hostname -I 2>/dev/null | awk 'NF {print $1; exit}')"
    SERVER_IP="${SERVER_IP:-127.0.0.1}"
    log "Интерфейс: http://$SERVER_IP:$PORT"
    log "Диагностика: sudo planner-solving-doctor"
fi
