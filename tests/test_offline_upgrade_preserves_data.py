from pathlib import Path
import subprocess


def test_backup_and_restore_keep_database_accounts_and_configuration(tmp_path: Path):
    repository = Path(__file__).parents[1]
    shared = tmp_path / "shared"
    backups = shared / "backups"
    data = shared / "data"
    data.mkdir(parents=True)
    database = data / "planner-solving.sqlite3"
    database.write_bytes(b"sqlite-with-users-and-password-hashes")
    (data / "history").mkdir()
    (data / "history" / "source.xlsx").write_bytes(b"history")
    (shared / "teachers.json").write_text('[{"id":1}]\n', encoding="utf-8")
    (shared / "config.json").write_text('{"port":8001}\n', encoding="utf-8")

    script = f'''
      set -Eeuo pipefail
      source "{repository / 'offline' / 'common.sh'}"
      archive="$(backup_shared "{shared}" "{backups}" before-test)"
      printf 'damaged' > "{database}"
      printf '[]\n' > "{shared / 'teachers.json'}"
      restore_shared "{shared}" "$archive"
    '''
    subprocess.run(["bash", "-c", script], check=True)

    assert database.read_bytes() == b"sqlite-with-users-and-password-hashes"
    assert (data / "history" / "source.xlsx").read_bytes() == b"history"
    assert (shared / "teachers.json").read_text(encoding="utf-8") == '[{"id":1}]\n'
    assert (shared / "config.json").read_text(encoding="utf-8") == '{"port":8001}\n'


def test_packaged_installer_preserves_invoking_user_python_context_without_using_it_for_service():
    repository = Path(__file__).parents[1]
    entrypoint = (repository / "offline" / "install_from_archive.sh").read_text(encoding="utf-8")
    internal = (repository / "offline" / "install_or_update.sh").read_text(encoding="utf-8")
    assert 'INSTALL_ROOT="/opt/planner-solving"' in entrypoint
    assert 'SERVICE_USER="${SERVICE_USER:-planner-solving}"' in entrypoint
    assert "PLANNER_INVOKING_USER" in entrypoint
    assert "PLANNER_INVOKING_HOME" in entrypoint
    assert "PLANNER_INVOKING_VIRTUAL_ENV" in entrypoint
    assert "PLANNER_INVOKING_PYENV_ROOT" in entrypoint
    assert "PLANNER_INVOKING_PATH" in entrypoint
    assert "SUDO_USER" in entrypoint
    assert "install_or_update.sh" in entrypoint
    assert "planner-solving-admin" in internal
    assert "planner-solving-python" in internal
