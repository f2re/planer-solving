#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_ROOT="/opt/planner-solving"
ARCHIVE=""
SERVICE_USER=""
PORT="8001"
PYTHON_BIN=""
NO_SYSTEMD=0
ASSUME_YES=1

usage() {
    cat <<'EOF'
Распаковка, установка или обновление Planner Solving.

  sudo ./install-planner-solving.sh [параметры]

Параметры:
  --archive PATH       архив planner-solving-offline-*.tar.gz
  --install-dir PATH   каталог установки, по умолчанию /opt/planner-solving
  --service-user USER  пользователь службы; существующая настройка сохраняется
  --port PORT          порт, по умолчанию 8001
  --python PATH        Python 3.11+
  --no-systemd         не устанавливать службу
  --ask                запросить подтверждение внутреннего установщика
EOF
}

while (($#)); do
    case "$1" in
        --archive) ARCHIVE="$2"; shift 2 ;;
        --install-dir) INSTALL_ROOT="$2"; shift 2 ;;
        --service-user) SERVICE_USER="$2"; shift 2 ;;
        --port) PORT="$2"; shift 2 ;;
        --python) PYTHON_BIN="$2"; shift 2 ;;
        --no-systemd) NO_SYSTEMD=1; shift ;;
        --ask) ASSUME_YES=0; shift ;;
        --help|-h) usage; exit 0 ;;
        *) echo "Неизвестный параметр: $1" >&2; usage; exit 2 ;;
    esac
done

if [[ $EUID -ne 0 ]]; then
    command -v sudo >/dev/null 2>&1 || {
        echo "Для установки в /opt требуются права root или команда sudo." >&2
        exit 2
    }
    reexec=(--install-dir "$INSTALL_ROOT" --port "$PORT")
    [[ -n "$ARCHIVE" ]] && reexec+=(--archive "$ARCHIVE")
    [[ -n "$SERVICE_USER" ]] && reexec+=(--service-user "$SERVICE_USER")
    [[ -n "$PYTHON_BIN" ]] && reexec+=(--python "$PYTHON_BIN")
    [[ $NO_SYSTEMD -eq 1 ]] && reexec+=(--no-systemd)
    [[ $ASSUME_YES -eq 0 ]] && reexec+=(--ask)
    exec sudo -E bash "$0" "${reexec[@]}"
fi

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

checksum_file="$ARCHIVE.sha256"
if [[ -f "$checksum_file" ]]; then
    if command -v sha256sum >/dev/null 2>&1; then
        (cd "$(dirname "$ARCHIVE")" && sha256sum -c "$(basename "$checksum_file")")
    else
        python3 - "$ARCHIVE" "$checksum_file" <<'PY'
import hashlib
from pathlib import Path
import sys
archive = Path(sys.argv[1])
expected = Path(sys.argv[2]).read_text(encoding="utf-8").split()[0]
digest = hashlib.sha256()
with archive.open("rb") as stream:
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(chunk)
if digest.hexdigest() != expected:
    raise SystemExit("Контрольная сумма архива не совпадает")
print("Контрольная сумма архива подтверждена")
PY
    fi
else
    echo "Предупреждение: файл $checksum_file отсутствует." >&2
fi

if [[ -z "$SERVICE_USER" && -f /etc/systemd/system/planner-solving.service ]]; then
    SERVICE_USER="$(awk -F= '$1=="User"{print $2; exit}' /etc/systemd/system/planner-solving.service)"
fi
SERVICE_USER="${SERVICE_USER:-planner-solving}"

if ! id "$SERVICE_USER" >/dev/null 2>&1; then
    if command -v useradd >/dev/null 2>&1; then
        useradd --system --user-group --home-dir "$INSTALL_ROOT" --shell /usr/sbin/nologin "$SERVICE_USER"
    elif command -v adduser >/dev/null 2>&1; then
        adduser --system --group --home "$INSTALL_ROOT" --no-create-home "$SERVICE_USER"
    else
        echo "Не удалось создать системного пользователя $SERVICE_USER." >&2
        exit 2
    fi
fi

TEMP_DIR="$(mktemp -d -t planner-solving-install-XXXXXX)"
cleanup() { rm -rf "$TEMP_DIR"; }
trap cleanup EXIT

tar -xzf "$ARCHIVE" -C "$TEMP_DIR"
BUNDLE_ROOT="$(find "$TEMP_DIR" -mindepth 1 -maxdepth 1 -type d -name 'planner-solving-offline-*' | head -n 1)"
[[ -n "$BUNDLE_ROOT" && -x "$BUNDLE_ROOT/install_or_update.sh" ]] || {
    echo "В архиве отсутствует install_or_update.sh" >&2
    exit 2
}

args=(
    --install-dir "$INSTALL_ROOT"
    --service-user "$SERVICE_USER"
    --port "$PORT"
)
[[ -n "$PYTHON_BIN" ]] && args+=(--python "$PYTHON_BIN")
[[ $NO_SYSTEMD -eq 1 ]] && args+=(--no-systemd)
[[ $ASSUME_YES -eq 1 ]] && args+=(--yes)

bash "$BUNDLE_ROOT/install_or_update.sh" "${args[@]}"

mkdir -p "$INSTALL_ROOT/state"
cat > "$INSTALL_ROOT/state/admin.sh" <<EOF
#!/usr/bin/env bash
set -Eeuo pipefail
cd "$INSTALL_ROOT/current"
exec "$INSTALL_ROOT/current/.venv/bin/python" -m tools.user_admin \
  --data-dir "$INSTALL_ROOT/shared/data" \
  --legacy-teachers "$INSTALL_ROOT/shared/teachers.json" "\$@"
EOF
chmod 0755 "$INSTALL_ROOT/state/admin.sh"
ln -sfn "$INSTALL_ROOT/state/admin.sh" /usr/local/bin/planner-solving-admin 2>/dev/null || true

echo
echo "Planner Solving установлен в $INSTALL_ROOT"
echo "Данные и пароли сохранены в $INSTALL_ROOT/shared/data"
echo "Управление пользователями: sudo planner-solving-admin list"
echo "Сброс пароля: sudo planner-solving-admin reset-password admin"
echo "Пустой пароль: sudo planner-solving-admin reset-password admin --empty"
