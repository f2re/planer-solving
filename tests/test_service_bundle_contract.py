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
    assert 'wait_for_health "$VENV_PYTHON" "$PORT" 75' in installer
    assert 'port_available "$VENV_PYTHON" "$HOST" "$PORT"' in installer

    assert 'CURRENT="$(readlink -f "$INSTALL_ROOT/current")"' in runtime
    assert 'PYTHON="$CURRENT/.venv/bin/python"' in runtime
    assert 'MANAGED_RUNTIME=' in runtime
    assert 'unset PYTHONHOME' in runtime
    assert 'exec "$PYTHON" -m uvicorn' in runtime
    assert 'pip install' not in runtime


def test_bundle_contains_runtime_discovery_doctor_and_integrity_entrypoints():
    builder = text(OFFLINE / "build_bundle.py")
    entrypoint = text(OFFLINE / "install_from_archive.sh")
    doctor = text(OFFLINE / "doctor.sh")

    for name in (
        '"runtime.sh"',
        '"doctor.sh"',
        '"python_discovery.sh"',
        '"python_runtime.py"',
        '"verify_bundle.sh"',
    ):
        assert name in builder
    assert 'BUNDLE_FORMAT_VERSION = 3' in builder
    assert 'include_python_runtime' in builder
    assert '--without-python-runtime' in builder
    assert 'Отсутствует обязательный файл контрольной суммы' in entrypoint
    assert '--allow-unsigned' in entrypoint
    assert 'PLANNER_INVOKING_USER' in entrypoint
    assert 'PLANNER_INVOKING_PYENV_ROOT' in entrypoint
    assert '--list-python' in entrypoint
    assert '--repair' in entrypoint
    assert 'planner-solving-doctor' in entrypoint
    assert 'PIPESTATUS[0]' in doctor
    assert 'python-info.sh' in doctor


def test_python_search_accepts_venv_pyenv_directories_and_missing_libpython():
    discovery = text(OFFLINE / "python_discovery.sh")
    installer = text(OFFLINE / "install_or_update.sh")

    assert 'каталог стандартной библиотеки' in discovery
    assert 'корень pyenv' in discovery
    assert 'shim pyenv' in discovery
    assert 'pyvenv.cfg' in discovery
    assert 'PLANNER_INVOKING_VIRTUAL_ENV' in discovery
    assert 'PLANNER_INVOKING_PYENV_ROOT' in discovery
    assert 'PLANNER_INVOKING_PATH' in discovery
    assert 'LD_LIBRARY_PATH' in discovery
    assert 'libpython${expected_major}.${expected_minor}.so' in discovery
    assert '--python VALUE' in installer
    assert '--python-search-root' in installer
    assert '--strict-python' in installer
    assert '--list-python' in installer
    assert 'Восстановлен путь к libpython' in installer


def test_service_user_checks_new_venv_before_switching_release():
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
    assert '.planner-runtime' in installer
    assert 'python.real' in installer
    assert 'REQUIRED_MODULES' in preflight
    assert '"uvicorn"' in preflight
    assert '"openpyxl"' in preflight
    assert 'runuser -u "$user"' in common
    assert 'acquire_install_lock' in common


def test_update_is_atomic_and_restores_service_data_and_unit_on_failure():
    installer = text(OFFLINE / "install_or_update.sh")
    assert 'backup_shared' in installer
    assert 'rollback_installation' in installer
    assert 'UNIT_BACKUP' in installer
    assert 'DEFAULT_BACKUP' in installer
    assert 'OLD_ACTIVE_UNITS' in installer
    assert 'atomic_link "$RELEASE" "$INSTALL_ROOT/current"' in installer
    assert 'INSTALL_FINISHED=1' in installer
    assert 'shared' in installer


def test_source_launcher_never_repairs_managed_release_at_service_start():
    launcher = text(ROOT / "start_web.sh")
    guard = launcher.index('PLANNER_MANAGED_INSTALL')
    venv_install = launcher.index('pip install')
    assert guard < venv_install
    assert 'служба не устанавливает зависимости при старте' in launcher
    assert 'tools.service_preflight' in launcher
