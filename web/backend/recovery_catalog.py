"""Safe operator recovery guidance for API and infrastructure failures.

The catalog intentionally contains no stack traces, filesystem secrets or raw
exceptions.  It converts stable error codes into a small action vocabulary that
both the web UI and command-line diagnostics can execute or explain.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Mapping, Sequence


Action = Dict[str, Any]


def _action(
    action_type: str,
    label: str,
    description: str,
    *,
    primary: bool = False,
    target: str | None = None,
    command: str | None = None,
    requires_admin: bool = False,
) -> Action:
    value: Action = {
        "type": action_type,
        "label": label,
        "description": description,
        "primary": primary,
        "requires_admin": requires_admin,
    }
    if target:
        value["target"] = target
    if command:
        value["command"] = command
    return value


DIAGNOSTIC_ACTION = _action(
    "open_diagnostics",
    "Открыть диагностику",
    "Проверить хранилище, свободное место, базу данных и каталоги записи.",
    target="/api/system/recovery",
)
DOCTOR_ACTION = _action(
    "copy_admin_command",
    "Скопировать команду диагностики",
    "Передать администратору отчёт штатной диагностики установки.",
    command="sudo planner-solving-doctor --output /tmp/planner-solving-doctor.txt",
    requires_admin=True,
)
REPAIR_ACTION = _action(
    "copy_admin_command",
    "Скопировать команду восстановления",
    "Переустановить активный выпуск и виртуальное окружение без удаления рабочих данных.",
    command="sudo ./install-planner-solving.sh --python bundled --strict-python --repair",
    requires_admin=True,
)


CATALOG: Dict[str, Dict[str, Any]] = {
    "session_not_found": {
        "title": "Сеанс больше недоступен",
        "severity": "critical",
        "retryable": False,
        "state_preserved": False,
        "guidance": (
            "Временный сеанс истёк или был удалён. Проверьте историю завершённых запусков; "
            "если нужного запуска там нет, создайте новый сеанс и добавьте исходники заново."
        ),
        "actions": [
            _action("open_history", "Открыть историю", "Найти сформированные результаты и архивные исходники.", primary=True),
            _action("start_new_session", "Начать новый сеанс", "Очистить устаревшую ссылку и открыть загрузку файлов."),
        ],
    },
    "session_corrupted": {
        "title": "Черновик сеанса повреждён",
        "severity": "critical",
        "retryable": False,
        "state_preserved": True,
        "guidance": (
            "Автоматическое восстановление состояния невозможно, но исходные файлы могут оставаться на сервере. "
            "Не удаляйте каталог сеанса до получения диагностического отчёта."
        ),
        "actions": [DIAGNOSTIC_ACTION, DOCTOR_ACTION, _action("start_new_session", "Создать новый сеанс", "Продолжить работу с исправными копиями файлов.")],
    },
    "uploaded_file_not_found": {
        "title": "Исходный или готовый файл не найден",
        "severity": "technical",
        "retryable": True,
        "state_preserved": True,
        "guidance": (
            "Остальная работа сохранена. Вернитесь к списку исходников, замените только отсутствующий файл "
            "или повторите формирование из истории."
        ),
        "actions": [
            _action("replace_current_file", "Заменить файл", "Выбрать исправную копию только для текущей записи.", primary=True),
            _action("open_history", "Открыть историю", "Повторить завершённый запуск с архивными исходниками."),
            _action("retry_request", "Повторить", "Проверить, не был ли отказ временным."),
        ],
    },
    "storage_unavailable": {
        "title": "Хранилище данных недоступно",
        "severity": "critical",
        "retryable": True,
        "state_preserved": True,
        "guidance": (
            "Новые изменения не записываются. Не начинайте новый сеанс: восстановите доступ к диску, "
            "права каталогов или SQLite, затем повторите операцию в текущем окне."
        ),
        "actions": [DIAGNOSTIC_ACTION, _action("retry_request", "Проверить ещё раз", "Повторить запрос после устранения причины.", primary=True), DOCTOR_ACTION, REPAIR_ACTION],
    },
    "workspace_not_found": {
        "title": "Рабочее пространство не найдено",
        "severity": "technical",
        "retryable": True,
        "state_preserved": True,
        "guidance": "Обновите список пространств и выберите существующее. Исходники активного сеанса не удаляются.",
        "actions": [
            _action("refresh_workspaces", "Обновить пространства", "Загрузить актуальный список и выбрать доступное.", primary=True),
            _action("open_workspace_data", "Открыть данные", "Проверить параметры и основное пространство."),
        ],
    },
    "workspace_error": {
        "title": "Данные пространства требуют восстановления",
        "severity": "critical",
        "retryable": True,
        "state_preserved": True,
        "guidance": (
            "Операция с данными отменена. Проверьте SQLite, версию схемы и последний резервный снимок; "
            "после восстановления повторите действие."
        ),
        "actions": [DIAGNOSTIC_ACTION, DOCTOR_ACTION, REPAIR_ACTION],
    },
    "draft_revision_conflict": {
        "title": "Черновик изменён в другой вкладке",
        "severity": "technical",
        "retryable": True,
        "state_preserved": True,
        "guidance": (
            "Ни одна версия не перезаписана. Сначала восстановите серверный черновик, затем повторите "
            "нужные изменения в одной вкладке."
        ),
        "actions": [
            _action("restore_server_draft", "Восстановить серверный черновик", "Загрузить последнюю сохранённую ревизию.", primary=True),
            _action("keep_current_tab", "Оставить текущее окно", "Закрыть другие вкладки и повторить сохранение вручную."),
        ],
    },
    "draft_too_large": {
        "title": "Черновик превышает допустимый размер",
        "severity": "technical",
        "retryable": True,
        "state_preserved": True,
        "guidance": (
            "Последняя серверная версия сохранена. Сформируйте промежуточный результат либо уберите из сеанса "
            "ненужные файлы; удалённый файл можно сразу вернуть."
        ),
        "actions": [
            _action("generate_now", "Сформировать текущий результат", "Зафиксировать пригодные данные в истории.", primary=True),
            _action("review_session_files", "Просмотреть файлы", "Отключить или временно убрать лишние книги."),
        ],
    },
    "replacement_rejected": {
        "title": "Новая копия файла не принята",
        "severity": "technical",
        "retryable": True,
        "state_preserved": True,
        "guidance": "Прежний файл и все ручные правки сохранены. Выберите исправную книгу .xlsx или .xlsm.",
        "actions": [_action("replace_current_file", "Выбрать другую копию", "Повторить замену только этого файла.", primary=True)],
    },
    "append_commit_failed": {
        "title": "Новые файлы не добавлены",
        "severity": "critical",
        "retryable": True,
        "state_preserved": True,
        "guidance": "Прежний состав сеанса не изменён. Проверьте хранилище и повторите добавление.",
        "actions": [DIAGNOSTIC_ACTION, _action("retry_request", "Повторить добавление", "Отправить те же файлы повторно.", primary=True), DOCTOR_ACTION],
    },
    "replacement_commit_failed": {
        "title": "Замена файла не завершена",
        "severity": "critical",
        "retryable": True,
        "state_preserved": True,
        "guidance": "Прежний исходник восстановлен. После проверки хранилища повторите замену.",
        "actions": [DIAGNOSTIC_ACTION, _action("replace_current_file", "Повторить замену", "Выбрать новую копию ещё раз.", primary=True), DOCTOR_ACTION],
    },
    "remove_commit_failed": {
        "title": "Файл не убран",
        "severity": "critical",
        "retryable": True,
        "state_preserved": True,
        "guidance": "Файл и прежний состав сеанса восстановлены. После проверки хранилища повторите действие.",
        "actions": [DIAGNOSTIC_ACTION, _action("retry_request", "Повторить", "Снова убрать выбранный файл.", primary=True)],
    },
    "restore_commit_failed": {
        "title": "Файл пока не восстановлен",
        "severity": "critical",
        "retryable": True,
        "state_preserved": True,
        "guidance": "Файл остаётся в корзине сеанса и не потерян. Проверьте хранилище и повторите восстановление.",
        "actions": [DIAGNOSTIC_ACTION, _action("retry_request", "Повторить восстановление", "Вернуть файл из корзины ещё раз.", primary=True)],
    },
    "source_archive_missing": {
        "title": "Архивный исходник недоступен",
        "severity": "technical",
        "retryable": False,
        "state_preserved": True,
        "guidance": (
            "Историческая запись сохранена, но исходный файл отсутствует. Добавьте актуальную копию в новый "
            "сеанс или восстановите каталог shared/data/history из резервной копии."
        ),
        "actions": [
            _action("start_new_session", "Добавить актуальные файлы", "Создать сеанс без изменения истории.", primary=True),
            DOCTOR_ACTION,
        ],
    },
    "output_write_failed": {
        "title": "Готовый файл не записан",
        "severity": "critical",
        "retryable": True,
        "state_preserved": True,
        "guidance": (
            "Исходники, разметка и решения сохранены в текущем черновике. Освободите место или исправьте "
            "права каталога output, затем нажмите «Сформировать результат» повторно."
        ),
        "actions": [DIAGNOSTIC_ACTION, _action("generate_now", "Повторить формирование", "Создать результат из сохранённого сеанса.", primary=True), DOCTOR_ACTION],
    },
    "processing_history_unavailable": {
        "title": "История запуска временно недоступна",
        "severity": "technical",
        "retryable": True,
        "state_preserved": True,
        "guidance": (
            "Формирование может продолжиться без записи истории. После восстановления базы повторите запуск, "
            "если требуется архивный след."
        ),
        "actions": [DIAGNOSTIC_ACTION, _action("retry_request", "Повторить запись", "Повторить действие после восстановления SQLite."), DOCTOR_ACTION],
    },
    "internal_error": {
        "title": "Внутренняя ошибка приложения",
        "severity": "critical",
        "retryable": True,
        "state_preserved": True,
        "guidance": (
            "Текущий запрос отменён, но приложение не удаляет активный сеанс. Повторите действие один раз; "
            "при повторении передайте администратору код инцидента и диагностический отчёт."
        ),
        "actions": [
            _action("retry_request", "Повторить один раз", "Повторить исходную операцию без перезагрузки страницы.", primary=True),
            DIAGNOSTIC_ACTION,
            _action("copy_incident_id", "Скопировать код инцидента", "Приложить код к журналу и обращению."),
            DOCTOR_ACTION,
        ],
    },
}


def recovery_for(
    code: str,
    *,
    detail: str,
    incident_id: str | None = None,
    request_path: str | None = None,
    overrides: Mapping[str, Any] | None = None,
    extra_actions: Sequence[Mapping[str, Any]] = (),
) -> Dict[str, Any]:
    """Return a JSON-safe recovery descriptor for a stable error code."""

    base = deepcopy(CATALOG.get(code, CATALOG["internal_error"]))
    base["code"] = code
    base["detail"] = detail
    base["incident_id"] = incident_id
    base["request_path"] = request_path
    actions = list(base.get("actions") or [])
    for raw in extra_actions:
        action = dict(raw)
        if action and action not in actions:
            actions.append(action)
    base["actions"] = actions
    if overrides:
        for key, value in overrides.items():
            if key == "actions":
                continue
            base[key] = value
    return base


def compact_recommendations(codes: Sequence[str]) -> list[Dict[str, Any]]:
    """Return deduplicated CLI/UI recommendations for diagnostics output."""

    result: list[Dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for code in codes:
        item = recovery_for(code, detail="")
        for action in item.get("actions") or []:
            key = (str(action.get("type")), str(action.get("label")))
            if key in seen:
                continue
            seen.add(key)
            result.append(action)
    return result
