const { ref, computed, watch, nextTick, onBeforeUnmount } = Vue;

const MAX_HISTORY = 80;

export function createEditorHistoryState(addToast, schedule, editor) {
    const historyRevision = ref(0);
    const applyingHistory = ref(false);
    const buckets = new Map();
    let stopStateWatch = null;
    let stopSessionWatch = null;

    const copy = value => value == null ? value : JSON.parse(JSON.stringify(value));

    function clearObject(target) {
        if (!target || typeof target !== 'object') return;
        Object.keys(target).forEach(key => delete target[key]);
    }

    function captureState() {
        const file = schedule.currentFile.value;
        if (!file?.file_id || !schedule.currentLayout.value) return null;
        return {
            file_id: String(file.file_id),
            group_name: String(file.group_name || ''),
            enabled: Boolean(file.enabled),
            layout: copy(schedule.currentLayout.value),
            period_overrides: copy(schedule.periodOverrides[file.file_id] || {
                week_day_dates: {},
                week_months: {},
                teacher_overrides: {}
            }),
            calendar_overrides: copy(schedule.calendarOverrides || {
                policy: 'auto',
                week_day_dates: {},
                week_months: {}
            })
        };
    }

    function signature(value) {
        return value ? JSON.stringify(value) : '';
    }

    function bucketFor(fileId, create = true) {
        const key = String(fileId || '');
        if (!key) return null;
        if (!buckets.has(key) && create) {
            buckets.set(key, {
                undo: [],
                redo: [],
                last: null,
                lastSignature: ''
            });
        }
        return buckets.get(key) || null;
    }

    function recordSnapshot(snapshot) {
        if (!snapshot || applyingHistory.value) return;
        const bucket = bucketFor(snapshot.file_id);
        const nextSignature = signature(snapshot);
        if (!bucket.last) {
            bucket.last = copy(snapshot);
            bucket.lastSignature = nextSignature;
            historyRevision.value += 1;
            return;
        }
        if (nextSignature === bucket.lastSignature) return;
        bucket.undo.push(copy(bucket.last));
        if (bucket.undo.length > MAX_HISTORY) bucket.undo.shift();
        bucket.redo = [];
        bucket.last = copy(snapshot);
        bucket.lastSignature = nextSignature;
        historyRevision.value += 1;
    }

    async function applySnapshot(snapshot) {
        if (!snapshot) return;
        const file = schedule.analyzedFiles.value.find(
            item => String(item.file_id) === String(snapshot.file_id)
        );
        if (!file) {
            addToast('История изменений', 'Файл больше не находится в текущем сеансе.', 'warning');
            return;
        }

        applyingHistory.value = true;
        try {
            schedule.selectedFileId.value = file.file_id;
            file.group_name = snapshot.group_name;
            file.enabled = Boolean(snapshot.enabled);
            schedule.layouts[file.file_id] = copy(snapshot.layout);
            schedule.periodOverrides[file.file_id] = copy(snapshot.period_overrides || {
                week_day_dates: {},
                week_months: {},
                teacher_overrides: {}
            });

            const calendar = snapshot.calendar_overrides || {};
            schedule.calendarOverrides.policy = calendar.policy || 'auto';
            clearObject(schedule.calendarOverrides.week_day_dates);
            clearObject(schedule.calendarOverrides.week_months);
            Object.assign(
                schedule.calendarOverrides.week_day_dates,
                copy(calendar.week_day_dates || {})
            );
            Object.assign(
                schedule.calendarOverrides.week_months,
                copy(calendar.week_months || {})
            );
            delete schedule.validations[file.file_id];
            await nextTick();
            if (file.analysis) await schedule.loadPreview();
            window.__plannerSessionDraft?.flush?.();
        } finally {
            applyingHistory.value = false;
        }
    }

    const canUndoEditor = computed(() => {
        historyRevision.value;
        const bucket = bucketFor(schedule.currentFile.value?.file_id, false);
        return Boolean(bucket?.undo.length);
    });

    const canRedoEditor = computed(() => {
        historyRevision.value;
        const bucket = bucketFor(schedule.currentFile.value?.file_id, false);
        return Boolean(bucket?.redo.length);
    });

    const editorHistoryDepth = computed(() => {
        historyRevision.value;
        const bucket = bucketFor(schedule.currentFile.value?.file_id, false);
        return {
            undo: bucket?.undo.length || 0,
            redo: bucket?.redo.length || 0
        };
    });

    async function undoEditorChange() {
        const current = captureState();
        const bucket = bucketFor(current?.file_id, false);
        if (!current || !bucket?.undo.length) return;
        const target = bucket.undo.pop();
        bucket.redo.push(copy(current));
        if (bucket.redo.length > MAX_HISTORY) bucket.redo.shift();
        bucket.last = copy(target);
        bucket.lastSignature = signature(target);
        historyRevision.value += 1;
        await applySnapshot(target);
        addToast(
            'Изменение отменено',
            `Можно вернуть вперёд: ${bucket.redo.length}. Разметка файла сохранена в черновике.`,
            'info'
        );
    }

    async function redoEditorChange() {
        const current = captureState();
        const bucket = bucketFor(current?.file_id, false);
        if (!current || !bucket?.redo.length) return;
        const target = bucket.redo.pop();
        bucket.undo.push(copy(current));
        if (bucket.undo.length > MAX_HISTORY) bucket.undo.shift();
        bucket.last = copy(target);
        bucket.lastSignature = signature(target);
        historyRevision.value += 1;
        await applySnapshot(target);
        addToast(
            'Изменение возвращено',
            `Доступно отмен: ${bucket.undo.length}. Разметка файла сохранена в черновике.`,
            'info'
        );
    }

    function resetEditorHistory(fileId = null) {
        if (fileId) buckets.delete(String(fileId));
        else buckets.clear();
        historyRevision.value += 1;
        const snapshot = captureState();
        if (snapshot && (!fileId || String(snapshot.file_id) === String(fileId))) {
            recordSnapshot(snapshot);
        }
    }

    function handleHistoryShortcut(event) {
        if (!editor.sheetWorkspaceOpen.value) return;
        const target = event.target;
        const editing = target instanceof HTMLInputElement
            || target instanceof HTMLTextAreaElement
            || target instanceof HTMLSelectElement
            || target?.isContentEditable;
        if (editing || !(event.metaKey || event.ctrlKey)) return;
        const key = event.key.toLowerCase();
        if (key === 'z' && event.shiftKey) {
            if (!canRedoEditor.value) return;
            event.preventDefault();
            redoEditorChange();
        } else if (key === 'z') {
            if (!canUndoEditor.value) return;
            event.preventDefault();
            undoEditorChange();
        } else if (key === 'y') {
            if (!canRedoEditor.value) return;
            event.preventDefault();
            redoEditorChange();
        }
    }

    stopStateWatch = watch(
        () => signature(captureState()),
        value => {
            if (!value || applyingHistory.value) return;
            try {
                recordSnapshot(JSON.parse(value));
            } catch (_) {
                // Invalid transient state is not added to the operator history.
            }
        },
        { immediate: true, flush: 'post' }
    );

    stopSessionWatch = watch(
        () => schedule.sessionId.value,
        () => resetEditorHistory(),
        { flush: 'post' }
    );

    window.addEventListener('keydown', handleHistoryShortcut);
    onBeforeUnmount(() => {
        stopStateWatch?.();
        stopSessionWatch?.();
        window.removeEventListener('keydown', handleHistoryShortcut);
    });

    return {
        canUndoEditor,
        canRedoEditor,
        editorHistoryDepth,
        applyingHistory,
        undoEditorChange,
        redoEditorChange,
        resetEditorHistory
    };
}
