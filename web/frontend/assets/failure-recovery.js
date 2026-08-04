const INSTALL_MARK = 'plannerFailureRecoveryInstalled';
const ACTIONABLE_CODES = new Set([
    'session_not_found',
    'session_corrupted',
    'uploaded_file_not_found',
    'storage_unavailable',
    'workspace_not_found',
    'workspace_error',
    'draft_revision_conflict',
    'draft_too_large',
    'replacement_rejected',
    'append_commit_failed',
    'replacement_commit_failed',
    'remove_commit_failed',
    'restore_commit_failed',
    'source_archive_missing',
    'output_write_failed',
    'processing_history_unavailable',
    'internal_error',
]);
let lastFailure = null;
let interceptorId = null;

function proxy() {
    return document.querySelector('#app')?.__vue_app__?._instance?.proxy || null;
}

function element(tag, className = '', text = '') {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text) node.textContent = text;
    return node;
}

function copyText(value) {
    const text = String(value || '');
    if (!text) return Promise.resolve(false);
    if (navigator.clipboard?.writeText) {
        return navigator.clipboard.writeText(text).then(() => true, () => false);
    }
    const area = element('textarea');
    area.value = text;
    area.style.position = 'fixed';
    area.style.opacity = '0';
    document.body.appendChild(area);
    area.select();
    const ok = document.execCommand('copy');
    area.remove();
    return Promise.resolve(ok);
}

function closeCenter() {
    document.querySelector('.failure-recovery-backdrop')?.remove();
}

function normalizedFailure(errorOrPayload) {
    const response = errorOrPayload?.response;
    const raw = response?.data || errorOrPayload || {};
    const payload = raw && typeof raw === 'object' ? raw : { detail: String(raw) };
    const recovery = payload.recovery && typeof payload.recovery === 'object'
        ? payload.recovery
        : {};
    return {
        status: Number(response?.status || payload.status || 0),
        code: String(payload.code || recovery.code || 'internal_error'),
        incidentId: String(payload.incident_id || recovery.incident_id || ''),
        detail: String(payload.detail || recovery.detail || 'Операция не выполнена.'),
        recovery,
        requestConfig: response ? errorOrPayload.config : payload.requestConfig,
    };
}

function shouldOpen(value) {
    return value.recovery?.severity === 'critical'
        || value.status >= 500
        || ACTIONABLE_CODES.has(value.code);
}

function formatBytes(value) {
    const bytes = Number(value || 0);
    if (!Number.isFinite(bytes) || bytes <= 0) return '0 Б';
    const units = ['Б', 'КБ', 'МБ', 'ГБ', 'ТБ'];
    const index = Math.min(units.length - 1, Math.floor(Math.log(bytes) / Math.log(1024)));
    return `${(bytes / (1024 ** index)).toFixed(index ? 1 : 0)} ${units[index]}`;
}

async function loadDiagnostics(target = '/api/system/recovery') {
    const response = await fetch(target, { credentials: 'same-origin', cache: 'no-store' });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
    return data;
}

function renderDiagnostics(container, data) {
    container.replaceChildren();
    const header = element('div', 'failure-diagnostics-header');
    header.append(
        element('strong', '', data.status === 'ok' ? 'Система готова к повтору' : 'Диагностика обнаружила проблемы'),
        element('small', '', `Версия ${data.app_version || 'не определена'} · активных сеансов: ${data.active_session_count ?? '—'}`),
    );
    container.appendChild(header);

    const list = element('div', 'failure-diagnostics-list');
    for (const check of data.checks || []) {
        const row = element('article', `failure-diagnostic ${check.ok ? 'ok' : check.severity || 'warning'}`);
        const badge = element('span', 'failure-diagnostic-badge', check.ok ? '✓' : '!');
        const copy = element('div');
        copy.append(element('strong', '', check.title || check.code), element('p', '', check.message || ''));
        if (check.tool) copy.appendChild(element('small', '', `Что сделать: ${check.tool}`));
        row.append(badge, copy);
        list.appendChild(row);
    }
    container.appendChild(list);

    if ((data.admin_commands || []).length) {
        const commands = element('div', 'failure-command-list');
        commands.appendChild(element('strong', '', 'Команды для администратора'));
        for (const command of data.admin_commands) {
            const row = element('div', 'failure-command');
            row.append(element('code', '', command));
            const button = element('button', 'btn btn-secondary btn-small', 'Копировать');
            button.type = 'button';
            button.addEventListener('click', async () => {
                await copyText(command);
                proxy()?.addToast?.('Команда скопирована', command, 'success');
            });
            row.appendChild(button);
            commands.appendChild(row);
        }
        container.appendChild(commands);
    }
}

async function retryRequest(failure) {
    const app = proxy();
    const config = failure.requestConfig;
    if (!config) {
        closeCenter();
        app?.addToast?.(
            'Повторите действие',
            'Автоматический повтор для этой операции недоступен. Текущий сеанс сохранён; повторите исходную команду в интерфейсе.',
            'info',
        );
        return;
    }
    closeCenter();
    try {
        if (config.transport === 'fetch') {
            const response = await fetch(config.input, config.init || {});
            if (!response.ok) return;
        } else if (window.axios) {
            await window.axios({ ...config, headers: { ...(config.headers || {}) } });
        } else {
            throw new Error('Клиент запросов недоступен');
        }
        app?.addToast?.('Повтор выполнен', 'Операция завершилась без критической ошибки.', 'success');
    } catch (_) {
        // The interceptors open the current failure with a new incident id.
    }
}

async function executeAction(action, failure, diagnostics) {
    const app = proxy();
    const type = String(action?.type || '');
    if (type === 'retry_request') {
        await retryRequest(failure);
        return;
    }
    if (type === 'open_diagnostics') {
        diagnostics.hidden = false;
        diagnostics.replaceChildren(element('div', 'failure-diagnostics-loading', 'Проверяем хранилище и базу данных…'));
        try {
            renderDiagnostics(diagnostics, await loadDiagnostics(action.target));
        } catch (error) {
            diagnostics.replaceChildren(element('div', 'failure-diagnostics-error', `Диагностика недоступна: ${error.message}`));
        }
        return;
    }
    if (type === 'copy_admin_command') {
        const ok = await copyText(action.command);
        app?.addToast?.(ok ? 'Команда скопирована' : 'Не удалось скопировать', action.command || '', ok ? 'success' : 'warning');
        return;
    }
    if (type === 'copy_incident_id') {
        const ok = await copyText(failure.incidentId);
        app?.addToast?.(ok ? 'Код инцидента скопирован' : 'Не удалось скопировать', failure.incidentId, ok ? 'success' : 'warning');
        return;
    }
    if (type === 'start_new_session') {
        closeCenter();
        if (typeof app?.resetWorkflow === 'function') await app.resetWorkflow();
        else {
            localStorage.removeItem('planner-active-session-v1');
            window.location.reload();
        }
        return;
    }
    if (type === 'restore_server_draft') {
        closeCenter();
        if (window.__plannerSessionDraft?.restore) await window.__plannerSessionDraft.restore();
        else app?.addToast?.('Черновик', 'Обновите страницу: сохранённый черновик будет восстановлен автоматически.', 'info');
        return;
    }
    if (type === 'open_history') {
        closeCenter();
        if (typeof app?.openOperations === 'function') app.openOperations('history');
        else if (app) {
            app.operationsOpen = true;
            app.operationsTab = 'history';
        }
        return;
    }
    if (type === 'refresh_workspaces') {
        await app?.loadSpaces?.();
        await app?.loadData?.();
        app?.addToast?.('Список обновлён', 'Выберите доступное рабочее пространство.', 'success');
        return;
    }
    if (type === 'open_workspace_data') {
        closeCenter();
        window.dispatchEvent(new CustomEvent('planner:open-workspace-data', { detail: { tab: 'spaces' } }));
        return;
    }
    if (type === 'replace_current_file') {
        closeCenter();
        if (!app) return;
        app.step = 2;
        await Vue.nextTick();
        const input = document.querySelector('.file-item.selected .file-session-actions input[type="file"]')
            || document.querySelector('.file-item.selected input[type="file"]');
        if (input) input.click();
        else app.addToast?.('Замена файла', 'Откройте нужный файл в списке и нажмите «Заменить».', 'info');
        return;
    }
    if (type === 'generate_now') {
        closeCenter();
        if (typeof app?.generate === 'function') await app.generate();
        else app?.addToast?.('Формирование', 'Вернитесь к редактору и нажмите «Сформировать результат».', 'info');
        return;
    }
    if (type === 'review_session_files') {
        closeCenter();
        if (!app) return;
        app.step = 2;
        await Vue.nextTick();
        document.querySelector('.file-list')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
        return;
    }
    if (type === 'reload_page') {
        window.location.reload();
        return;
    }
    if (type === 'keep_current_tab') {
        closeCenter();
        return;
    }
    if (action?.target?.startsWith('/')) {
        window.location.assign(action.target);
        return;
    }
    app?.addToast?.('Способ решения', action?.description || action?.label || 'Следуйте рекомендации в окне.', 'info');
}

function showCenter(errorOrPayload) {
    const failure = normalizedFailure(errorOrPayload);
    if (!shouldOpen(failure)) return;
    const fingerprint = `${failure.incidentId}:${failure.code}`;
    if (lastFailure === fingerprint && document.querySelector('.failure-recovery-backdrop')) return;
    lastFailure = fingerprint;
    closeCenter();

    const recovery = failure.recovery || {};
    const backdrop = element('div', 'failure-recovery-backdrop');
    backdrop.setAttribute('role', 'presentation');
    const dialog = element('section', 'failure-recovery-dialog');
    dialog.setAttribute('role', 'dialog');
    dialog.setAttribute('aria-modal', 'true');
    dialog.setAttribute('aria-labelledby', 'failure-recovery-title');

    const header = element('header', 'failure-recovery-header');
    const symbol = element('div', `failure-recovery-symbol ${recovery.severity || 'critical'}`, '!');
    const heading = element('div');
    const eyebrow = element('span', 'failure-recovery-eyebrow', 'Неисправность локализована');
    const title = element('h2', '', recovery.title || 'Операция не выполнена');
    title.id = 'failure-recovery-title';
    heading.append(eyebrow, title);
    const close = element('button', 'failure-recovery-close', '×');
    close.type = 'button';
    close.setAttribute('aria-label', 'Закрыть');
    close.addEventListener('click', closeCenter);
    header.append(symbol, heading, close);

    const body = element('div', 'failure-recovery-body');
    body.append(element('p', 'failure-recovery-detail', failure.detail));
    if (recovery.guidance) body.append(element('p', 'failure-recovery-guidance', recovery.guidance));

    const facts = element('div', 'failure-recovery-facts');
    facts.append(
        element('span', recovery.state_preserved === false ? 'lost' : 'preserved', recovery.state_preserved === false ? 'Сеанс недоступен' : 'Текущая работа сохранена'),
        element('span', recovery.retryable ? 'retryable' : 'manual', recovery.retryable ? 'Можно повторить' : 'Нужно выбрать другой путь'),
    );
    body.appendChild(facts);

    if (failure.code || failure.incidentId) {
        const technical = element('details', 'failure-recovery-technical');
        technical.appendChild(element('summary', '', 'Технические сведения'));
        const values = element('div');
        values.append(
            element('code', '', `Код: ${failure.code}`),
            element('code', '', `Инцидент: ${failure.incidentId || 'не выдан'}`),
        );
        technical.appendChild(values);
        body.appendChild(technical);
    }

    const diagnostics = element('section', 'failure-diagnostics');
    diagnostics.hidden = true;
    body.appendChild(diagnostics);

    const footer = element('footer', 'failure-recovery-actions');
    const actions = Array.isArray(recovery.actions) ? recovery.actions : [];
    for (const action of actions) {
        const button = element('button', `btn ${action.primary ? 'btn-primary' : 'btn-secondary'}`, action.label || 'Выполнить');
        button.type = 'button';
        button.title = action.description || '';
        button.addEventListener('click', () => executeAction(action, failure, diagnostics));
        footer.appendChild(button);
    }
    if (!actions.length) {
        const retry = element('button', 'btn btn-primary', 'Перезагрузить страницу');
        retry.type = 'button';
        retry.addEventListener('click', () => window.location.reload());
        footer.appendChild(retry);
    }
    const dismiss = element('button', 'btn btn-secondary', 'Закрыть и остаться');
    dismiss.type = 'button';
    dismiss.addEventListener('click', closeCenter);
    footer.appendChild(dismiss);

    dialog.append(header, body, footer);
    backdrop.appendChild(dialog);
    backdrop.addEventListener('click', event => {
        if (event.target === backdrop) closeCenter();
    });
    document.body.appendChild(backdrop);
    window.requestAnimationFrame(() => dialog.querySelector('button')?.focus());
}

export function installFailureRecovery() {
    const root = document.documentElement;
    if (root.dataset[INSTALL_MARK] === '1') return;
    root.dataset[INSTALL_MARK] = '1';
    if (window.axios?.interceptors?.response) {
        interceptorId = window.axios.interceptors.response.use(
            response => response,
            error => {
                showCenter(error);
                return Promise.reject(error);
            },
        );
    }
    window.addEventListener('planner:failure', event => showCenter(event.detail || {}));
    window.__plannerFailureRecovery = {
        show: showCenter,
        close: closeCenter,
        diagnostics: loadDiagnostics,
        uninstall: () => {
            if (interceptorId !== null) window.axios?.interceptors?.response?.eject(interceptorId);
            closeCenter();
        },
    };
}

export { formatBytes };
