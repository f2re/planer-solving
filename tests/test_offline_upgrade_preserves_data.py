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
    source = (repository / "offline" / "install_from_archive.sh").read_text(encoding="utf-8")
    assert 'INSTALL_ROOT="/opt/planner-solving"' in source
    assert 'SERVICE_USER="${SERVICE_USER:-planner-solving}"' in source
    assert "PLANNER_INVOKING_USER" in source
    assert "PLANNER_INVOKING_HOME" in source
    assert "PLANNER_INVOKING_VIRTUAL_ENV" in source
    assert "PLANNER_INVOKING_PYENV_ROOT" in source
    assert "PLANNER_INVOKING_PATH" in source
    assert "SUDO_USER" in source
    assert "install_or_update.sh" in source
    assert "planner-solving-admin" in source
    assert "planner-solving-python" in source
