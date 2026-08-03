import { buildPreviewBounds, copyLayout, numericLayoutValue, normalizeScheduleLayout, columnLetter, confidenceLabel, confidenceClass, scheduleCellClass } from './schedule-layout-utils.js';

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

    const currentFile = computed(() =>
        analyzedFiles.value.find(item => item.file_id === selectedFileId.value) || null
    );
    const currentLayout = computed(() =>
        currentFile.value ? layouts[currentFile.value.file_id] : null
    );
    const currentValidation = computed(() =>
        currentFile.value ? validations[currentFile.value.file_id] : null
    );
    const enabledFiles = computed(() =>
        analyzedFiles.value.filter(item => item.enabled && item.analysis)
    );
    const checkedFilesCount = computed(() =>
        enabledFiles.value.filter(item => validations[item.file_id]).length
    );
    const canGenerate = computed(() => Boolean(
        enabledFiles.value.length && enabledFiles.value.every(item => {
            const validation = validations[item.file_id];
            return validation?.report
                && !validation.report.errors?.length
                && validation.report.lesson_count > 0;
        })
    ));

    const copy = copyLayout;
    const numeric = numericLayoutValue;
    const normalizedLayout = normalizeScheduleLayout;
    const colLetter = columnLetter;

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
            addToast(
                'Ошибка анализа',
                error.response?.data?.detail || 'Не удалось загрузить файлы.',
                'error'
            );
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

    const previewBounds = () => buildPreviewBounds(currentFile.value, currentLayout.value, previewRegion.value);

    const loadPreview = async () => {
        if (!sessionId.value || !currentFile.value?.analysis) return;
        previewBusy.value = true;
        try {
            const { data } = await axios.get(
                `/api/analysis/${sessionId.value}/files/${currentFile.value.file_id}/preview`,
                {
                    params: {
                        region: previewRegion.value,
                        sheet_name: currentLayout.value?.sheet_name || currentFile.value.analysis.selected_sheet,
                        ...previewBounds()
                    }
                }
            );
            preview.value = data;
        } catch (error) {
            preview.value = null;
            addToast(
                'Предпросмотр',
                error.response?.data?.detail || 'Не удалось открыть область.',
                'error'
            );
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
    const applyTemplate = async template => {
        if (!template || !currentFile.value) return;
        const layout = copy(template.layout);
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
            addToast(
                'Ошибка проверки',
                error.response?.data?.detail || 'Разметку проверить не удалось.',
                'error'
            );
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
            addToast(
                'Ошибка проверки',
                error.response?.data?.detail || 'Проверка остановлена.',
                'error'
            );
            return false;
        } finally {
            validateBusy.value = false;
        }
    };
    const generate = async () => {
        generateBusy.value = true;
        try {
            if (!await validateAll() || !canGenerate.value) {
                addToast(
                    'Формирование остановлено',
                    'Исправьте разметку файлов с ошибками.',
                    'error'
                );
                return;
            }
            const payload = {
                workspace_id: activeWorkspaceId.value,
                files: analyzedFiles.value.map(file => ({
                    file_id: file.file_id,
                    group_name: file.group_name,
                    enabled: Boolean(file.enabled && file.analysis),
                    layout: file.analysis
                        ? normalizedLayout(layouts[file.file_id])
                        : {}
                }))
            };
            const { data } = await axios.post(
                `/api/analysis/${sessionId.value}/generate`,
                payload
            );
            result.value = data;
            if (data.filename) {
                step.value = 3;
                addToast(
                    'Готово',
                    data.message,
                    data.status === 'success' ? 'success' : 'warning'
                );
            } else {
                addToast('Не сформировано', data.message, 'error');
            }
        } catch (error) {
            addToast(
                'Ошибка формирования',
                error.response?.data?.detail || 'Не удалось сформировать файл.',
                'error'
            );
        } finally {
            generateBusy.value = false;
        }
    };

    const fileStatus = file =>
        !file.enabled ? 'disabled' : validations[file.file_id]?.status || file.status;

    const cellClass = (row, cell) => scheduleCellClass(currentLayout.value, row, cell);

    const resetWorkflow = async () => {
        if (sessionId.value) {
            try {
                await axios.delete(`/api/analysis/${sessionId.value}`);
            } catch (_) {
                // The server may already have cleaned an expired session.
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
        step,
        sessionId,
        analyzedFiles,
        layouts,
        validations,
        selectedFileId,
        currentFile,
        currentLayout,
        currentValidation,
        preview,
        previewRegion,
        previewBusy,
        uploadBusy,
        validateBusy,
        generateBusy,
        result,
        enabledFiles,
        checkedFilesCount,
        canGenerate,
        colLetter,
        confidenceLabel,
        confidenceClass,
        markDirty,
        markFileDirty,
        invalidateAll,
        normalizedLayout,
        handleFileInput,
        handleDrop,
        selectFile,
        loadPreview,
        switchRegion,
        copyLayoutToEnabled,
        changeDayNames,
        applySuggestion,
        applyTemplate,
        validateCurrent,
        validateAll,
        generate,
        fileStatus,
        cellClass,
        resetWorkflow
    };
}
