const { ref, reactive, computed, onBeforeUnmount } = Vue;

export function createInteractionState(addToast, schedule, activeWorkspaceId) {
    const templateMatchBusy = ref(false);
    const templateMatchProgress = reactive({ done: 0, total: 0 });
    const uploadProgress = reactive({ loaded: 0, total: 0, percent: 0 });
    const selectionMode = ref('grid');
    const selectedRange = ref(null);
    const selectionAnchor = ref(null);
    const dragState = ref(null);
    const lastLayoutSnapshot = ref(null);
    let matchRun = 0;
    let uploadRun = 0;

    const copy = value => JSON.parse(JSON.stringify(value));
    const clamp = (value, minimum, maximum) => Math.max(minimum, Math.min(maximum, value));
    const canUndoInteractiveChange = computed(() => Boolean(lastLayoutSnapshot.value));

    const candidateKey = candidate => candidate?.candidate_key || `${candidate?.source || 'automatic'}:${candidate?.template_id || 'automatic'}`;
    const formatBytes = value => {
        const bytes = Number(value || 0);
        if (bytes < 1024) return `${bytes} Б`;
        const units = ['КБ', 'МБ', 'ГБ', 'ТБ'];
        let size = bytes / 1024, index = 0;
        while (size >= 1024 && index < units.length - 1) { size /= 1024; index += 1; }
        return `${size >= 100 ? size.toFixed(0) : size.toFixed(1)} ${units[index]}`;
    };
    const templateMatchDescription = candidate => (candidate?.reasons || []).slice(0, 3).join(' · ');

    const analyzeFiles = async files => {
        const list = Array.from(files || []);
        if (!list.length) return;
        const run = ++uploadRun;
        const previousSession = schedule.sessionId.value;
        uploadProgress.loaded = 0;
        uploadProgress.total = list.reduce((sum, file) => sum + Number(file.size || 0), 0);
        uploadProgress.percent = 0;
        schedule.uploadBusy.value = true;
        schedule.result.value = null;
        const form = new FormData();
        list.forEach(file => form.append('files', file));
        try {
            const { data } = await axios.post('/api/analyze', form, {
                headers: { 'Content-Type': 'multipart/form-data' },
                onUploadProgress: event => {
                    uploadProgress.loaded = Number(event.loaded || 0);
                    uploadProgress.total = Number(event.total || uploadProgress.total || 0);
                    uploadProgress.percent = uploadProgress.total
                        ? Math.min(100, Math.round(uploadProgress.loaded * 100 / uploadProgress.total))
                        : 0;
                }
            });
            if (run !== uploadRun) return;
            uploadProgress.loaded = uploadProgress.total;
            uploadProgress.percent = 100;
            if (previousSession) {
                axios.delete(`/api/analysis/${previousSession}`).catch(() => {});
            }
            schedule.sessionId.value = data.session_id;
            schedule.analyzedFiles.value = data.files.map(file => ({
                ...file,
                enabled: file.status !== 'error',
                matching: false,
                template_match: null,
                template_candidates: []
            }));
            Object.keys(schedule.layouts).forEach(key => delete schedule.layouts[key]);
            schedule.invalidateAll();
            schedule.analyzedFiles.value.forEach(file => {
                if (file.analysis) schedule.layouts[file.file_id] = copy(file.analysis.layout);
            });
            const first = schedule.analyzedFiles.value.find(file => file.analysis);
            if (!first) {
                addToast('Файлы не распознаны', 'Ни один файл не удалось открыть.', 'error');
                return;
            }
            schedule.selectedFileId.value = first.file_id;
            schedule.step.value = 2;
            schedule.previewRegion.value = 'schedule';
            clearRangeSelection();
            await schedule.loadPreview();
            schedule.uploadBusy.value = false;
            await rematchTemplates({ quiet: true });
            const problems = schedule.analyzedFiles.value.filter(file => file.status !== 'success').length;
            addToast(
                'Анализ завершён',
                problems ? `Файлов с замечаниями: ${problems}.` : 'Все файлы получили проверенную разметку.',
                problems ? 'warning' : 'success'
            );
        } catch (error) {
            addToast('Ошибка анализа', error.response?.data?.detail || 'Не удалось загрузить файлы.', 'error');
        } finally {
            if (run === uploadRun) schedule.uploadBusy.value = false;
        }
    };

    const handleFileInput = async event => {
        const files = event.target.files;
        await analyzeFiles(files);
        event.target.value = '';
    };
    const handleDrop = event => analyzeFiles(event.dataTransfer.files);

    const rematchTemplates = async ({ quiet = false } = {}) => {
        if (!schedule.sessionId.value || !activeWorkspaceId.value) return;
        const files = schedule.analyzedFiles.value.filter(file => file.analysis);
        const run = ++matchRun;
        templateMatchBusy.value = true;
        templateMatchProgress.done = 0;
        templateMatchProgress.total = files.length;
        let templateWins = 0;
        let failed = 0;
        for (const file of files) {
            if (run !== matchRun) break;
            file.matching = true;
            try {
                const { data } = await axios.post(
                    `/api/analysis/${schedule.sessionId.value}/files/${file.file_id}/match-templates`,
                    { workspace_id: activeWorkspaceId.value }
                );
                file.template_candidates = data.candidates || [];
                file.template_match = data.selected || null;
                if (data.selected?.usable && data.selected?.layout) {
                    schedule.layouts[file.file_id] = copy(data.selected.layout);
                    schedule.markFileDirty(file.file_id);
                }
                if (data.selected?.source === 'template') templateWins += 1;
            } catch (error) {
                failed += 1;
                file.template_match = null;
                file.template_candidates = [];
                if (!quiet) {
                    addToast(
                        'Автоподбор разметки',
                        error.response?.data?.detail || `Не удалось проверить шаблоны для «${file.filename}».`,
                        'warning'
                    );
                }
            } finally {
                file.matching = false;
                templateMatchProgress.done += 1;
            }
        }
        if (run === matchRun) {
            templateMatchBusy.value = false;
            if (schedule.currentFile.value?.analysis) await schedule.loadPreview();
            if (!quiet) {
                addToast(
                    'Шаблоны проверены',
                    `Файлов: ${files.length}; шаблон выбран для ${templateWins}; ошибок проверки: ${failed}.`,
                    failed ? 'warning' : 'success'
                );
            }
        }
    };

    const applyMatchCandidate = async key => {
        const file = schedule.currentFile.value;
        if (!file) return;
        const candidate = (file.template_candidates || []).find(item => candidateKey(item) === key);
        if (!candidate?.layout) return;
        lastLayoutSnapshot.value = copy(schedule.currentLayout.value);
        schedule.layouts[file.file_id] = copy(candidate.layout);
        file.template_match = candidate;
        schedule.markFileDirty(file.file_id);
        clearRangeSelection();
        await schedule.loadPreview();
        addToast('Разметка применена', candidate.name, candidate.usable ? 'success' : 'warning');
    };

    const normalizedRange = (row1, col1, row2, col2) => ({
        rowStart: Math.min(row1, row2),
        rowEnd: Math.max(row1, row2),
        colStart: Math.min(col1, col2),
        colEnd: Math.max(col1, col2)
    });

    const isInsideRange = (range, row, col) => Boolean(
        range && row >= range.rowStart && row <= range.rowEnd && col >= range.colStart && col <= range.colEnd
    );

    const isCellSelected = (row, col) => isInsideRange(selectedRange.value, Number(row), Number(col));

    const beginRangeSelection = (row, col, event) => {
        if (event.pointerType === 'mouse' && event.button !== 0) return;
        event.preventDefault();
        const numericRow = Number(row), numericCol = Number(col);
        const moveExisting = event.altKey && isInsideRange(selectedRange.value, numericRow, numericCol);
        dragState.value = moveExisting
            ? { type: 'move', row: numericRow, col: numericCol, original: { ...selectedRange.value } }
            : { type: 'select', row: numericRow, col: numericCol };
        if (!moveExisting) {
            selectionAnchor.value = { row: numericRow, col: numericCol };
            selectedRange.value = normalizedRange(numericRow, numericCol, numericRow, numericCol);
        }
        document.documentElement.classList.add('parser-range-selecting');
    };

    const pointerCell = event => {
        const element = document.elementFromPoint(event.clientX, event.clientY)?.closest?.('[data-parser-cell]');
        if (!element) return null;
        const row = Number(element.dataset.row), col = Number(element.dataset.col);
        return Number.isFinite(row) && Number.isFinite(col) ? { row, col } : null;
    };

    const moveRangeSelection = event => {
        if (!dragState.value) return;
        const cell = pointerCell(event);
        if (!cell) return;
        event.preventDefault();
        if (dragState.value.type === 'select') {
            selectedRange.value = normalizedRange(
                selectionAnchor.value.row,
                selectionAnchor.value.col,
                cell.row,
                cell.col
            );
            return;
        }
        const file = schedule.currentFile.value;
        const maxRow = file?.analysis?.max_row || Number.MAX_SAFE_INTEGER;
        const maxCol = file?.analysis?.max_column || Number.MAX_SAFE_INTEGER;
        const original = dragState.value.original;
        let rowDelta = cell.row - dragState.value.row;
        let colDelta = cell.col - dragState.value.col;
        rowDelta = clamp(rowDelta, 1 - original.rowStart, maxRow - original.rowEnd);
        colDelta = clamp(colDelta, 1 - original.colStart, maxCol - original.colEnd);
        selectedRange.value = {
            rowStart: original.rowStart + rowDelta,
            rowEnd: original.rowEnd + rowDelta,
            colStart: original.colStart + colDelta,
            colEnd: original.colEnd + colDelta
        };
    };

    const applySelectedRange = () => {
        const range = selectedRange.value;
        const layout = schedule.currentLayout.value;
        if (!range || !layout) return;
        lastLayoutSnapshot.value = copy(layout);
        switch (selectionMode.value) {
            case 'weeks':
                layout.weeks_row = range.rowStart;
                layout.first_week_col = range.colStart;
                layout.last_week_col = range.colEnd;
                break;
            case 'months':
                layout.months_row = range.rowStart;
                layout.first_week_col = range.colStart;
                layout.last_week_col = range.colEnd;
                break;
            case 'legend':
                layout.legend_start_row = range.rowStart;
                layout.legend_end_row = range.rowEnd;
                break;
            case 'legend_code':
                layout.legend_code_col = range.colStart;
                break;
            case 'legend_subject':
                layout.legend_subject_col = range.colStart;
                break;
            case 'legend_lecturer':
                layout.legend_lecturer_col = range.colStart;
                break;
            case 'legend_other':
                layout.legend_other_col = range.colStart;
                break;
            default:
                layout.grid_start_row = range.rowStart;
                layout.grid_end_row = range.rowEnd;
                layout.first_week_col = range.colStart;
                layout.last_week_col = range.colEnd;
        }
        schedule.markDirty();
    };

    const finishRangeSelection = () => {
        if (!dragState.value) return;
        dragState.value = null;
        document.documentElement.classList.remove('parser-range-selecting');
        applySelectedRange();
    };

    const selectSingleCell = (row, col) => {
        selectionAnchor.value = { row: Number(row), col: Number(col) };
        selectedRange.value = normalizedRange(Number(row), Number(col), Number(row), Number(col));
        applySelectedRange();
    };

    const setSelectionMode = mode => {
        selectionMode.value = mode;
        clearRangeSelection();
        if (mode.startsWith('legend') && schedule.previewRegion.value !== 'legend') {
            schedule.switchRegion('legend');
        } else if (!mode.startsWith('legend') && schedule.previewRegion.value !== 'schedule') {
            schedule.switchRegion('schedule');
        }
    };

    const clearRangeSelection = () => {
        selectedRange.value = null;
        selectionAnchor.value = null;
        dragState.value = null;
        document.documentElement.classList.remove('parser-range-selecting');
    };

    const undoInteractiveChange = async () => {
        const file = schedule.currentFile.value;
        if (!file || !lastLayoutSnapshot.value) return;
        schedule.layouts[file.file_id] = copy(lastLayoutSnapshot.value);
        lastLayoutSnapshot.value = null;
        schedule.markFileDirty(file.file_id);
        clearRangeSelection();
        await schedule.loadPreview();
    };

    const interactiveCellClass = (row, cell) => {
        const range = selectedRange.value;
        const r = Number(row.index), c = Number(cell.column);
        if (!isInsideRange(range, r, c)) return { 'parser-cell': true };
        return {
            'parser-cell': true,
            'parser-selected': true,
            'parser-selected-top': r === range.rowStart,
            'parser-selected-bottom': r === range.rowEnd,
            'parser-selected-left': c === range.colStart,
            'parser-selected-right': c === range.colEnd
        };
    };

    const selectionHint = computed(() => {
        const labels = {
            grid: 'Выделите прямоугольник сетки занятий.',
            weeks: 'Проведите по строке с номерами недель.',
            months: 'Проведите по строке с названиями месяцев.',
            legend: 'Выделите весь блок дисциплин и преподавателей.',
            legend_code: 'Щёлкните столбец обозначения дисциплины.',
            legend_subject: 'Щёлкните столбец названия дисциплины.',
            legend_lecturer: 'Щёлкните столбец лектора.',
            legend_other: 'Щёлкните столбец остальных преподавателей.'
        };
        const range = selectedRange.value;
        if (!range) return `${labels[selectionMode.value]} Alt/Option + перетаскивание перемещает уже выбранную область.`;
        return `Выбрано: строки ${range.rowStart}–${range.rowEnd}, столбцы ${schedule.colLetter(range.colStart)}–${schedule.colLetter(range.colEnd)}. Изменения уже отражены в параметрах.`;
    });

    const selectFile = async id => {
        clearRangeSelection();
        lastLayoutSnapshot.value = null;
        await schedule.selectFile(id);
    };
    const switchRegion = async region => {
        clearRangeSelection();
        await schedule.switchRegion(region);
    };
    const resetWorkflow = async () => {
        ++matchRun;
        ++uploadRun;
        templateMatchBusy.value = false;
        clearRangeSelection();
        lastLayoutSnapshot.value = null;
        await schedule.resetWorkflow();
    };

    window.addEventListener('pointermove', moveRangeSelection, { passive: false });
    window.addEventListener('pointerup', finishRangeSelection);
    window.addEventListener('pointercancel', finishRangeSelection);
    onBeforeUnmount(() => {
        window.removeEventListener('pointermove', moveRangeSelection);
        window.removeEventListener('pointerup', finishRangeSelection);
        window.removeEventListener('pointercancel', finishRangeSelection);
    });

    return {
        templateMatchBusy,
        templateMatchProgress,
        uploadProgress,
        formatBytes,
        selectionMode,
        selectedRange,
        canUndoInteractiveChange,
        candidateKey,
        templateMatchDescription,
        handleFileInput,
        handleDrop,
        rematchTemplates,
        applyMatchCandidate,
        beginRangeSelection,
        selectSingleCell,
        setSelectionMode,
        clearRangeSelection,
        undoInteractiveChange,
        interactiveCellClass,
        isCellSelected,
        selectionHint,
        selectFile,
        switchRegion,
        resetWorkflow
    };
}
