const { ref, computed, watch, nextTick, onBeforeUnmount } = Vue;

const STORAGE_KEY = 'planner-analysis-session-v2';
const DRAFT_VERSION = 1;

function clone(value) {
    return JSON.parse(JSON.stringify(value ?? null));
}

function compactResult(value) {
    if (!value) return null;
    return {
        filename: value.filename || null,
        weekly_filename: value.weekly_filename || null,
        run_id: value.run_id || null,
        status: value.status || 'warning',
        message: value.message || '',
        details: clone(value.details || []),
        warnings: clone(value.warnings || []),
        corrections: clone(value.corrections || [])
    };
}

function storedSession() {
    try {
        const value = JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null');
        return value && typeof value.session_id === 'string' ? value : null;
    } catch (_) {
        return null;
    }
}

function rememberSession(sessionId, workspaceId) {
    try {
        if (!sessionId) localStorage.removeItem(STORAGE_KEY);
        else localStorage.setItem(STORAGE_KEY, JSON.stringify({
            session_id: sessionId,
            workspace_id: workspaceId || null,
            saved_at: Date.now()
        }));
    } catch (_) {
        // Browser storage may be disabled. The server draft still remains usable
        // through the current open tab.
    }
}

export function createScheduleDraftState(addToast, schedule, activeWorkspaceId) {
    const draftState = ref('idle');
    const draftSavedAt = ref(null);
    const draftRestored = ref(false);
    const draftError = ref('');
    const replacementFileId = ref(null);
    const replacementBusy = ref(false);
    let restoring = false;
    let saveTimer = null;
    let saveChain = Promise.resolve();
    let disposed = false;

    const draftStateLabel = computed(() => ({
        idle: 'Черновик готов',
        pending: 'Сохраняем изменения…',
        saved: draftSavedAt.value
            ? `Сохранено ${new Date(draftSavedAt.value).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })}`
            : 'Черновик сохранён',
        error: 'Черновик не сохранён'
    }[draftState.value] || 'Черновик готов'));

    const resultCorrections = computed(() => schedule.result.value?.corrections || []);
    const resultProblemFiles = computed(() =>
        (schedule.result.value?.details || []).filter(item =>
            item.status !== 'success' || item.used === false || Number(item.warning_count || 0) > 0
        )
    );

    function clearObject(target) {
        Object.keys(target || {}).forEach(key => delete target[key]);
    }

    function draftPayload() {
        const knownIds = new Set(
            schedule.analyzedFiles.value
                .filter(item => item.analysis)
                .map(item => String(item.file_id))
        );
        const layouts = {};
        const periodOverrides = {};
        for (const fileId of knownIds) {
            if (schedule.layouts[fileId]) layouts[fileId] = clone(schedule.layouts[fileId]);
            if (schedule.periodOverrides[fileId]) {
                periodOverrides[fileId] = clone(schedule.periodOverrides[fileId]);
            }
        }
        return {
            version: DRAFT_VERSION,
            workspace_id: activeWorkspaceId.value || null,
            selected_file_id: knownIds.has(String(schedule.selectedFileId.value || ''))
                ? schedule.selectedFileId.value
                : null,
            step: schedule.step.value,
            files: schedule.analyzedFiles.value.map(item => ({
                file_id: String(item.file_id),
                enabled: Boolean(item.enabled && item.analysis),
                group_name: String(item.group_name || '').slice(0, 240)
            })),
            layouts,
            period_overrides: periodOverrides,
            calendar_overrides: clone(schedule.calendarOverrides),
            result: compactResult(schedule.result.value)
        };
    }

    async function writeDraft(payload = draftPayload(), { quiet = true } = {}) {
        const id = schedule.sessionId.value;
        if (!id || restoring || disposed) return false;
        draftState.value = 'pending';
        draftError.value = '';
        rememberSession(id, activeWorkspaceId.value);
        try {
            const { data } = await axios.put(`/api/analysis/${id}/draft`, payload);
            if (id !== schedule.sessionId.value) return false;
            draftSavedAt.value = Number(data.saved_at || Date.now() / 1000) * 1000;
            draftState.value = 'saved';
            return true;
        } catch (error) {
            if (id !== schedule.sessionId.value) return false;
            const status = Number(error.response?.status || 0);
            if (status === 404 || status === 410) {
                rememberSession(null);
                draftError.value = 'Сеанс истёк. Исходники потребуется загрузить заново.';
            } else {
                draftError.value = error.response?.data?.detail || 'Не удалось сохранить текущие правки.';
            }
            draftState.value = 'error';
            if (!quiet) addToast('Черновик', draftError.value, 'warning');
            return false;
        }
    }

    function queueDraftSave() {
        if (restoring || disposed || !schedule.sessionId.value) return;
        draftState.value = 'pending';
        window.clearTimeout(saveTimer);
        saveTimer = window.setTimeout(() => {
            const payload = draftPayload();
            saveChain = saveChain
                .catch(() => false)
                .then(() => writeDraft(payload));
        }, 350);
    }

    async function flushDraft({ quiet = true } = {}) {
        window.clearTimeout(saveTimer);
        const payload = draftPayload();
        saveChain = saveChain
            .catch(() => false)
            .then(() => writeDraft(payload, { quiet }));
        return saveChain;
    }

    async function restoreDraft() {
        const stored = storedSession();
        if (!stored?.session_id || schedule.sessionId.value) return { restored: false };
        restoring = true;
        draftState.value = 'pending';
        draftError.value = '';
        try {
            const { data } = await axios.get(`/api/analysis/${stored.session_id}`);
            const draft = data.draft || {};
            const draftFiles = new Map((draft.files || []).map(item => [String(item.file_id), item]));
            const files = (data.files || []).map(item => {
                const saved = draftFiles.get(String(item.file_id));
                return {
                    ...item,
                    group_name: saved?.group_name || item.group_name,
                    enabled: saved ? Boolean(saved.enabled && item.analysis) : Boolean(item.analysis)
                };
            });
            if (!files.some(item => item.analysis)) {
                rememberSession(null);
                draftState.value = 'idle';
                return { restored: false };
            }

            schedule.sessionId.value = data.session_id;
            schedule.analyzedFiles.value = files;
            clearObject(schedule.layouts);
            clearObject(schedule.validations);
            clearObject(schedule.periodOverrides);

            for (const file of files) {
                if (!file.analysis) continue;
                schedule.layouts[file.file_id] = clone(
                    draft.layouts?.[file.file_id] || file.analysis.layout
                );
                schedule.periodOverrides[file.file_id] = clone(
                    draft.period_overrides?.[file.file_id] || {
                        week_day_dates: {},
                        week_months: {}
                    }
                );
            }

            clearObject(schedule.calendarOverrides.week_day_dates);
            clearObject(schedule.calendarOverrides.week_months);
            Object.assign(schedule.calendarOverrides, clone(draft.calendar_overrides || {}));
            schedule.calendarOverrides.policy ||= 'auto';
            schedule.calendarOverrides.week_day_dates ||= {};
            schedule.calendarOverrides.week_months ||= {};

            const selected = files.find(item => item.file_id === draft.selected_file_id && item.analysis)
                || files.find(item => item.analysis);
            schedule.selectedFileId.value = selected?.file_id || null;
            schedule.result.value = draft.result || null;
            schedule.step.value = Number(draft.step) === 3 && draft.result?.filename ? 3 : 2;
            schedule.previewRegion.value = 'schedule';

            const restoredWorkspace = draft.workspace_id || stored.workspace_id || null;
            if (restoredWorkspace) {
                activeWorkspaceId.value = restoredWorkspace;
                try {
                    localStorage.setItem('planner-workspace-id', restoredWorkspace);
                } catch (_) {
                    // No-op.
                }
            }
            rememberSession(data.session_id, restoredWorkspace);
            draftSavedAt.value = Number(draft.saved_at || data.updated_at || Date.now() / 1000) * 1000;
            draftState.value = 'saved';
            draftRestored.value = true;
            await nextTick();
            if (schedule.step.value === 2 && schedule.selectedFileId.value) {
                await schedule.loadPreview();
            }
            addToast(
                'Работа восстановлена',
                schedule.step.value === 3
                    ? 'Восстановлен готовый результат и исходная сессия правок.'
                    : 'Файлы, разметка, даты и положение рабочего этапа восстановлены.',
                'success'
            );
            return {
                restored: true,
                workspace_id: restoredWorkspace,
                step: schedule.step.value
            };
        } catch (error) {
            const status = Number(error.response?.status || 0);
            if (status === 404 || status === 410) {
                rememberSession(null);
                addToast('Черновик истёк', 'Сохранённые исходники удалены по сроку хранения. Начните новый сеанс.', 'info');
            }
            draftState.value = 'idle';
            return { restored: false, expired: status === 404 || status === 410 };
        } finally {
            restoring = false;
        }
    }

    async function returnToCorrections(fileId = null) {
        schedule.step.value = 2;
        const requested = schedule.analyzedFiles.value.find(item => item.file_id === fileId && item.analysis);
        const problematic = resultProblemFiles.value
            .map(detail => schedule.analyzedFiles.value.find(item => item.file_id === detail.file_id && item.analysis))
            .find(Boolean);
        const target = requested || problematic || schedule.analyzedFiles.value.find(item => item.analysis);
        if (target) {
            schedule.selectedFileId.value = target.file_id;
            schedule.previewRegion.value = 'schedule';
            await nextTick();
            await schedule.loadPreview();
        }
        await flushDraft();
    }

    async function openResultFile(detail) {
        await returnToCorrections(detail?.file_id || null);
    }

    function startFileReplacement(fileId = null) {
        const target = fileId || schedule.currentFile.value?.file_id;
        if (!target || replacementBusy.value) return;
        replacementFileId.value = target;
        nextTick(() => document.getElementById('analysis-file-replacement')?.click());
    }

    async function replaceAnalysisFile(event) {
        const input = event?.target;
        const file = input?.files?.[0];
        const fileId = replacementFileId.value;
        if (!file || !fileId || !schedule.sessionId.value) {
            if (input) input.value = '';
            return;
        }
        replacementBusy.value = true;
        const form = new FormData();
        form.append('files', file);
        try {
            const { data } = await axios.post(
                `/api/analysis/${schedule.sessionId.value}/files/${fileId}/replace`,
                form,
                { headers: { 'Content-Type': 'multipart/form-data' } }
            );
            const index = schedule.analyzedFiles.value.findIndex(item => item.file_id === fileId);
            const previous = index >= 0 ? schedule.analyzedFiles.value[index] : {};
            const replacement = {
                ...previous,
                ...data,
                enabled: Boolean(data.analysis),
                group_name: data.group_name || previous.group_name || file.name.replace(/\.[^.]+$/, '')
            };
            if (index >= 0) schedule.analyzedFiles.value.splice(index, 1, replacement);
            else schedule.analyzedFiles.value.push(replacement);
            if (data.analysis) {
                schedule.layouts[fileId] = clone(data.analysis.layout);
                schedule.periodOverrides[fileId] = { week_day_dates: {}, week_months: {} };
                delete schedule.validations[fileId];
                schedule.selectedFileId.value = fileId;
                schedule.result.value = null;
                schedule.step.value = 2;
                schedule.previewRegion.value = 'schedule';
                await nextTick();
                await schedule.loadPreview();
                await schedule.validateCurrent();
            }
            await flushDraft({ quiet: false });
            addToast('Файл заменён', 'Остальные файлы, ручные даты и разметки сохранены.', 'success');
        } catch (error) {
            addToast(
                'Файл не заменён',
                error.response?.data?.detail || 'Новый файл не удалось обработать; прежний файл сохранён.',
                'warning'
            );
        } finally {
            replacementBusy.value = false;
            replacementFileId.value = null;
            if (input) input.value = '';
        }
    }

    const originalApplyParserAction = schedule.applyParserAction;
    async function applyParserAction(action) {
        if (action?.type === 'replace_file') {
            startFileReplacement(action.file_id || schedule.currentFile.value?.file_id);
            return;
        }
        if (action?.type === 'open_teacher_mapping') {
            schedule.step.value = 2;
            schedule.previewRegion.value = 'legend';
            await schedule.loadPreview();
            await nextTick();
            const target = document.querySelector('.editor-settings-panel, .settings-panel, .exact-layout-editor');
            target?.scrollIntoView({ behavior: 'smooth', block: 'start' });
            addToast(
                'Преподаватели',
                'Проверьте столбцы лектора и остальных преподавателей либо измените справочник пространства.',
                'info'
            );
            return;
        }
        return originalApplyParserAction(action);
    }

    const originalGenerate = schedule.generate;
    async function generate() {
        await originalGenerate();
        if (schedule.result.value?.filename) await flushDraft({ quiet: false });
    }

    const originalResetWorkflow = schedule.resetWorkflow;
    async function resetWorkflow() {
        restoring = true;
        window.clearTimeout(saveTimer);
        try {
            await originalResetWorkflow();
        } finally {
            rememberSession(null);
            draftState.value = 'idle';
            draftSavedAt.value = null;
            draftRestored.value = false;
            draftError.value = '';
            replacementFileId.value = null;
            restoring = false;
        }
    }

    watch(
        () => ({
            sessionId: schedule.sessionId.value,
            step: schedule.step.value,
            selectedFileId: schedule.selectedFileId.value,
            workspaceId: activeWorkspaceId.value,
            files: schedule.analyzedFiles.value.map(item => ({
                file_id: item.file_id,
                enabled: item.enabled,
                group_name: item.group_name,
                has_analysis: Boolean(item.analysis)
            })),
            layouts: schedule.layouts,
            periodOverrides: schedule.periodOverrides,
            calendarOverrides: schedule.calendarOverrides,
            result: compactResult(schedule.result.value)
        }),
        queueDraftSave,
        { deep: true }
    );

    function beforeUnload() {
        const id = schedule.sessionId.value;
        if (!id || restoring) return;
        const body = JSON.stringify(draftPayload());
        try {
            fetch(`/api/analysis/${id}/draft`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin',
                body,
                keepalive: true
            }).catch(() => {});
        } catch (_) {
            // The debounced server copy remains the fallback.
        }
    }
    window.addEventListener('beforeunload', beforeUnload);
    onBeforeUnmount(() => {
        disposed = true;
        window.clearTimeout(saveTimer);
        window.removeEventListener('beforeunload', beforeUnload);
    });

    return {
        draftState,
        draftStateLabel,
        draftSavedAt,
        draftRestored,
        draftError,
        resultCorrections,
        resultProblemFiles,
        replacementFileId,
        replacementBusy,
        restoreDraft,
        flushDraft,
        returnToCorrections,
        openResultFile,
        startFileReplacement,
        replaceAnalysisFile,
        applyParserAction,
        generate,
        resetWorkflow
    };
}
