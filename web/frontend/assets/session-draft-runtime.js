const STORAGE_KEY = 'planner-active-session-v1';
const SAVE_DELAY_MS = 750;
const DRAFT_VERSION = 1;

let installed = false;
let proxy = null;
let saveTimer = null;
let stopStateWatch = null;
let stopRestoreWatch = null;
let revision = 0;
let lastSavedSignature = '';
let restoring = false;
let saving = false;
let conflict = false;
let restoreCompleted = false;
let statusNode = null;

function clone(value, fallback = null) {
    try {
        return JSON.parse(JSON.stringify(value));
    } catch (_) {
        return fallback;
    }
}

function clearObject(value) {
    if (!value || typeof value !== 'object') return;
    Object.keys(value).forEach(key => delete value[key]);
}

function currentProxy() {
    const app = document.querySelector('#app')?.__vue_app__;
    return app?._instance?.proxy || null;
}

function ensureStatusNode() {
    if (statusNode?.isConnected) return statusNode;
    const parent = document.querySelector('.readiness-copy') || document.querySelector('.topbar');
    if (!parent) return null;
    statusNode = document.createElement('button');
    statusNode.type = 'button';
    statusNode.className = 'server-draft-status';
    statusNode.hidden = true;
    statusNode.addEventListener('click', () => {
        if (conflict) {
            const replace = window.confirm(
                'Серверный черновик изменён в другой вкладке. Восстановить его и заменить текущее состояние этого экрана?'
            );
            if (replace) restoreDraft({ force: true });
            return;
        }
        flushDraft({ force: true });
    });
    parent.appendChild(statusNode);
    return statusNode;
}

function setStatus(kind, label, title = '') {
    const node = ensureStatusNode();
    if (!node) return;
    node.hidden = !label;
    node.className = `server-draft-status ${kind || ''}`.trim();
    node.textContent = label;
    node.title = title;
}

function fileIds() {
    return new Set((proxy?.analyzedFiles || []).map(file => String(file.file_id || '')).filter(Boolean));
}

function selectedMappings(source, allowed) {
    const result = {};
    if (!source || typeof source !== 'object') return result;
    for (const [key, value] of Object.entries(source)) {
        if (allowed.has(String(key)) && value && typeof value === 'object') {
            result[String(key)] = clone(value, {});
        }
    }
    return result;
}

function draftState() {
    if (!proxy?.sessionId) return null;
    const allowed = fileIds();
    return {
        version: DRAFT_VERSION,
        base_revision: revision,
        workspace_id: String(proxy.activeWorkspaceId || '') || null,
        step: Math.max(1, Math.min(3, Number(proxy.step || 1))),
        selected_file_id: allowed.has(String(proxy.selectedFileId || ''))
            ? String(proxy.selectedFileId)
            : null,
        file_states: (proxy.analyzedFiles || []).map(file => ({
            file_id: String(file.file_id || ''),
            group_name: String(file.group_name || ''),
            enabled: Boolean(file.enabled)
        })),
        layouts: selectedMappings(proxy.layouts, allowed),
        validations: selectedMappings(proxy.validations, allowed),
        period_overrides: selectedMappings(proxy.periodOverrides, allowed),
        calendar_overrides: clone(proxy.calendarOverrides, {}),
        result: clone(proxy.result, null),
        editor: {
            preview_region: String(proxy.previewRegion || 'schedule'),
            period_editor_open: Boolean(proxy.periodEditorOpen),
            sheet_workspace_open: Boolean(proxy.sheetWorkspaceOpen)
        }
    };
}

function signature(value) {
    if (!value) return '';
    const comparable = { ...value };
    delete comparable.base_revision;
    return JSON.stringify(comparable);
}

function scheduleSave() {
    if (restoring || conflict || !proxy) return;
    window.clearTimeout(saveTimer);
    const sessionId = String(proxy.sessionId || '');
    if (!sessionId) {
        localStorage.removeItem(STORAGE_KEY);
        revision = 0;
        lastSavedSignature = '';
        setStatus('', '');
        return;
    }
    localStorage.setItem(STORAGE_KEY, sessionId);
    const state = draftState();
    if (!state || signature(state) === lastSavedSignature) return;
    setStatus('pending', 'Сохраняем черновик…', 'Изменения будут сохранены на сервере автоматически.');
    saveTimer = window.setTimeout(() => flushDraft(), SAVE_DELAY_MS);
}

async function readJson(response) {
    try {
        return await response.json();
    } catch (_) {
        return {};
    }
}

async function flushDraft({ force = false, keepalive = false } = {}) {
    if (!proxy || restoring || saving || conflict) return false;
    const sessionId = String(proxy.sessionId || '');
    const state = draftState();
    if (!sessionId || !state) return false;
    const nextSignature = signature(state);
    if (!force && nextSignature === lastSavedSignature) return true;

    saving = true;
    setStatus('saving', 'Сохраняем черновик…');
    try {
        const response = await fetch(`/api/analysis/${sessionId}/draft`, {
            method: 'PUT',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(state),
            keepalive
        });
        const data = await readJson(response);
        if (response.status === 409) {
            conflict = true;
            setStatus(
                'conflict',
                'Черновик изменён в другой вкладке',
                'Нажмите, чтобы восстановить серверную версию.'
            );
            proxy.addToast?.(
                'Конфликт черновика',
                data.detail || 'Серверный черновик изменён в другой вкладке. Текущее состояние не перезаписано.',
                'warning'
            );
            return false;
        }
        if (response.status === 404) {
            localStorage.removeItem(STORAGE_KEY);
            setStatus('expired', 'Сеанс истёк', 'Исходные файлы на сервере больше недоступны.');
            return false;
        }
        if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
        revision = Number(data.revision || revision + 1);
        lastSavedSignature = nextSignature;
        conflict = false;
        localStorage.setItem(STORAGE_KEY, sessionId);
        const savedTime = data.saved_at ? new Date(data.saved_at) : new Date();
        setStatus(
            'saved',
            'Черновик сохранён',
            `Сохранено на сервере: ${savedTime.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })}`
        );
        return true;
    } catch (error) {
        console.warn('[planner] operator draft was not saved', error);
        setStatus('offline', 'Черновик ожидает сохранения', 'Повтор будет выполнен после восстановления связи.');
        return false;
    } finally {
        saving = false;
    }
}

function normalizedFiles(files, state) {
    const fileStates = new Map((state.file_states || []).map(item => [String(item.file_id), item]));
    return (files || []).map(item => {
        const saved = fileStates.get(String(item.file_id)) || {};
        return {
            ...item,
            group_name: saved.group_name || item.group_name,
            enabled: saved.enabled ?? Boolean(item.analysis),
            matching: false,
            template_match: item.template_match || null,
            template_candidates: []
        };
    });
}

function replaceReactiveObject(target, source) {
    clearObject(target);
    Object.assign(target, clone(source, {}));
}

async function applyDraft(sessionId, response) {
    const state = response.draft;
    if (!state || !Array.isArray(response.files)) return false;
    restoring = true;
    try {
        const workspaceId = String(state.workspace_id || '');
        if (workspaceId && workspaceId !== String(proxy.activeWorkspaceId || '')) {
            await proxy.switchWorkspace?.(workspaceId);
        }

        proxy.sessionId = sessionId;
        const files = normalizedFiles(response.files, state);
        proxy.analyzedFiles.splice(0, proxy.analyzedFiles.length, ...files);
        replaceReactiveObject(proxy.layouts, state.layouts || {});
        replaceReactiveObject(proxy.validations, state.validations || {});
        replaceReactiveObject(proxy.periodOverrides, state.period_overrides || {});

        if (proxy.calendarOverrides) {
            proxy.calendarOverrides.policy = state.calendar_overrides?.policy || 'auto';
            replaceReactiveObject(
                proxy.calendarOverrides.week_day_dates,
                state.calendar_overrides?.week_day_dates || {}
            );
            replaceReactiveObject(
                proxy.calendarOverrides.week_months,
                state.calendar_overrides?.week_months || {}
            );
        }

        const allowed = new Set(files.map(file => String(file.file_id)));
        const preferred = String(state.selected_file_id || '');
        proxy.selectedFileId = allowed.has(preferred)
            ? preferred
            : (files.find(file => file.analysis)?.file_id || null);
        proxy.previewRegion = state.editor?.preview_region || 'schedule';
        proxy.periodEditorOpen = Boolean(state.editor?.period_editor_open);
        proxy.result = clone(state.result, null);
        proxy.step = Math.max(1, Math.min(3, Number(state.step || 1)));
        revision = Number(response.revision || 0);
        conflict = false;
        localStorage.setItem(STORAGE_KEY, sessionId);
        lastSavedSignature = signature(draftState());
    } finally {
        restoring = false;
    }

    await Vue.nextTick();
    const selected = (proxy.analyzedFiles || []).find(
        file => String(file.file_id) === String(proxy.selectedFileId || '')
    );
    if (proxy.step >= 2 && selected?.analysis) {
        try {
            await proxy.loadPreview?.();
        } catch (_) {
            // The draft itself is still restored even when preview rendering fails.
        }
    }
    setStatus('saved', 'Черновик восстановлен', 'Состояние загружено с сервера.');
    proxy.addToast?.(
        'Черновик восстановлен',
        `Возвращены файлы: ${response.files.length}. Разметка и решения доступны для продолжения.`,
        'success'
    );
    return true;
}

async function restoreDraft({ force = false } = {}) {
    if (!proxy || restoring || saving) return false;
    if (proxy.sessionId && !force) return false;
    const sessionId = localStorage.getItem(STORAGE_KEY);
    if (!sessionId) {
        restoreCompleted = true;
        return false;
    }

    setStatus('restoring', 'Восстанавливаем черновик…');
    try {
        const response = await fetch(`/api/analysis/${sessionId}/draft`, {
            credentials: 'same-origin',
            cache: 'no-store'
        });
        const data = await readJson(response);
        if (response.status === 401 || response.status === 403) {
            setStatus('', '');
            return false;
        }
        if (response.status === 404) {
            localStorage.removeItem(STORAGE_KEY);
            setStatus('', '');
            restoreCompleted = true;
            return false;
        }
        if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
        if (!data.draft) {
            localStorage.removeItem(STORAGE_KEY);
            setStatus('', '');
            restoreCompleted = true;
            return false;
        }
        const restored = await applyDraft(sessionId, data);
        restoreCompleted = restored;
        return restored;
    } catch (error) {
        console.warn('[planner] operator draft was not restored', error);
        setStatus('offline', 'Черновик временно недоступен', 'Система повторит восстановление после входа или появления связи.');
        return false;
    }
}

function installWatchers() {
    stopStateWatch = Vue.watch(
        () => JSON.stringify({
            sessionId: proxy.sessionId,
            workspaceId: proxy.activeWorkspaceId,
            step: proxy.step,
            selectedFileId: proxy.selectedFileId,
            files: proxy.analyzedFiles,
            layouts: proxy.layouts,
            validations: proxy.validations,
            periods: proxy.periodOverrides,
            calendar: proxy.calendarOverrides,
            result: proxy.result,
            editor: [proxy.previewRegion, proxy.periodEditorOpen, proxy.sheetWorkspaceOpen]
        }),
        scheduleSave,
        { flush: 'post' }
    );

    stopRestoreWatch = Vue.watch(
        () => JSON.stringify({
            workspaceId: proxy.activeWorkspaceId,
            userId: proxy.currentUser?.id || null,
            authenticated: proxy.authStatus?.authenticated || false,
            setupAccess: proxy.authStatus?.setup_access || false
        }),
        () => {
            if (!restoreCompleted && !proxy.sessionId) restoreDraft();
        },
        { immediate: true, flush: 'post' }
    );
}

export function installSessionDraftRuntime() {
    if (installed) return;
    proxy = currentProxy();
    if (!proxy) {
        window.setTimeout(installSessionDraftRuntime, 50);
        return;
    }
    installed = true;
    installWatchers();

    const observer = new MutationObserver(() => {
        if (proxy?.sessionId) ensureStatusNode();
    });
    observer.observe(document.querySelector('#app'), { childList: true, subtree: true });

    window.addEventListener('online', () => {
        if (proxy?.sessionId) flushDraft({ force: true });
        else if (!restoreCompleted) restoreDraft();
    });
    window.addEventListener('pagehide', () => {
        if (proxy?.sessionId && !conflict) flushDraft({ force: true, keepalive: true });
    });

    window.__plannerSessionDraft = {
        flush: () => flushDraft({ force: true }),
        restore: () => restoreDraft({ force: true }),
        stop: () => {
            stopStateWatch?.();
            stopRestoreWatch?.();
            observer.disconnect();
        }
    };
}
