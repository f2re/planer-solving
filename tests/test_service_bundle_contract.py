from pathlib import Path


ROOT = Path(__file__).parents[1]
OFFLINE = ROOT / "offline"


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_managed_install_defaults_to_opt_and_stable_service_launcher():
    installer = text(OFFLINE / "install_or_update.sh")
    runtime = text(OFFLINE / "runtime.sh")

    assert 'INSTALL_ROOT="/opt/planner-solving"' in installer
    assert 'SERVICE_USER="planner-solving"' in installer
    assert 'EnvironmentFile=-/etc/default/planner-solving' in installer
    assert 'ExecStartPre=$STATE/run-service.sh --check' in installer
    assert 'ExecStart=$STATE/run-service.sh' in installer
    assert 'PYTHONNOUSERSITE=1' in installer
    assert 'ReadWritePaths=$SHARED' in installer
    assert 'systemd-analyze verify' in installer
    assert 'wait_for_health "$RELEASE/.venv/bin/python" "$PORT" 60' in installer

    assert 'CURRENT="$(readlink -f "$INSTALL_ROOT/current")"' in runtime
    assert 'PYTHON="$CURRENT/.venv/bin/python"' in runtime
    assert 'unset PYTHONHOME' in runtime
    assert 'exec "$PYTHON" -m uvicorn' in runtime
    assert 'pip install' not in runtime


def test_bundle_contains_runtime_doctor_and_integrity_checked_entrypoint():
    builder = text(OFFLINE / "build_bundle.py")
    entrypoint = text(OFFLINE / "install_from_archive.sh")
    doctor = text(OFFLINE / "doctor.sh")

    assert '"runtime.sh"' in builder
    assert '"doctor.sh"' in builder
    assert 'BUNDLE_FORMAT_VERSION = 2' in builder
    assert 'Отсутствует обязательный файл контрольной суммы' in entrypoint
    assert '--allow-unsigned' in entrypoint
    assert 'planner-solving-doctor' in entrypoint
    assert 'PIPESTATUS[0]' in doctor
    assert 'run-service.sh" --check' in doctor or '"$runtime" --check' in doctor


def test_service_user_checks_exact_venv_before_switching_release():
    installer = text(OFFLINE / "install_or_update.sh")
    preflight = text(ROOT / "tools" / "service_preflight.py")
    common = text(OFFLINE / "common.sh")

    preflight_position = installer.index('tools.service_preflight')
    switch_position = installer.index('atomic_link "$RELEASE" "$INSTALL_ROOT/current"')
    assert preflight_position < switch_position
    assert 'run_as_user "$SERVICE_USER"' in installer
    assert '--no-index' in installer
    assert '--find-links "$BUNDLE_ROOT/wheelhouse"' in installer
    assert 'planner-solving-app.pth' in installer
    assert 'cd "\\$CURRENT"' in installer
    assert 'export PYTHONPATH="\\$CURRENT"' in installer
    assert 'REQUIRED_MODULES' in preflight
    assert '"uvicorn"' in preflight
    assert '"openpyxl"' in preflight
    assert 'runuser -u "$user"' in common
    assert 'SUDO_USER' not in common


def test_source_launcher_never_repairs_managed_release_at_service_start():
    launcher = text(ROOT / "start_web.sh")
    guard = launcher.index('PLANNER_MANAGED_INSTALL')
    venv_install = launcher.index('pip install')
    assert guard < venv_install
    assert 'служба не устанавливает зависимости при старте' in launcher
    assert 'tools.service_preflight' in launcher
