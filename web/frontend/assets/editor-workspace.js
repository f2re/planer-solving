const { ref, reactive, computed, watch, nextTick, onBeforeUnmount } = Vue;

export { installEditorWorkspaceMarkup } from './editor-workspace-markup.js';

export function createEditorWorkspaceState(addToast, schedule, interaction, workspace, platform) {
    const sheetWorkspaceOpen = ref(false);
    const filesPanelVisible = ref(true);
    const settingsPanelVisible = ref(false);
    const editorControlsVisible = ref(false);
    const sheetZoom = ref(1);
    const liveRecalc = ref(true);
    const recalcState = ref('idle');
    const layoutDirty = ref(false);
    const templateSaveOpen = ref(false);
    const templateSaving = ref(false);
    const templateSaveMode = ref('new');
    const smartTemplateName = ref('');
    const pendingEditorExit = ref(false);
    const headerAnchor = ref(null);
    const fullPreviewSheet = ref('');
    const dock = reactive({
        files: { x: 16, y: 72, width: 290 },
        settings: { x: Math.max(360, window.innerWidth - 390), y: 72, width: 370 }
    });
    let drag = null;
    let layoutTimer = null;
    let validationTimer = null;
    let previousLayout = null;
    let baselineLayout = '';
    let suppressLayoutWatch = false;

    const copy = value => JSON.parse(JSON.stringify(value || {}));
    const list = value => Array.isArray(value)
        ? value.map(Number).filter(Number.isFinite)
        : String(value ?? '').split(/[;,\s]+/).map(Number).filter(Number.isFinite);
    const equalList = (left, right) => JSON.stringify(list(left)) === JSON.stringify(list(right));
    const range = (first, last, step = 1, limit = 240) => {
        const result = [];
        const safeFirst = Math.max(1, Number(first || 1));
        const safeLast = Math.max(safeFirst, Number(last || safeFirst));
        const safeStep = Math.max(1, Number(step || 1));
        for (let value = safeFirst; value <= safeLast && result.length < limit; value += safeStep) {
            result.push(value);
        }
        return result;
    };
    const selectedEditorTemplate = computed(() => workspace.selectedTemplate.value || null);
    const recalcLabel = computed(() => ({
        idle: 'Готово', pending: 'Изменения…', working: 'Пересчитываем…',
        ready: 'Проверено', warning: 'Есть замечания', error: 'Ошибка'
    }[recalcState.value] || 'Готово'));

    function normalizedSignature() {
        return JSON.stringify(schedule.normalizedLayout(schedule.currentLayout.value || {}));
    }
    function resetLayoutBaseline() {
        baselineLayout = normalizedSignature();
        layoutDirty.value = false;
        previousLayout = copy(schedule.currentLayout.value);
    }

    function synchronizeDerivedLayout(layout, before) {
        if (!layout || !before) return;
        const weekScalars = ['first_week_col', 'last_week_col', 'week_col_step', 'week_data_col_offset'];
        const scalarWeekChanged = weekScalars.some(key => Number(layout[key] || 0) !== Number(before[key] || 0));
        const exactWeekChanged = !equalList(layout.week_columns, before.week_columns);
        if (scalarWeekChanged && !exactWeekChanged) {
            const columns = range(layout.first_week_col, layout.last_week_col, layout.week_col_step);
            layout.week_columns = columns;
            layout.week_data_columns = columns.map(col => col + Number(layout.week_data_col_offset || 0));
            const oldNumbers = list(before.week_numbers);
            const firstNumber = oldNumbers[0] ?? (layout.allow_week_zero ? 0 : 1);
            layout.week_numbers = columns.map((_, index) => firstNumber + index);
        } else if (exactWeekChanged && list(layout.week_columns).length) {
            const columns = [...new Set(list(layout.week_columns))].sort((a, b) => a - b);
            layout.week_columns = columns;
            layout.first_week_col = columns[0];
            layout.last_week_col = columns[columns.length - 1];
            if (columns.length > 1) layout.week_col_step = Math.max(1, columns[1] - columns[0]);
        }
        const dayScalars = ['grid_start_row', 'day_block_rows'];
        const scalarDayChanged = dayScalars.some(key => Number(layout[key] || 0) !== Number(before[key] || 0));
        if (scalarDayChanged && equalList(layout.day_start_rows, before.day_start_rows)) {
            layout.day_start_rows = (layout.day_names || []).map((_, index) =>
                Number(layout.grid_start_row || 1) + index * Number(layout.day_block_rows || 13)
            );
        }
        const pairScalars = ['pairs_per_day', 'pair_row_stride'];
        const scalarPairChanged = pairScalars.some(key => Number(layout[key] || 0) !== Number(before[key] || 0));
        if (scalarPairChanged && equalList(layout.pair_row_offsets, before.pair_row_offsets)) {
            layout.pair_row_offsets = Array.from(
                { length: Math.max(1, Number(layout.pairs_per_day || 4)) },
                (_, index) => index * Number(layout.pair_row_stride || 3)
            );
        }
    }

    async function loadFullSheet() {
        const file = schedule.currentFile.value;
        const layout = schedule.currentLayout.value;
        if (!file?.analysis || !schedule.sessionId.value || !layout) return;
        schedule.previewBusy.value = true;
        try {
            const { data } = await axios.get(
                `/api/analysis/${schedule.sessionId.value}/files/${file.file_id}/preview`,
                { params: { region: 'custom', full_sheet: true, sheet_name: layout.sheet_name } }
            );
            schedule.preview.value = data;
            fullPreviewSheet.value = layout.sheet_name;
        } catch (error) {
            addToast('Рабочий лист', error.response?.data?.detail || 'Не удалось загрузить лист целиком.', 'error');
        } finally {
            schedule.previewBusy.value = false;
        }
    }

    async function validateSilently() {
        const file = schedule.currentFile.value;
        if (!file?.analysis || !file.enabled || !schedule.sessionId.value) return null;
        const { data } = await axios.post(
            `/api/analysis/${schedule.sessionId.value}/validate`,
            {
                file_id: file.file_id,
                group_name: file.group_name,
                layout: schedule.normalizedLayout(schedule.currentLayout.value),
                workspace_id: workspace.activeWorkspaceId.value
            }
        );
        schedule.validations[file.file_id] = data;
        return data;
    }

    async function flushRecalculation(showToast = false) {
        if (!schedule.currentLayout.value || !schedule.currentFile.value) return;
        window.clearTimeout(layoutTimer);
        window.clearTimeout(validationTimer);
        recalcState.value = 'working';
        try {
            if (sheetWorkspaceOpen.value) {
                if (fullPreviewSheet.value !== schedule.currentLayout.value.sheet_name) await loadFullSheet();
            } else {
                await schedule.loadPreview();
            }
            const validation = await validateSilently();
            if (validation?.status === 'error') recalcState.value = 'error';
            else if (validation?.status === 'warning') recalcState.value = 'warning';
            else recalcState.value = 'ready';
            if (showToast) {
                addToast(
                    'Разметка пересчитана',
                    validation?.status === 'error'
                        ? (validation.report?.errors || []).join(' ')
                        : `Распознано занятий: ${validation?.report?.lesson_count || 0}.`,
                    validation?.status || 'success'
                );
            }
            if (sheetWorkspaceOpen.value && sheetZoom.value === 1) await fitSheetToScreen();
        } catch (error) {
            recalcState.value = 'error';
            if (showToast) addToast('Пересчёт', error.response?.data?.detail || 'Не удалось проверить разметку.', 'error');
        }
    }

    function scheduleRecalculation() {
        recalcState.value = 'pending';
        window.clearTimeout(layoutTimer);
        window.clearTimeout(validationTimer);
        if (!liveRecalc.value) return;
        layoutTimer = window.setTimeout(() => {
            if (!sheetWorkspaceOpen.value) schedule.loadPreview().catch(() => {});
        }, 220);
        validationTimer = window.setTimeout(() => flushRecalculation(false), 650);
    }

    async function recalculateNow() {
        await flushRecalculation(true);
    }

    async function enterSheetWorkspace() {
        if (!schedule.currentFile.value?.analysis) return;
        sheetWorkspaceOpen.value = true;
        settingsPanelVisible.value = false;
        filesPanelVisible.value = true;
        document.documentElement.classList.add('sheet-workspace-open');
        await loadFullSheet();
        await nextTick();
        await fitSheetToScreen();
        resetLayoutBaseline();
    }

    function closeSheetWorkspace() {
        sheetWorkspaceOpen.value = false;
        document.documentElement.classList.remove('sheet-workspace-open');
        pendingEditorExit.value = false;
        headerAnchor.value = null;
    }

    function leaveSheetWorkspace() {
        if (layoutDirty.value) {
            pendingEditorExit.value = true;
            requestTemplateSave();
            return;
        }
        closeSheetWorkspace();
    }

    function zoomInSheet() { sheetZoom.value = Math.min(2.2, Math.round((sheetZoom.value + 0.1) * 10) / 10); }
    function zoomOutSheet() { sheetZoom.value = Math.max(0.2, Math.round((sheetZoom.value - 0.1) * 10) / 10); }
    function zoomSheetWheel(event) {
        if (event.deltaY < 0) zoomInSheet(); else zoomOutSheet();
    }
    async function fitSheetToScreen() {
        await nextTick();
        const wrap = document.querySelector('.editor-canvas-panel .preview-wrap');
        const table = wrap?.querySelector('.preview-table');
        if (!wrap || !table) return;
        sheetZoom.value = 1;
        await nextTick();
        const width = Math.max(1, table.scrollWidth);
        const height = Math.max(1, table.scrollHeight);
        const scale = Math.min((wrap.clientWidth - 30) / width, (wrap.clientHeight - 30) / height, 1.4);
        sheetZoom.value = Math.max(0.2, Math.round(scale * 100) / 100);
    }

    function relevantColumns(mode) {
        const layout = schedule.currentLayout.value || {};
        if (mode.startsWith('legend')) {
            const columns = [layout.legend_code_col, layout.legend_subject_col, layout.legend_lecturer_col, layout.legend_other_col]
                .map(Number).filter(Number.isFinite);
            return columns.length ? [Math.min(...columns), Math.max(...columns)] : [schedule.preview.value?.col_start || 1, schedule.preview.value?.col_end || 1];
        }
        const columns = list(layout.week_data_columns).length ? list(layout.week_data_columns) : list(layout.week_columns);
        return columns.length ? [Math.min(...columns), Math.max(...columns)] : [schedule.preview.value?.col_start || 1, schedule.preview.value?.col_end || 1];
    }

    function applyHeaderSelection(rangeValue, type) {
        const layout = schedule.currentLayout.value;
        if (!layout) return;
        interaction.selectedRange.value = rangeValue;
        const mode = interaction.selectionMode.value;
        if (type === 'row') {
            if (mode === 'weeks') layout.weeks_row = rangeValue.rowStart;
            else if (mode === 'months') layout.months_row = rangeValue.rowStart;
            else if (mode === 'legend') {
                layout.legend_start_row = rangeValue.rowStart;
                layout.legend_end_row = rangeValue.rowEnd;
            } else {
                layout.grid_start_row = rangeValue.rowStart;
                layout.grid_end_row = rangeValue.rowEnd;
            }
        } else if (type === 'column') {
            if (mode === 'legend_code') layout.legend_code_col = rangeValue.colStart;
            else if (mode === 'legend_subject') layout.legend_subject_col = rangeValue.colStart;
            else if (mode === 'legend_lecturer') layout.legend_lecturer_col = rangeValue.colStart;
            else if (mode === 'legend_other') layout.legend_other_col = rangeValue.colStart;
            else {
                layout.first_week_col = rangeValue.colStart;
                layout.last_week_col = rangeValue.colEnd;
                layout.week_columns = range(rangeValue.colStart, rangeValue.colEnd, 1);
                layout.week_data_columns = [...layout.week_columns];
                const start = layout.allow_week_zero ? 0 : 1;
                layout.week_numbers = layout.week_columns.map((_, index) => start + index);
            }
        }
        schedule.markDirty();
    }

    function selectSheetRow(row, event) {
        const start = event.shiftKey && headerAnchor.value?.type === 'row' ? headerAnchor.value.value : Number(row);
        headerAnchor.value = { type: 'row', value: Number(row) };
        const [colStart, colEnd] = relevantColumns(interaction.selectionMode.value);
        applyHeaderSelection({
            rowStart: Math.min(start, Number(row)), rowEnd: Math.max(start, Number(row)),
            colStart, colEnd
        }, 'row');
    }
    function selectSheetColumn(column, event) {
        const start = event.shiftKey && headerAnchor.value?.type === 'column' ? headerAnchor.value.value : Number(column);
        headerAnchor.value = { type: 'column', value: Number(column) };
        applyHeaderSelection({
            rowStart: schedule.preview.value?.row_start || 1,
            rowEnd: schedule.preview.value?.row_end || 1,
            colStart: Math.min(start, Number(column)), colEnd: Math.max(start, Number(column))
        }, 'column');
    }
    function selectWholeSheet() {
        const preview = schedule.preview.value;
        if (!preview) return;
        interaction.selectedRange.value = {
            rowStart: preview.row_start, rowEnd: preview.row_end,
            colStart: preview.col_start, colEnd: preview.col_end
        };
    }
    const isSheetRowSelected = row => {
        const selected = interaction.selectedRange.value;
        return Boolean(selected && Number(row) >= selected.rowStart && Number(row) <= selected.rowEnd);
    };
    const isSheetColumnSelected = column => {
        const selected = interaction.selectedRange.value;
        return Boolean(selected && Number(column) >= selected.colStart && Number(column) <= selected.colEnd);
    };

    function beginDockDrag(name, event) {
        if (!sheetWorkspaceOpen.value) return;
        event.preventDefault();
        drag = { name, startX: event.clientX, startY: event.clientY, x: dock[name].x, y: dock[name].y };
        window.addEventListener('pointermove', moveDockDrag);
        window.addEventListener('pointerup', endDockDrag, { once: true });
    }
    function moveDockDrag(event) {
        if (!drag) return;
        const panel = dock[drag.name];
        panel.x = Math.max(0, Math.min(window.innerWidth - panel.width, drag.x + event.clientX - drag.startX));
        panel.y = Math.max(48, Math.min(window.innerHeight - 100, drag.y + event.clientY - drag.startY));
    }
    function endDockDrag() {
        drag = null;
        window.removeEventListener('pointermove', moveDockDrag);
    }
    function dockPanelStyle(name) {
        if (!sheetWorkspaceOpen.value) return {};
        const panel = dock[name];
        return { left: `${panel.x}px`, top: `${panel.y}px`, width: `${panel.width}px` };
    }

    function requestTemplateSave() {
        const file = schedule.currentFile.value;
        const selected = selectedEditorTemplate.value;
        smartTemplateName.value = selected?.name || `${file?.group_name || file?.filename?.replace(/\.[^.]+$/, '') || 'Расписание'} · ${schedule.currentLayout.value?.sheet_name || 'лист'}`;
        templateSaveMode.value = selected ? 'update' : 'new';
        templateSaveOpen.value = true;
    }
    function cancelTemplateSave() {
        templateSaveOpen.value = false;
        pendingEditorExit.value = false;
    }
    function leaveWithoutTemplateSave() {
        templateSaveOpen.value = false;
        closeSheetWorkspace();
    }
    async function saveEditorTemplate() {
        if (!smartTemplateName.value || !schedule.currentLayout.value) return;
        templateSaving.value = true;
        try {
            const selected = selectedEditorTemplate.value;
            const payload = {
                name: smartTemplateName.value,
                description: selected?.description || '',
                layout: schedule.normalizedLayout(schedule.currentLayout.value),
                composite: selected?.composite || [],
                fingerprint: schedule.currentFile.value?.analysis?.fingerprint || {},
                comment: `Подтверждено в полноэкранной рабочей области для «${schedule.currentFile.value?.filename || 'файла'}»`
            };
            let response;
            if (templateSaveMode.value === 'update' && selected) {
                response = await axios.put(`/api/workspaces/${workspace.activeWorkspaceId.value}/templates/${selected.id}/profile`, payload);
            } else {
                response = await axios.post(`/api/workspaces/${workspace.activeWorkspaceId.value}/templates`, payload);
            }
            await workspace.refreshWorkspace?.(workspace.activeWorkspaceId.value, { silent: true });
            workspace.selectedProfile.value = response.data.name;
            resetLayoutBaseline();
            templateSaveOpen.value = false;
            addToast('Шаблон сохранён', `«${response.data.name}», версия ${response.data.current_revision}.`, 'success');
            if (pendingEditorExit.value) closeSheetWorkspace();
        } catch (error) {
            addToast('Шаблон', error.response?.data?.detail || 'Не удалось сохранить разметку.', 'error');
        } finally {
            templateSaving.value = false;
        }
    }

    async function clearUserPassword() {
        const user = platform.userForm;
        if (!user?.id) return;
        if (!confirm(`Сбросить пароль пользователя «${user.display_name || user.username}» на пустой?`)) return;
        try {
            await axios.post(`/api/admin/users/${user.id}/reset-password`, { password: '' });
            platform.platformUsers.value = (await axios.get('/api/admin/users')).data.users;
            platform.userForm.password = '';
            addToast('Пароль сброшен', 'Теперь пользователь может войти с пустым паролем.', 'success');
        } catch (error) {
            addToast('Сброс пароля', error.response?.data?.detail || 'Пароль не сброшен.', 'error');
        }
    }

    function autoScrollSelection(event) {
        if (!sheetWorkspaceOpen.value || !document.documentElement.classList.contains('parser-range-selecting')) return;
        const wrap = document.querySelector('.editor-canvas-panel .preview-wrap');
        if (!wrap) return;
        const box = wrap.getBoundingClientRect();
        const margin = 48;
        let dx = 0, dy = 0;
        if (event.clientX < box.left + margin) dx = -18;
        else if (event.clientX > box.right - margin) dx = 18;
        if (event.clientY < box.top + margin) dy = -18;
        else if (event.clientY > box.bottom - margin) dy = 18;
        if (dx || dy) wrap.scrollBy(dx, dy);
    }

    watch(() => schedule.selectedFileId.value, async () => {
        suppressLayoutWatch = true;
        fullPreviewSheet.value = '';
        headerAnchor.value = null;
        await nextTick();
        resetLayoutBaseline();
        suppressLayoutWatch = false;
        if (sheetWorkspaceOpen.value) {
            await loadFullSheet();
            await fitSheetToScreen();
        }
    });
    watch(() => schedule.currentLayout.value, layout => {
        if (!layout || suppressLayoutWatch) return;
        suppressLayoutWatch = true;
        synchronizeDerivedLayout(layout, previousLayout || copy(layout));
        previousLayout = copy(layout);
        suppressLayoutWatch = false;
        layoutDirty.value = normalizedSignature() !== baselineLayout;
        schedule.markDirty();
        scheduleRecalculation();
    }, { deep: true });
    watch(() => schedule.step.value, value => {
        if (value === 2 && localStorage.getItem('planner-auto-fullscreen') !== '0') {
            window.setTimeout(() => enterSheetWorkspace(), 80);
        }
        if (value !== 2 && sheetWorkspaceOpen.value) closeSheetWorkspace();
    });

    const resize = () => {
        dock.settings.x = Math.min(dock.settings.x, Math.max(0, window.innerWidth - dock.settings.width));
        if (sheetWorkspaceOpen.value) fitSheetToScreen();
    };
    window.addEventListener('resize', resize);
    window.addEventListener('pointermove', autoScrollSelection, { passive: true });
    onBeforeUnmount(() => {
        window.clearTimeout(layoutTimer);
        window.clearTimeout(validationTimer);
        window.removeEventListener('resize', resize);
        window.removeEventListener('pointermove', autoScrollSelection);
        window.removeEventListener('pointermove', moveDockDrag);
        document.documentElement.classList.remove('sheet-workspace-open');
    });

    return {
        sheetWorkspaceOpen,
        filesPanelVisible,
        settingsPanelVisible,
        editorControlsVisible,
        sheetZoom,
        liveRecalc,
        recalcState,
        recalcLabel,
        layoutDirty,
        templateSaveOpen,
        templateSaving,
        templateSaveMode,
        smartTemplateName,
        pendingEditorExit,
        selectedEditorTemplate,
        enterSheetWorkspace,
        leaveSheetWorkspace,
        zoomInSheet,
        zoomOutSheet,
        zoomSheetWheel,
        fitSheetToScreen,
        recalculateNow,
        selectSheetRow,
        selectSheetColumn,
        selectWholeSheet,
        isSheetRowSelected,
        isSheetColumnSelected,
        beginDockDrag,
        dockPanelStyle,
        requestTemplateSave,
        cancelTemplateSave,
        leaveWithoutTemplateSave,
        saveEditorTemplate,
        clearUserPassword
    };
}
