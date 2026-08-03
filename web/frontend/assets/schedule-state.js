import { buildPreviewBounds, copyLayout, numericLayoutValue, normalizeScheduleLayout, columnLetter, confidenceLabel, confidenceClass, scheduleCellClass } from './schedule-layout-utils.js';

const { ref, reactive, computed, nextTick } = Vue;
const DAY_ORDER = { 'Пн': 0, 'Вт': 1, 'Ср': 2, 'Чт': 3, 'Пт': 4, 'Сб': 5 };
const MONTH_OPTIONS = [
    'Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
    'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь'
];

export function createScheduleState(addToast, activeWorkspaceId) {
    const step = ref(1);
    const sessionId = ref(null);
    const analyzedFiles = ref([]);
    const layouts = reactive({});
    const validations = reactive({});
    const periodOverrides = reactive({});
    const calendarOverrides = reactive({
        policy: 'auto',
        week_day_dates: {},
        week_months: {}
    });
    const periodEditorOpen = ref(false);
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
    const canGenerate = computed(() => enabledFiles.value.length > 0);

    const currentIssues = computed(() => {
        const report = currentValidation.value?.report || {};
        const periodIssues = report.period?.issues || [];
        const technical = (report.errors || []).map(message => ({
            severity: 'warning',
            code: 'technical_file_issue',
            message,
            blocking: false,
            action: { type: 'edit_layout', label: 'Проверить этот файл на месте' }
        }));
        return [...technical, ...periodIssues];
    });
    const currentAutoRepairs = computed(() => currentValidation.value?.report?.auto_repairs || []);
    const currentActions = computed(() => currentValidation.value?.report?.actions || []);

    const ensurePeriodOverrides = fileId => {
        if (!fileId) return { week_day_dates: {}, week_months: {} };
        if (!periodOverrides[fileId]) {
            periodOverrides[fileId] = { week_day_dates: {}, week_months: {} };
        }
        periodOverrides[fileId].week_day_dates ||= {};
        periodOverrides[fileId].week_months ||= {};
        return periodOverrides[fileId];
    };
    const currentPeriodOverride = computed(() => ensurePeriodOverrides(currentFile.value?.file_id));

    const currentPeriodRows = computed(() => {
        const dates = currentValidation.value?.report?.period?.week_day_dates || {};
        const overrides = currentPeriodOverride.value.week_day_dates || {};
        return Object.entries(dates).map(([slot, detected]) => {
            const [weekRaw, dayName] = slot.split(':');
            const year = Number(detected?.year || 0);
            const day = Number(detected?.day || 0);
            const month = String(detected?.month || '');
            const detectedLabel = [day || '—', month.toLocaleLowerCase('ru'), year || ''].filter(Boolean).join(' ');
            return {
                slot,
                week: Number(weekRaw),
                dayName,
                detected,
                detectedLabel,
                value: String(overrides[slot] || '')
            };
        }).sort((left, right) =>
            left.week - right.week || (DAY_ORDER[left.dayName] ?? 99) - (DAY_ORDER[right.dayName] ?? 99)
        );
    });

    const currentWeekMonthRows = computed(() => {
        const period = currentValidation.value?.report?.period || {};
        const sets = period.week_month_sets || {};
        const simple = period.week_months || {};
        const weeks = new Set([
            ...Object.keys(sets),
            ...Object.keys(simple),
            ...((period.week_numbers || []).map(String))
        ]);
        const overrides = currentPeriodOverride.value.week_months || {};
        return [...weeks].map(rawWeek => ({
            week: Number(rawWeek),
            detected: (sets[rawWeek] || (simple[rawWeek] ? [simple[rawWeek]] : [])).join(' → '),
            value: String(overrides[rawWeek] || '')
        })).sort((left, right) => left.week - right.week);
    });

    const copy = copyLayout;
    const numeric = numericLayoutValue;
    const normalizedLayout = normalizeScheduleLayout;
    const colLetter = columnLetter;

    const markFileDirty = id => {
        if (id) delete validations[id];
    };
    const markDirty = () => markFileDirty(currentFile.value?.file_id);
    const markPeriodDirty = () => {
        const validation = currentValidation.value;
        if (!validation?.report) return;
        validation.status = 'warning';
        validation.report.period_overrides_pending = true;
    };
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
                enabled: Boolean(item.analysis)
            }));
            Object.keys(layouts).forEach(key => delete layouts[key]);
            Object.keys(periodOverrides).forEach(key => delete periodOverrides[key]);
            invalidateAll();
            analyzedFiles.value.forEach(item => {
                if (item.analysis) {
                    layouts[item.file_id] = copy(item.analysis.layout);
                    ensurePeriodOverrides(item.file_id);
                }
            });
            const first = analyzedFiles.value.find(item => item.analysis);
            if (!first) {
                addToast('Файлы не открыты', 'Ни один файл не удалось прочитать. Выберите другой файл.', 'warning');
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
                    ? `Файлов с подсказками: ${problems}. Они не блокируют формирование.`
                    : 'Все файлы получили автоматическую разметку.',
                problems ? 'warning' : 'success'
            );
        } catch (error) {
            addToast(
                'Файлы не загружены',
                error.response?.data?.detail || 'Не удалось передать файлы на сервер.',
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
        ensurePeriodOverrides(id);
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
                error.response?.data?.detail || 'Не удалось открыть область. Разметку можно изменить вручную.',
                'warning'
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
                workspace_id: activeWorkspaceId.value,
                period_overrides: copy(ensurePeriodOverrides(file.file_id))
            }
        );
        validations[file.file_id] = data;
        return data;
    };

    const applyRecoveredLayout = async () => {
        const report = currentValidation.value?.report;
        const file = currentFile.value;
        if (!report?.layout_used || !file) return;
        layouts[file.file_id] = copy(report.layout_used);
        delete validations[file.file_id];
        await loadPreview();
        addToast('Автоисправления применены', 'Координаты обновлены; их можно продолжить менять вручную.', 'success');
    };

    const updatePeriodDate = (slot, value) => {
        const state = ensurePeriodOverrides(currentFile.value?.file_id);
        if (value) state.week_day_dates[slot] = value;
        else delete state.week_day_dates[slot];
        markPeriodDirty();
    };
    const updateWeekMonth = (week, value) => {
        const state = ensurePeriodOverrides(currentFile.value?.file_id);
        if (value) state.week_months[String(week)] = value;
        else delete state.week_months[String(week)];
        markPeriodDirty();
    };
    const clearCurrentPeriodOverrides = () => {
        const state = ensurePeriodOverrides(currentFile.value?.file_id);
        Object.keys(state.week_day_dates).forEach(key => delete state.week_day_dates[key]);
        Object.keys(state.week_months).forEach(key => delete state.week_months[key]);
        markPeriodDirty();
        addToast('Правки дат очищены', 'При следующей проверке снова применится автоматическое восстановление.', 'info');
    };
    const setCalendarPolicy = value => {
        calendarOverrides.policy = ['auto', 'source', 'workspace'].includes(value) ? value : 'auto';
    };

    const openLayoutCorrection = async action => {
        periodEditorOpen.value = false;
        const field = action?.field;
        await nextTick();
        const fieldTarget = field
            ? document.querySelector(`[v-model\\.number="currentLayout.${field}"], [v-model="currentLayout.${field}"]`)
            : null;
        const target = fieldTarget || document.querySelector('.range-editor') || document.querySelector('.exact-layout-editor');
        target?.scrollIntoView({ behavior: 'smooth', block: 'center' });
        target?.focus?.();
        addToast('Правка на месте', action?.label || 'Уточните выделение или координату и пересчитайте файл.', 'info');
    };

    const applyParserAction = async action => {
        if (!action) return;
        if (action.type === 'calendar_policy') {
            setCalendarPolicy(action.value);
            addToast('Способ календаря выбран', action.label || 'Настройка применится при формировании.', 'success');
            return;
        }
        if (action.type === 'edit_period') {
            periodEditorOpen.value = true;
            await nextTick();
            document.querySelector('.period-recovery-section')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
            return;
        }
        if (action.type === 'layout_patch') {
            await applyRecoveredLayout();
            return;
        }
        if (action.type === 'edit_layout') {
            await openLayoutCorrection(action);
            return;
        }
        addToast('Действие оператора', action.label || 'Используйте соответствующую панель на текущем экране.', 'info');
    };

    const validateCurrent = async () => {
        if (!currentFile.value) return;
        validateBusy.value = true;
        try {
            const validation = await validateFile(currentFile.value);
            const count = validation?.report?.lesson_count || 0;
            addToast(
                'Проверка разметки',
                count
                    ? `Распознано занятий: ${count}. Замечания можно исправить здесь же или оставить автоматике.`
                    : 'Занятия пока не найдены. Укажите сетку на текущем листе; файл загружать повторно не требуется.',
                count ? (validation.status === 'success' ? 'success' : 'warning') : 'warning'
            );
        } catch (error) {
            addToast(
                'Проверка не завершена',
                error.response?.data?.detail || 'Сервер не проверил файл, но попытка формирования всё равно доступна.',
                'warning'
            );
        } finally {
            validateBusy.value = false;
        }
    };

    const validateAll = async () => {
        validateBusy.value = true;
        let recovered = 0;
        let unavailable = 0;
        try {
            for (const file of enabledFiles.value) {
                try {
                    const validation = await validateFile(file);
                    if ((validation?.report?.lesson_count || 0) > 0) recovered += 1;
                } catch (error) {
                    unavailable += 1;
                    validations[file.file_id] = {
                        status: 'warning',
                        report: {
                            lesson_count: 0,
                            mapped_lessons: 0,
                            unknown_teacher_lessons: 0,
                            errors: [],
                            warnings: [error.response?.data?.detail || 'Предварительная проверка недоступна.'],
                            actions: [{ type: 'edit_layout', label: 'Повторить проверку на месте', blocking: false }],
                            generation_allowed: true,
                            blocking: false
                        }
                    };
                }
            }
            addToast(
                'Проверка файлов',
                `Файлов с извлечёнными занятиями: ${recovered}. Файлов, которые будут восстановлены при формировании: ${enabledFiles.value.length - recovered}.`,
                unavailable || recovered < enabledFiles.value.length ? 'warning' : 'success'
            );
            return true;
        } finally {
            validateBusy.value = false;
        }
    };

    const generate = async () => {
        generateBusy.value = true;
        try {
            await validateAll();
            const payload = {
                workspace_id: activeWorkspaceId.value,
                allow_partial: true,
                calendar_overrides: {
                    policy: calendarOverrides.policy,
                    week_day_dates: { ...(calendarOverrides.week_day_dates || {}) },
                    week_months: { ...(calendarOverrides.week_months || {}) }
                },
                files: analyzedFiles.value.map(file => ({
                    file_id: file.file_id,
                    group_name: file.group_name,
                    enabled: Boolean(file.enabled && file.analysis),
                    layout: file.analysis
                        ? normalizedLayout(layouts[file.file_id])
                        : {},
                    period_overrides: file.analysis
                        ? copy(ensurePeriodOverrides(file.file_id))
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
                    'Результат готов',
                    data.message,
                    data.status === 'success' ? 'success' : 'warning'
                );
            } else {
                addToast('Нужно выбрать файл', data.message, 'warning');
            }
        } catch (error) {
            addToast(
                'Формирование не завершено',
                error.response?.data?.detail || 'Произошла техническая ошибка сервера. Загруженные файлы остаются в текущем сеансе.',
                'error'
            );
        } finally {
            generateBusy.value = false;
        }
    };

    const fileStatus = file => {
        if (!file.enabled) return 'disabled';
        const status = validations[file.file_id]?.status || file.status;
        return status === 'error' ? 'warning' : status;
    };

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
        periodEditorOpen.value = false;
        Object.keys(layouts).forEach(key => delete layouts[key]);
        Object.keys(periodOverrides).forEach(key => delete periodOverrides[key]);
        Object.keys(calendarOverrides.week_day_dates).forEach(key => delete calendarOverrides.week_day_dates[key]);
        Object.keys(calendarOverrides.week_months).forEach(key => delete calendarOverrides.week_months[key]);
        calendarOverrides.policy = 'auto';
        invalidateAll();
    };

    return {
        step,
        sessionId,
        analyzedFiles,
        layouts,
        validations,
        periodOverrides,
        calendarOverrides,
        periodEditorOpen,
        selectedFileId,
        currentFile,
        currentLayout,
        currentValidation,
        currentIssues,
        currentAutoRepairs,
        currentActions,
        currentPeriodRows,
        currentWeekMonthRows,
        currentPeriodOverride,
        monthOptions: MONTH_OPTIONS,
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
        applyRecoveredLayout,
        updatePeriodDate,
        updateWeekMonth,
        clearCurrentPeriodOverrides,
        setCalendarPolicy,
        applyParserAction,
        validateCurrent,
        validateAll,
        generate,
        fileStatus,
        cellClass,
        resetWorkflow
    };
}
