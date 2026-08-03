from __future__ import annotations

from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).parents[1]
COMMON = ROOT / "offline" / "common.sh"
DISCOVERY = ROOT / "offline" / "python_discovery.sh"


def _run_discovery(hint: Path, tmp_path: Path) -> str:
    major, minor = sys.version_info[:2]
    script = f'''
set -Eeuo pipefail
source "{COMMON}"
source "{DISCOVERY}"
resolve_python_runtime "{hint}" {major} {minor} "{tmp_path / 'install'}" "$(id -un)" "" 0 1
printf 'SELECTED=%s\\n' "$PYTHON_SELECTED"
printf 'LIB=%s\\n' "$PYTHON_SELECTED_LD_LIBRARY_PATH"
printf 'VERSION=%s\\n' "$PYTHON_SELECTED_VERSION"
python_exec_selected -c 'import ensurepip,ssl,sqlite3,sys,venv; print("EXEC_OK=%d.%d" % sys.version_info[:2])'
'''
    return subprocess.check_output(["bash", "-c", script], text=True)


def test_pyenv_with_missing_libpython_is_recovered_and_directory_hints_work(tmp_path: Path):
    major, minor = sys.version_info[:2]
    pyenv = tmp_path / ".pyenv"
    version = pyenv / "versions" / f"{major}.{minor}.99"
    bin_dir = version / "bin"
    lib_dir = version / "lib"
    stdlib = lib_dir / f"python{major}.{minor}"
    shims = pyenv / "shims"
    pyenv_bin = pyenv / "bin"
    for directory in (bin_dir, lib_dir, stdlib, shims, pyenv_bin):
        directory.mkdir(parents=True, exist_ok=True)

    wrapper = bin_dir / f"python{major}.{minor}"
    wrapper.write_text(
        "#!/bin/sh\n"
        f"case :${{LD_LIBRARY_PATH:-}}: in *:{lib_dir}:*) exec {sys.executable} \"$@\" ;; "
        f"*) echo 'error while loading shared libraries: libpython{major}.{minor}.so.1.0: cannot open shared object file' >&2; exit 127 ;; esac\n",
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    (lib_dir / f"libpython{major}.{minor}.so.1.0").write_bytes(b"probe marker")
    (pyenv_bin / "pyenv").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (pyenv_bin / "pyenv").chmod(0o755)
    (shims / f"python{major}.{minor}").write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    (shims / f"python{major}.{minor}").chmod(0o755)

    hints = [pyenv, version, bin_dir, wrapper, stdlib, pyenv_bin / "pyenv", shims / f"python{major}.{minor}"]
    for hint in hints:
        output = _run_discovery(hint, tmp_path)
        assert f"LIB={lib_dir}" in output
        assert f"EXEC_OK={major}.{minor}" in output
        assert "SELECTED=" in output


def test_existing_venv_is_reported_as_venv(tmp_path: Path):
    venv = tmp_path / "venv"
    subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
    major, minor = sys.version_info[:2]
    script = f'''
set -Eeuo pipefail
source "{COMMON}"
source "{DISCOVERY}"
resolve_python_runtime "{venv}" {major} {minor} "{tmp_path / 'install'}" "$(id -un)" "" 0 1
printf '%s|%s|%s\\n' "$PYTHON_SELECTED" "$PYTHON_SELECTED_IS_VENV" "$PYTHON_SELECTED_BASE_PREFIX"
'''
    output = subprocess.check_output(["bash", "-c", script], text=True).strip()
    assert "|1|" in output
    assert str(venv / "bin") in output


def test_list_mode_mentions_failed_directory_instead_of_executing_it(tmp_path: Path):
    major, minor = sys.version_info[:2]
    empty = tmp_path / "not-python"
    empty.mkdir()
    script = f'''
set -Eeuo pipefail
source "{COMMON}"
source "{DISCOVERY}"
resolve_python_runtime "{empty}" {major} {minor} "{tmp_path / 'install'}" "$(id -un)" "" 1 1 || true
'''
    output = subprocess.check_output(["bash", "-c", script], text=True)
    assert str(empty) in output
    assert "каталог просмотрен" in output
