import assert from 'node:assert/strict';

const watchers = [];
let draftFlushes = 0;

globalThis.HTMLInputElement = class HTMLInputElement {};
globalThis.HTMLTextAreaElement = class HTMLTextAreaElement {};
globalThis.HTMLSelectElement = class HTMLSelectElement {};
globalThis.window = {
    addEventListener() {},
    removeEventListener() {},
    __plannerSessionDraft: {
        async flush() { draftFlushes += 1; }
    }
};

globalThis.Vue = {
    ref(value) { return { value }; },
    computed(getter) { return { get value() { return getter(); } }; },
    watch(source, callback, options = {}) {
        const item = { source, callback };
        watchers.push(item);
        if (options.immediate) callback(source());
        return () => {};
    },
    async nextTick() {},
    onBeforeUnmount() {}
};

const { createEditorHistoryState } = await import('../web/frontend/assets/editor-history-state.js');

const file = {
    file_id: 'file-1',
    filename: '101.xlsx',
    group_name: '101',
    enabled: true,
    analysis: { sheet_names: ['Лист1'] }
};
const layouts = {
    'file-1': { sheet_name: 'Лист1', weeks_row: 7, grid_start_row: 10 }
};
const periodOverrides = {
    'file-1': {
        week_day_dates: {},
        week_months: {},
        teacher_overrides: {}
    }
};
const validations = {
    'file-1': { status: 'success', report: { lesson_count: 10 } }
};
const selectedFileId = { value: 'file-1' };
let previewLoads = 0;

const schedule = {
    sessionId: { value: 'session-1' },
    analyzedFiles: { value: [file] },
    selectedFileId,
    layouts,
    periodOverrides,
    validations,
    calendarOverrides: {
        policy: 'auto',
        week_day_dates: {},
        week_months: {}
    },
    currentFile: {
        get value() {
            return schedule.analyzedFiles.value.find(item => item.file_id === selectedFileId.value) || null;
        }
    },
    currentLayout: {
        get value() {
            return layouts[selectedFileId.value] || null;
        }
    },
    async loadPreview() { previewLoads += 1; }
};
const editor = { sheetWorkspaceOpen: { value: true } };
const toasts = [];
const history = createEditorHistoryState(
    (title, message, type) => toasts.push({ title, message, type }),
    schedule,
    editor
);

assert.equal(watchers.length, 2, 'state and session watchers must be installed');
const stateWatcher = watchers[0];

layouts['file-1'].weeks_row = 9;
stateWatcher.callback(stateWatcher.source());
assert.equal(history.canUndoEditor.value, true);

await history.undoEditorChange();
assert.equal(layouts['file-1'].weeks_row, 7);
assert.equal(history.canRedoEditor.value, true);
assert.equal('file-1' in validations, false, 'derived validation must be invalidated');
assert.equal(previewLoads, 1);
assert.equal(draftFlushes, 1);

await history.redoEditorChange();
assert.equal(layouts['file-1'].weeks_row, 9);
assert.equal(previewLoads, 2);
assert.equal(draftFlushes, 2);

periodOverrides['file-1'].teacher_overrides['Математика'] = 'Иванов И.И.';
stateWatcher.callback(stateWatcher.source());
assert.equal(history.canUndoEditor.value, true);
await history.undoEditorChange();
assert.deepEqual(periodOverrides['file-1'].teacher_overrides, {});

file.group_name = '101-А';
file.enabled = false;
stateWatcher.callback(stateWatcher.source());
await history.undoEditorChange();
assert.equal(file.group_name, '101');
assert.equal(file.enabled, true);

assert.ok(toasts.some(item => item.title === 'Изменение отменено'));
assert.ok(toasts.some(item => item.title === 'Изменение возвращено'));
console.log('editor history probe passed');
