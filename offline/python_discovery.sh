#!/usr/bin/env bash
# Поиск и проверка Python для автономного установщика Planner Solving.
# Файл должен подключаться после offline/common.sh.

PYTHON_CANDIDATE_PATHS=()
PYTHON_CANDIDATE_KEYS=()
PYTHON_CANDIDATE_SOURCES=()
PYTHON_CANDIDATE_EXPLICIT=()
PYTHON_CANDIDATE_USERS=()
PYTHON_ATTEMPT_PATHS=()
PYTHON_ATTEMPT_RESULTS=()
PYTHON_SELECTED=""
PYTHON_SELECTED_SOURCE=""
PYTHON_SELECTED_VERSION=""
PYTHON_SELECTED_BASE_PREFIX=""
PYTHON_SELECTED_LD_LIBRARY_PATH=""
PYTHON_SELECTED_ARCH=""
PYTHON_SELECTED_EXECUTABLE=""
PYTHON_SELECTED_IS_VENV=0
PYTHON_SELECTED_RUN_USER=""
PYTHON_PROBE_ERROR=""

_pd_abspath() {
    local path="$1" directory basename
    if [[ "$path" != */* ]]; then
        command -v -- "$path" 2>/dev/null || true
        return 0
    fi
    directory="$(dirname -- "$path")"
    basename="$(basename -- "$path")"
    if [[ -d "$directory" ]]; then
        printf '%s/%s\n' "$(cd "$directory" 2>/dev/null && pwd -P)" "$basename"
    else
        printf '%s\n' "$path"
    fi
}

_pd_realpath() {
    if command -v readlink >/dev/null 2>&1; then
        readlink -f -- "$1" 2>/dev/null || _pd_abspath "$1"
    else
        _pd_abspath "$1"
    fi
}

_pd_existing_user() {
    local user="${1:-}"
    [[ -n "$user" ]] && id "$user" >/dev/null 2>&1 && printf '%s\n' "$user"
    return 0
}

_pd_owner_user() {
    local path="${1:-}" owner=""
    [[ -e "$path" ]] || return 0
    if command -v stat >/dev/null 2>&1; then
        owner="$(stat -c '%U' "$path" 2>/dev/null || true)"
    fi
    [[ -n "$owner" && "$owner" != UNKNOWN ]] && _pd_existing_user "$owner"
    return 0
}

_pd_add_candidate() {
    local path="${1:-}" source="${2:-неизвестно}" explicit="${3:-0}" run_user="${4:-}"
    local absolute key existing
    [[ -n "$path" ]] || return 0
    if [[ "$path" != */* ]]; then
        path="$(command -v -- "$path" 2>/dev/null || true)"
        [[ -n "$path" ]] || return 0
    fi
    absolute="$(_pd_abspath "$path")"
    key="$(_pd_realpath "$absolute")"
    [[ -n "$run_user" ]] || run_user="$(_pd_owner_user "$absolute")"
    for existing in "${PYTHON_CANDIDATE_KEYS[@]:-}"; do
        [[ "$existing" == "$key" ]] && return 0
    done
    PYTHON_CANDIDATE_PATHS+=("$absolute")
    PYTHON_CANDIDATE_KEYS+=("$key")
    PYTHON_CANDIDATE_SOURCES+=("$source")
    PYTHON_CANDIDATE_EXPLICIT+=("$explicit")
    PYTHON_CANDIDATE_USERS+=("$run_user")
}

_pd_add_pyenv_root() {
    local root="${1:-}" expected_major="$2" expected_minor="$3" source="$4"
    local explicit="${5:-0}" run_user="${6:-}" candidate
    [[ -d "$root/versions" ]] || return 0
    while IFS= read -r candidate; do
        _pd_add_candidate "$candidate" "$source" "$explicit" "$run_user"
    done < <(
        find "$root/versions" -mindepth 3 -maxdepth 3 \
            -path "*/${expected_major}.${expected_minor}*/bin/python*" \
            \( -type f -o -type l \) 2>/dev/null \
        | grep -E "/bin/python(${expected_major}\\.${expected_minor}|3|)$" \
        | sort -Vr
    )
    return 0
}

_pd_hint_user() {
    local hint="${1:-}" invoking_home="${PLANNER_INVOKING_HOME:-}" invoking_user="${PLANNER_INVOKING_USER:-}"
    if [[ -n "$invoking_home" && "$hint" == "$invoking_home"/* ]]; then
        _pd_existing_user "$invoking_user"
        return 0
    fi
    _pd_owner_user "$hint"
}

_pd_add_hint() {
    local hint="${1:-}" expected_major="$2" expected_minor="$3" source="$4"
    local explicit="${5:-1}" run_user="${6:-}" parent prefix root candidate before
    [[ -n "$hint" ]] || return 0
    [[ -n "$run_user" ]] || run_user="$(_pd_hint_user "$hint")"

    if [[ "$hint" != */* ]]; then
        candidate="$(command -v -- "$hint" 2>/dev/null || true)"
        if [[ -z "$candidate" && -n "$run_user" && $EUID -eq 0 && "$run_user" != root ]]; then
            candidate="$(run_as_user "$run_user" sh -lc 'command -v "$1" 2>/dev/null || true' sh "$hint" 2>/dev/null || true)"
        fi
        if [[ -n "$candidate" ]]; then
            _pd_add_hint "$candidate" "$expected_major" "$expected_minor" "$source (PATH)" "$explicit" "$run_user"
        elif [[ "$explicit" == 1 ]]; then
            PYTHON_ATTEMPT_PATHS+=("$hint")
            PYTHON_ATTEMPT_RESULTS+=("команда не найдена в PATH")
        fi
        return 0
    fi
    hint="$(_pd_abspath "$hint")"

    if [[ -f "$hint" || -L "$hint" ]]; then
        if [[ "$(basename "$hint")" == pyenv ]]; then
            root="$(cd "$(dirname "$hint")/.." 2>/dev/null && pwd -P || true)"
            _pd_add_pyenv_root "$root" "$expected_major" "$expected_minor" "$source (исполняемый pyenv)" "$explicit" "$run_user"
            return 0
        fi
        if [[ "$hint" == */.pyenv/shims/* || "$hint" == */pyenv/shims/* ]]; then
            root="${hint%%/shims/*}"
            _pd_add_pyenv_root "$root" "$expected_major" "$expected_minor" "$source (shim pyenv)" "$explicit" "$run_user"
        fi
        _pd_add_candidate "$hint" "$source" "$explicit" "$run_user"
        return 0
    fi

    if [[ ! -d "$hint" ]]; then
        [[ "$explicit" == 1 ]] && {
            PYTHON_ATTEMPT_PATHS+=("$hint")
            PYTHON_ATTEMPT_RESULTS+=("путь не существует")
        }
        return 0
    fi

    before=${#PYTHON_CANDIDATE_PATHS[@]}
    if [[ "$hint" == */lib/python${expected_major}.${expected_minor}* ]]; then
        prefix="${hint%%/lib/python${expected_major}.${expected_minor}*}"
        _pd_add_hint "$prefix" "$expected_major" "$expected_minor" "$source (каталог стандартной библиотеки)" "$explicit" "$run_user"
    fi
    if [[ "$(basename "$hint")" == bin ]]; then
        parent="$(cd "$hint/.." 2>/dev/null && pwd -P || true)"
        _pd_add_hint "$parent" "$expected_major" "$expected_minor" "$source (каталог bin)" "$explicit" "$run_user"
    fi

    for candidate in \
        "$hint/bin/python${expected_major}.${expected_minor}" \
        "$hint/bin/python3" \
        "$hint/bin/python" \
        "$hint/.venv/bin/python" \
        "$hint/venv/bin/python" \
        "$hint/env/bin/python" \
        "$hint/python${expected_major}.${expected_minor}" \
        "$hint/python3" \
        "$hint/python"; do
        [[ -e "$candidate" ]] && _pd_add_candidate "$candidate" "$source" "$explicit" "$run_user"
    done
    _pd_add_pyenv_root "$hint" "$expected_major" "$expected_minor" "$source (корень pyenv)" "$explicit" "$run_user"

    if [[ "$explicit" == 1 && ${#PYTHON_CANDIDATE_PATHS[@]} -eq $before ]]; then
        PYTHON_ATTEMPT_PATHS+=("$hint")
        PYTHON_ATTEMPT_RESULTS+=("каталог просмотрен, исполняемый Python ${expected_major}.${expected_minor} не найден")
    fi
    return 0
}

_pd_home_for_user() {
    local user="${1:-}" home=""
    [[ -n "$user" ]] || return 0
    if command -v getent >/dev/null 2>&1; then
        home="$(getent passwd "$user" 2>/dev/null | awk -F: 'NR==1{print $6}')"
    fi
    if [[ -z "$home" ]]; then
        home="$(eval printf '%s' "~$user" 2>/dev/null || true)"
    fi
    [[ -d "$home" ]] && printf '%s\n' "$home"
    return 0
}

_pd_add_home_candidates() {
    local home="${1:-}" expected_major="$2" expected_minor="$3" label="$4" run_user="${5:-}"
    local candidate cfg venv_root
    [[ -d "$home" ]] || return 0
    _pd_add_pyenv_root "$home/.pyenv" "$expected_major" "$expected_minor" "$label: pyenv" 0 "$run_user"
    for venv_root in \
        "$home/.venv" "$home/venv" "$home/env" \
        "$home/.local/opt/planner-solving/current/.venv" \
        "$home/.local/share/planner-solving/venv"; do
        _pd_add_hint "$venv_root" "$expected_major" "$expected_minor" "$label: venv" 0 "$run_user"
    done
    if [[ -d "$home/.virtualenvs" ]]; then
        while IFS= read -r candidate; do
            _pd_add_candidate "$candidate" "$label: virtualenv" 0 "$run_user"
        done < <(find "$home/.virtualenvs" -mindepth 2 -maxdepth 2 -path '*/bin/python' \( -type f -o -type l \) 2>/dev/null | sort)
    fi
    while IFS= read -r cfg; do
        venv_root="$(dirname "$cfg")"
        [[ -e "$venv_root/bin/python" ]] && _pd_add_candidate "$venv_root/bin/python" "$label: найденный venv" 0 "$run_user"
    done < <(find "$home" -maxdepth 4 -type f -name pyvenv.cfg 2>/dev/null | head -n 100)

    if [[ -d "$home/.asdf/installs/python" ]]; then
        while IFS= read -r candidate; do
            _pd_add_candidate "$candidate" "$label: asdf" 0 "$run_user"
        done < <(find "$home/.asdf/installs/python" -mindepth 3 -maxdepth 3 -path "*/${expected_major}.${expected_minor}*/bin/python*" -type f 2>/dev/null | sort -Vr)
    fi
    for candidate in \
        "$home/miniconda3/bin/python" "$home/anaconda3/bin/python" \
        "$home/mambaforge/bin/python" "$home/miniforge3/bin/python" \
        "$home"/miniconda3/envs/*/bin/python "$home"/anaconda3/envs/*/bin/python \
        "$home"/mambaforge/envs/*/bin/python "$home"/miniforge3/envs/*/bin/python; do
        [[ -e "$candidate" ]] && _pd_add_candidate "$candidate" "$label: conda" 0 "$run_user"
    done
    return 0
}

_pd_prefixes_for_candidate() {
    local candidate="$1" resolved prefix venv cfg_home
    prefix="$(cd "$(dirname "$candidate")/.." 2>/dev/null && pwd -P || true)"
    [[ -n "$prefix" ]] && printf '%s\n' "$prefix"
    venv="$(cd "$(dirname "$candidate")/.." 2>/dev/null && pwd -P || true)"
    if [[ -f "$venv/pyvenv.cfg" ]]; then
        cfg_home="$(sed -n 's/^[[:space:]]*home[[:space:]]*=[[:space:]]*//p' "$venv/pyvenv.cfg" | head -n1)"
        [[ -n "$cfg_home" ]] && printf '%s\n' "$(cd "$cfg_home/.." 2>/dev/null && pwd -P || true)"
    fi
    resolved="$(_pd_realpath "$candidate")"
    prefix="$(cd "$(dirname "$resolved")/.." 2>/dev/null && pwd -P || true)"
    [[ -n "$prefix" ]] && printf '%s\n' "$prefix"
}

_pd_guess_library_path() {
    local candidate="$1" expected_major="$2" expected_minor="$3" prefix directory found=""
    while IFS= read -r prefix; do
        [[ -n "$prefix" ]] || continue
        for directory in "$prefix/lib" "$prefix/lib64"; do
            if [[ -d "$directory" ]] && find "$directory" -maxdepth 1 -name "libpython${expected_major}.${expected_minor}.so*" -print -quit 2>/dev/null | grep -q .; then
                case ":$found:" in *":$directory:"*) ;; *) found="${found:+$found:}$directory" ;; esac
            fi
        done
        if [[ "$prefix" != /usr && "$prefix" != /usr/local && "$prefix" != / ]]; then
            while IFS= read -r directory; do
                case ":$found:" in *":$directory:"*) ;; *) found="${found:+$found:}$directory" ;; esac
            done < <(find "$prefix" -maxdepth 4 -type f -name "libpython${expected_major}.${expected_minor}.so*" -printf '%h\n' 2>/dev/null | sort -u)
        fi
    done < <(_pd_prefixes_for_candidate "$candidate" | awk 'NF && !seen[$0]++')
    printf '%s\n' "$found"
}

_pd_run_candidate() {
    local run_user="$1" candidate="$2" libpath="$3"
    shift 3
    local -a command=(env -u PYTHONHOME PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1)
    [[ -n "$libpath" ]] && command+=("LD_LIBRARY_PATH=$libpath${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}")
    command+=("$candidate" "$@")
    if [[ -n "$run_user" && $EUID -eq 0 && "$run_user" != root && "$run_user" != "$(id -un)" ]]; then
        run_as_user "$run_user" "${command[@]}"
    else
        "${command[@]}"
    fi
}

_pd_probe_candidate() {
    local candidate="$1" source="$2" expected_major="$3" expected_minor="$4" run_user="${5:-}"
    local output status libpath="" detail run_code
    [[ -f "$candidate" || -L "$candidate" ]] || { PYTHON_PROBE_ERROR="не является файлом"; return 1; }
    [[ -x "$candidate" ]] || { PYTHON_PROBE_ERROR="нет права выполнения"; return 1; }

    run_code='import ensurepip,platform,sqlite3,ssl,sys,venv; expected=(int(sys.argv[1]),int(sys.argv[2])); ok=sys.version_info[:2]==expected; print("\t".join(["%d.%d.%d"%sys.version_info[:3],sys.base_prefix,sys.executable,platform.machine().lower(),"1" if sys.prefix!=sys.base_prefix else "0"]) if ok else "VERSION=%d.%d"%sys.version_info[:2]); raise SystemExit(0 if ok else 42)'

    set +e
    output="$(_pd_run_candidate "$run_user" "$candidate" "" -c "$run_code" "$expected_major" "$expected_minor" 2>&1)"
    status=$?
    set -e
    if [[ $status -ne 0 ]]; then
        libpath="$(_pd_guess_library_path "$candidate" "$expected_major" "$expected_minor")"
        if [[ -n "$libpath" ]]; then
            set +e
            output="$(_pd_run_candidate "$run_user" "$candidate" "$libpath" -c "$run_code" "$expected_major" "$expected_minor" 2>&1)"
            status=$?
            set -e
        fi
    fi
    if [[ $status -ne 0 ]]; then
        detail="$(printf '%s' "$output" | tail -n 3 | tr '\n' ' ' | sed 's/[[:space:]]\+/ /g; s/^ //; s/ $//')"
        PYTHON_PROBE_ERROR="${detail:-код $status}"
        return 1
    fi

    IFS=$'\t' read -r PYTHON_SELECTED_VERSION PYTHON_SELECTED_BASE_PREFIX PYTHON_SELECTED_EXECUTABLE PYTHON_SELECTED_ARCH PYTHON_SELECTED_IS_VENV <<<"$output"
    PYTHON_SELECTED="$candidate"
    PYTHON_SELECTED_SOURCE="$source"
    PYTHON_SELECTED_LD_LIBRARY_PATH="$libpath"
    PYTHON_SELECTED_RUN_USER="$run_user"
    PYTHON_PROBE_ERROR=""
    return 0
}

python_exec_selected() {
    [[ -n "$PYTHON_SELECTED" ]] || { echo "Python не выбран" >&2; return 2; }
    _pd_run_candidate "$PYTHON_SELECTED_RUN_USER" "$PYTHON_SELECTED" "$PYTHON_SELECTED_LD_LIBRARY_PATH" "$@"
}

python_print_attempts() {
    local index
    if ((${#PYTHON_ATTEMPT_PATHS[@]} == 0)); then
        echo "Подходящие пути Python не обнаружены."
        return 0
    fi
    for index in "${!PYTHON_ATTEMPT_PATHS[@]}"; do
        printf '%-4s %s\n     %s\n' "$((index + 1))." "${PYTHON_ATTEMPT_PATHS[$index]}" "${PYTHON_ATTEMPT_RESULTS[$index]}"
    done
}

resolve_python_runtime() {
    local request="${1:-}" expected_major="$2" expected_minor="$3" install_root="$4" service_user="$5"
    local embedded="${6:-}" list_only="${7:-0}" strict="${8:-0}"
    local home user root index status any_ok=0 explicit_ok=0 invoking_user service_run_user explicit_user venv_note

    PYTHON_CANDIDATE_PATHS=(); PYTHON_CANDIDATE_KEYS=(); PYTHON_CANDIDATE_SOURCES=(); PYTHON_CANDIDATE_EXPLICIT=(); PYTHON_CANDIDATE_USERS=()
    PYTHON_ATTEMPT_PATHS=(); PYTHON_ATTEMPT_RESULTS=()
    PYTHON_SELECTED=""; PYTHON_SELECTED_SOURCE=""; PYTHON_SELECTED_LD_LIBRARY_PATH=""; PYTHON_SELECTED_RUN_USER=""

    invoking_user="$(_pd_existing_user "${PLANNER_INVOKING_USER:-${SUDO_USER:-}}")"
    service_run_user="$(_pd_existing_user "$service_user")"
    [[ "$request" == auto ]] && request=""
    explicit_user="$invoking_user"
    if [[ -n "$embedded" && -n "$request" && "$(_pd_realpath "$request")" == "$(_pd_realpath "$embedded")" ]]; then
        explicit_user=root
    fi
    [[ -n "$request" ]] && _pd_add_hint "$request" "$expected_major" "$expected_minor" "параметр --python" 1 "$explicit_user"

    if [[ -z "$request" || "$strict" != 1 ]]; then
        _pd_add_hint "$install_root/current/.venv" "$expected_major" "$expected_minor" "текущий venv Planner Solving" 0 "$service_run_user"
        if [[ -d "$install_root/releases" ]]; then
            while IFS= read -r root; do
                _pd_add_hint "$root/.venv" "$expected_major" "$expected_minor" "venv предыдущего выпуска Planner Solving" 0 "$service_run_user"
            done < <(find "$install_root/releases" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | sort -Vr | head -n 20)
        fi
        if [[ -d "$install_root/runtime" ]]; then
            while IFS= read -r root; do
                _pd_add_hint "$root" "$expected_major" "$expected_minor" "установленный runtime Planner Solving" 0 root
            done < <(find "$install_root/runtime" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | sort -Vr | head -n 20)
        fi

        [[ -n "${PLANNER_INVOKING_VIRTUAL_ENV:-}" ]] && _pd_add_hint "$PLANNER_INVOKING_VIRTUAL_ENV" "$expected_major" "$expected_minor" "активный venv исходного пользователя" 0 "$invoking_user"
        [[ -n "${VIRTUAL_ENV:-}" ]] && _pd_add_hint "$VIRTUAL_ENV" "$expected_major" "$expected_minor" "VIRTUAL_ENV" 0 "$invoking_user"
        [[ -n "${PLANNER_INVOKING_PYENV_ROOT:-}" ]] && _pd_add_pyenv_root "$PLANNER_INVOKING_PYENV_ROOT" "$expected_major" "$expected_minor" "pyenv исходного пользователя" 0 "$invoking_user"
        [[ -n "${PYENV_ROOT:-}" ]] && _pd_add_pyenv_root "$PYENV_ROOT" "$expected_major" "$expected_minor" "PYENV_ROOT" 0 "$invoking_user"
        if [[ -n "${PLANNER_INVOKING_PATH:-}" ]]; then
            IFS=':' read -r -a _pd_invoking_path <<<"$PLANNER_INVOKING_PATH"
            for root in "${_pd_invoking_path[@]:-}"; do
                [[ -n "$root" ]] || continue
                _pd_add_hint "$root/python${expected_major}.${expected_minor}" "$expected_major" "$expected_minor" "PATH исходного пользователя" 0 "$invoking_user"
                _pd_add_hint "$root/python3" "$expected_major" "$expected_minor" "PATH исходного пользователя" 0 "$invoking_user"
            done
        fi

        for user in "$invoking_user" "${SUDO_USER:-}" "$service_user" "$(id -un)" root; do
            user="$(_pd_existing_user "$user")"
            [[ -n "$user" ]] || continue
            home="$(_pd_home_for_user "$user")"
            [[ -n "$home" ]] && _pd_add_home_candidates "$home" "$expected_major" "$expected_minor" "пользователь $user" "$user"
        done
        [[ -n "${PLANNER_INVOKING_HOME:-}" ]] && _pd_add_home_candidates "$PLANNER_INVOKING_HOME" "$expected_major" "$expected_minor" "исходный пользователь" "$invoking_user"

        for home in /home/*; do
            [[ -d "$home" ]] || continue
            user="$(basename "$home")"
            user="$(_pd_existing_user "$user")"
            _pd_add_home_candidates "$home" "$expected_major" "$expected_minor" "домашний каталог $(basename "$home")" "$user"
        done

        IFS=':' read -r -a _pd_custom_roots <<<"${PLANNER_PYTHON_SEARCH_ROOTS:-}"
        for root in "${_pd_custom_roots[@]:-}"; do
            [[ -n "$root" ]] && _pd_add_hint "$root" "$expected_major" "$expected_minor" "дополнительный путь поиска" 0 "$invoking_user"
        done

        for root in \
            "/usr/bin/python${expected_major}.${expected_minor}" \
            "/usr/local/bin/python${expected_major}.${expected_minor}" \
            "/opt/python${expected_major}.${expected_minor}" \
            "/opt/python/${expected_major}.${expected_minor}" \
            "/opt/conda"; do
            _pd_add_hint "$root" "$expected_major" "$expected_minor" "системный путь" 0 root
        done
        _pd_add_hint "python${expected_major}.${expected_minor}" "$expected_major" "$expected_minor" "PATH" 0 "$invoking_user"
        _pd_add_hint python3 "$expected_major" "$expected_minor" "PATH" 0 "$invoking_user"

        [[ -n "$embedded" ]] && _pd_add_hint "$embedded" "$expected_major" "$expected_minor" "встроенный runtime пакета" 0 root
    fi

    for index in "${!PYTHON_CANDIDATE_PATHS[@]}"; do
        PYTHON_PROBE_ERROR=""
        if _pd_probe_candidate "${PYTHON_CANDIDATE_PATHS[$index]}" "${PYTHON_CANDIDATE_SOURCES[$index]}" "$expected_major" "$expected_minor" "${PYTHON_CANDIDATE_USERS[$index]}"; then
            status=0
        else
            status=$?
        fi
        if [[ $status -eq 0 ]]; then
            any_ok=1
            [[ "${PYTHON_CANDIDATE_EXPLICIT[$index]}" == 1 ]] && explicit_ok=1
            PYTHON_ATTEMPT_PATHS+=("${PYTHON_CANDIDATE_PATHS[$index]}")
            venv_note=""
            [[ "$PYTHON_SELECTED_IS_VENV" == 1 ]] && venv_note="; виртуальное окружение"
            PYTHON_ATTEMPT_RESULTS+=("OK ${PYTHON_SELECTED_VERSION}; ${PYTHON_CANDIDATE_SOURCES[$index]}${venv_note}${PYTHON_SELECTED_LD_LIBRARY_PATH:+; восстановлен LD_LIBRARY_PATH=$PYTHON_SELECTED_LD_LIBRARY_PATH}${PYTHON_SELECTED_RUN_USER:+; запуск от $PYTHON_SELECTED_RUN_USER}")
            if [[ "$list_only" != 1 ]]; then
                return 0
            fi
        else
            PYTHON_ATTEMPT_PATHS+=("${PYTHON_CANDIDATE_PATHS[$index]}")
            PYTHON_ATTEMPT_RESULTS+=("НЕ ПОДХОДИТ: $PYTHON_PROBE_ERROR; ${PYTHON_CANDIDATE_SOURCES[$index]}")
        fi
    done

    if [[ "$list_only" == 1 ]]; then
        python_print_attempts
        [[ $any_ok -eq 1 ]]
        return
    fi
    if [[ -n "$request" && "$strict" == 1 && $explicit_ok -eq 0 ]]; then
        echo "Явно указанный Python не подошёл: $request" >&2
    fi
    return 1
}
