const { ref, reactive, computed } = Vue;

export function createScheduleState(addToast, activeWorkspaceId) {
    const step = ref(1);
    const sessionId = ref(null);
    const analyzedFiles = ref([]);
    const layouts = reactive({});
    const validations = reactive({});
    const selectedFileId = ref(null);
    const preview = ref(null);
    const previewRegion = ref('schedule');
    const previewBusy = ref(false);
    const uploadBusy = ref(false);
    const validateBusy = ref(false);
    const generateBusy = ref(false);
    const result = ref(null);

    const currentFile = computed(
        () => analyzedFiles.value.find(item => item.file_id === selectedFileId.value) || null
    );
    const currentLayout = computed(
        () => currentFile.value ? layouts[currentFile.value.file_id] : null
    );
    const currentValidation = computed(
        () => currentFile.value ? validations[currentFile.value.file_id] : null
    );
    const enabledFiles = computed(
        () => analyzedFiles.value.filter(item => item.enabled && item.analysis)
    );
    const checkedFilesCount = computed(
        () => enabledFiles.value.filter(item => validations[item.file_id]).length
    );
    const canGenerate = computed(() =>
        Boolean(enabledFiles.value.length) && enabledFiles.value.every(item => {
            const validation = validations[item.file_id];
            return validation?.report
                && !validation.report.errors?.length
                && validation.report.lesson_count > 0;
        })
    );

    const copy = value => JSON.parse(JSON.stringify(value));
    const numeric = value => {
        if (value === '' || value === null || value === undefined) return null;
        return Number.isFinite(Number(value)) ? Math.trunc(Number(value)) : null;
    };

    const normalizedLayout = layout => {
        const value = copy(layout || {});
        [
            'months_row', 'grid_end_row', 'teacher_row_offset',
            'legend_start_row', 'legend_end_row', 'legend_code_col',
            'legend_subject_col', 'legend_lecturer_col', 'legend_other_col'
        ].forEach(key => value[key] = numeric(value[key]));
        [
            'weeks_row', 'first_week_col', 'last_week_col', 'week_col_step',
            'week_data_col_offset', 'grid_start_row', 'day_block_rows',
            'pairs_per_day', 'pair_row_stride', 'date_row_offset',
            'code_row_offset', 'subject_row_offset', 'room_row_offset',
            'legend_data_start_offset'
        ].forEach(key => value[key] = Number(value[key] || 0));
        value.day_names = Array.isArray(value.day_names)
            ? value.day_names.map(item => String(item).trim()).filter(Boolean)
            : String(value.day_names || '').split(',').map(item => item.trim()).filter(Boolean);
        return value;
    };

    const colLetter = number => {
        let value = Number(number);
        let label = '';
        if (!Number.isFinite(value) || value < 1) return '—';
        while (value > 0) {
            value -= 1;
            label = String.fromCharCode(65 + value % 26) + label;
            value = Math.floor(value / 26);
        }
        return label;
    };
    const confidenceLabel = confidence => {
        const percent = Math.round((confidence || 0) * 100);
        return `${percent}% · ${percent >= 75 ? 'высокая' : percent >= 55 ? 'средняя' : 'низкая'}`;
    };
    const confidenceClass = confidence =>
        (confidence || 0) >= .75
            ? 'confidence-good'
            : (confidence || 0) >= .55
                ? 'confidence-medium'
                : 'confidence-low';

    const markFileDirty = id => {
        if (id) delete validations[id];
    };
    const markDirty = () => markFileDirty(currentFile.value?.file_id);
    const invalidateAll = () => Object.keys(validations).forEach(key => delete validations[key]);

    const analyzeFiles = async files => {
        if (!files?.length) return;
        uploadBusy.value = true;
        result.value = null;
        const form = new FormData();
        Array.from(files).forEach(file => form.append('files', file));
        try {
            const { data } = await axios.post('/api/analyze', form, {
                headers: { 'Content-Type': 'multipart/form-data' }
            });
            sessionId.value = data.session_id;
            analyzedFiles.value = data.files.map(item => ({
                ...item,
                enabled: item.status !== 'error'
            }));
            Object.keys(layouts).forEach(key => delete layouts[key]);
            invalidateAll();
            analyzedFiles.value.forEach(item => {
                if (item.analysis) layouts[item.file_id] = copy(item.analysis.layout);
            });
            const first = analyzedFiles.value.find(item => item.analysis);
            if (!first) {
                addToast('Файлы не распознаны', 'Ни один файл не удалось открыть.', 'error');
                return;
            }
            selectedFileId.value = first.file_id;
            step.value = 2;
            previewRegion.value = 'schedule';
            await loadPreview();
            const problems = analyzedFiles.value.filter(item => item.status !== 'success').length;
            addToast(
                'Анализ завершён',
                problems
                    ? `Файлов с замечаниями: ${problems}.`
                    : 'Все файлы получили автоматическую разметку.',
                problems ? 'warning' : 'success'
            );
        } catch (error) {
            addToast('Ошибка анализа', error.response?.data?.detail || 'Не удалось загрузить файлы.', 'error');
        } finally {
            uploadBusy.value = false;
        }
    };

    const handleFileInput = event => analyzeFiles(event.target.files);
    const handleDrop = event => analyzeFiles(event.dataTransfer.files);

    const selectFile = async id => {
        selectedFileId.value = id;
        previewRegion.value = 'schedule';
        await loadPreview();
    };

    const previewBounds = () => {
        const file = currentFile.value;
        const layout = currentLayout.value;
        if (!file || !layout) return null;
        const maxRow = file.analysis.max_row;
        const maxColumn = file.analysis.max_column;
        if (previewRegion.value === 'legend') {
            const columns = [
                layout.legend_code_col,
                layout.legend_subject_col,
                layout.legend_lecturer_col,
                layout.legend_other_col
            ].map(numeric).filter(Boolean);
            const start = numeric(layout.legend_start_row) || file.analysis.legend_preview.row_start;
            const end = numeric(layout.legend_end_row) || file.analysis.legend_preview.row_end;
            return {
                row_start: Math.max(1, start - 2),
                row_end: Math.min(maxRow, end + 2),
                col_start: Math.max(1, Math.min(...(columns.length ? columns : [1])) - 1),
                col_end: Math.min(maxColumn, Math.max(...(columns.length ? columns : [12])) + 2)
            };
        }
        const weeks = Number(layout.weeks_row || 1);
        const start = Number(layout.grid_start_row || weeks + 1);
        const end = numeric(layout.grid_end_row)
            || Math.min(maxRow, start + Number(layout.day_block_rows || 13) * (layout.day_names?.length || 6));
        return {
            row_start: Math.max(1, Math.min(weeks, start) - 2),
            row_end: Math.min(maxRow, end + 2),
            col_start: Math.max(1, Number(layout.first_week_col || 1) - 4),
            col_end: Math.min(maxColumn, Number(layout.last_week_col || 1) + 2)
        };
    };

    const loadPreview = async () => {
        if (!sessionId.value || !currentFile.value?.analysis) return;
        previewBusy.value = true;
        try {
            const { data } = await axios.get(
                `/api/analysis/${sessionId.value}/files/${currentFile.value.file_id}/preview`,
                {
                    params: {
                        region: previewRegion.value,
                        sheet_name:
                            currentLayout.value?.sheet_name
                            || currentFile.value.analysis.selected_sheet,
                        ...previewBounds()
                    }
                }
            );
            preview.value = data;
        } catch (error) {
            preview.value = null;
            addToast('Предпросмотр', error.response?.data?.detail || 'Не удалось открыть область.', 'error');
        } finally {
            previewBusy.value = false;
        }
    };

    const switchRegion = async region => {
        previewRegion.value = region;
        await loadPreview();
    };

    const copyLayoutToEnabled = () => {
        if (!currentLayout.value || !currentFile.value) return;
        let count = 0;
        enabledFiles.value.forEach(file => {
            if (file.file_id === currentFile.value.file_id) return;
            const layout = copy(normalizedLayout(currentLayout.value));
            if (!file.analysis.sheet_names.includes(layout.sheet_name)) {
                layout.sheet_name = file.analysis.selected_sheet;
            }
            layouts[file.file_id] = layout;
            markFileDirty(file.file_id);
            count += 1;
        });
        addToast('Разметка скопирована', `Обновлено файлов: ${count}.`, 'info');
    };

    const changeDayNames = event => {
        if (!currentLayout.value) return;
        currentLayout.value.day_names = event.target.value
            .split(',')
            .map(item => item.trim())
            .filter(Boolean);
        markDirty();
    };

    const applySuggestion = async () => {
        if (!currentFile.value?.analysis) return;
        layouts[currentFile.value.file_id] = copy(currentFile.value.analysis.layout);
        markDirty();
        await loadPreview();
    };

    const resolveTemplateLayout = template => {
        const definition = template?.layout || {};
        if (!Array.isArray(definition.components)) return copy(definition);
        const sheetNames = currentFile.value?.analysis?.sheet_names || [];
        const selected = definition.components.find(component =>
            sheetNames.includes(
                component.selector?.sheet_name || component.layout?.sheet_name
            )
        ) || definition.components[0];
        return copy(selected?.layout || {});
    };

    const applyTemplate = async template => {
        if (!template || !currentFile.value) return;
        const layout = resolveTemplateLayout(template);
        if (!currentFile.value.analysis.sheet_names.includes(layout.sheet_name)) {
            layout.sheet_name = currentFile.value.analysis.selected_sheet;
        }
        layouts[currentFile.value.file_id] = layout;
        markDirty();
        await loadPreview();
        addToast('Шаблон применён', template.name, 'success');
    };

    const validateFile = async file => {
        if (!file?.analysis || !file.enabled) return null;
        const { data } = await axios.post(
            `/api/analysis/${sessionId.value}/validate`,
            {
                file_id: file.file_id,
                group_name: file.group_name,
                layout: normalizedLayout(layouts[file.file_id]),
                workspace_id: activeWorkspaceId.value
            }
        );
        validations[file.file_id] = data;
        return data;
    };

    const validateCurrent = async () => {
        if (!currentFile.value) return;
        validateBusy.value = true;
        try {
            const validation = await validateFile(currentFile.value);
            const count = validation?.report?.lesson_count || 0;
            addToast(
                'Проверка разметки',
                validation.status === 'error'
                    ? (validation.report.errors || []).join(' ')
                    : `Распознано занятий: ${count}.`,
                validation.status
            );
        } catch (error) {
            addToast('Ошибка проверки', error.response?.data?.detail || 'Разметку проверить не удалось.', 'error');
        } finally {
            validateBusy.value = false;
        }
    };

    const validateAll = async () => {
        validateBusy.value = true;
        try {
            for (const file of enabledFiles.value) await validateFile(file);
            const invalid = enabledFiles.value.filter(file => {
                const report = validations[file.file_id]?.report;
                return !report || report.errors?.length || !report.lesson_count;
            });
            addToast(
                'Проверка файлов',
                invalid.length
                    ? `Файлов с критическими ошибками: ${invalid.length}.`
                    : 'Все выбранные файлы пригодны.',
                invalid.length ? 'warning' : 'success'
            );
            return !invalid.length;
        } catch (error) {
            addToast('Ошибка проверки', error.response?.data?.detail || 'Проверка остановлена.', 'error');
            return false;
        } finally {
            validateBusy.value = false;
        }
    };

    const generate = async () => {
        generateBusy.value = true;
        try {
            if (!await validateAll() || !canGenerate.value) {
                addToast('Формирование остановлено', 'Исправьте разметку файлов с ошибками.', 'error');
                return;
            }
            const payload = {
                workspace_id: activeWorkspaceId.value,
                files: analyzedFiles.value.map(file => ({
                    file_id: file.file_id,
                    group_name: file.group_name,
                    enabled: Boolean(file.enabled && file.analysis),
                    layout: file.analysis ? normalizedLayout(layouts[file.file_id]) : {}
                }))
            };
            const { data } = await axios.post(
                `/api/analysis/${sessionId.value}/generate`,
                payload
            );
            result.value = data;
            if (data.filename) {
                step.value = 3;
                addToast('Готово', data.message, data.status === 'success' ? 'success' : 'warning');
            } else {
                addToast('Не сформировано', data.message, 'error');
            }
        } catch (error) {
            addToast('Ошибка формирования', error.response?.data?.detail || 'Не удалось сформировать файл.', 'error');
        } finally {
            generateBusy.value = false;
        }
    };

    const fileStatus = file =>
        !file.enabled ? 'disabled' : validations[file.file_id]?.status || file.status;

    const cellClass = (row, cell) => {
        const layout = currentLayout.value;
        if (!layout) return {};
        const column = cell.column;
        return {
            'cell-merged': cell.merged,
            'cell-week':
                row.index === Number(layout.weeks_row)
                && column >= Number(layout.first_week_col)
                && column <= Number(layout.last_week_col),
            'cell-grid':
                row.index >= Number(layout.grid_start_row)
                && row.index <= Number(layout.grid_end_row || 999999)
                && column >= Number(layout.first_week_col)
                && column <= Number(layout.last_week_col),
            'cell-legend':
                layout.legend_start_row
                && row.index >= Number(layout.legend_start_row)
                && row.index <= Number(layout.legend_end_row || 999999)
        };
    };

    const resetWorkflow = async () => {
        if (sessionId.value) {
            try {
                await axios.delete(`/api/analysis/${sessionId.value}`);
            } catch (_) {
                // The session may already have expired.
            }
        }
        step.value = 1;
        sessionId.value = null;
        analyzedFiles.value = [];
        selectedFileId.value = null;
        preview.value = null;
        result.value = null;
        Object.keys(layouts).forEach(key => delete layouts[key]);
        invalidateAll();
    };

    return {
        step, sessionId, analyzedFiles, layouts, validations, selectedFileId,
        currentFile, currentLayout, currentValidation, preview, previewRegion,
        previewBusy, uploadBusy, validateBusy, generateBusy, result, enabledFiles,
        checkedFilesCount, canGenerate, colLetter, confidenceLabel, confidenceClass,
        markDirty, markFileDirty, invalidateAll, normalizedLayout, handleFileInput,
        handleDrop, selectFile, loadPreview, switchRegion, copyLayoutToEnabled,
        changeDayNames, applySuggestion, applyTemplate, validateCurrent, validateAll,
        generate, fileStatus, cellClass, resetWorkflow
    };
}
