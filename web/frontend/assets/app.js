const { createApp, ref, reactive, computed, onMounted } = Vue;

createApp({
    setup() {
        const step = ref(1);
        const teachers = ref([]);
        const teacherForm = reactive({
            id: null,
            short_name: '',
            full_name: '',
            position: '',
            rank: '',
            academic_degree: ''
        });
        const editingTeacher = ref(false);
        const teacherBusy = ref(false);
        const showTeachers = ref(false);

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
        const toasts = ref([]);
        const layoutProfiles = ref([]);
        const profileName = ref('');
        const selectedProfile = ref('');
        const PROFILE_STORAGE_KEY = 'planner-solving-layout-profiles-v1';

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
        const canGenerate = computed(() => {
            if (!enabledFiles.value.length) return false;
            return enabledFiles.value.every(item => {
                const validation = validations[item.file_id];
                return validation &&
                    validation.report &&
                    !validation.report.errors?.length &&
                    validation.report.lesson_count > 0;
            });
        });

        const addToast = (title, message, type = 'info') => {
            const id = `${Date.now()}-${Math.random()}`;
            toasts.value.push({ id, title, message, type });
            setTimeout(() => {
                toasts.value = toasts.value.filter(item => item.id !== id);
            }, 6500);
        };

        const removeToast = (id) => {
            toasts.value = toasts.value.filter(item => item.id !== id);
        };

        const deepCopy = value => JSON.parse(JSON.stringify(value));

        const loadLayoutProfiles = () => {
            try {
                const stored = JSON.parse(localStorage.getItem(PROFILE_STORAGE_KEY) || '[]');
                layoutProfiles.value = Array.isArray(stored) ? stored : [];
            } catch (_) {
                layoutProfiles.value = [];
            }
        };

        const persistLayoutProfiles = () => {
            localStorage.setItem(PROFILE_STORAGE_KEY, JSON.stringify(layoutProfiles.value));
        };

        const colLetter = number => {
            let value = Number(number);
            if (!Number.isFinite(value) || value < 1) return '—';
            let label = '';
            while (value > 0) {
                value -= 1;
                label = String.fromCharCode(65 + (value % 26)) + label;
                value = Math.floor(value / 26);
            }
            return label;
        };

        const confidenceLabel = confidence => {
            const value = Math.round((confidence || 0) * 100);
            if (value >= 75) return `${value}% · высокая`;
            if (value >= 55) return `${value}% · средняя`;
            return `${value}% · низкая`;
        };

        const confidenceClass = confidence => {
            if ((confidence || 0) >= 0.75) return 'confidence-good';
            if ((confidence || 0) >= 0.55) return 'confidence-medium';
            return 'confidence-low';
        };

        const fetchTeachers = async () => {
            try {
                const response = await axios.get('/api/teachers');
                teachers.value = response.data;
            } catch (error) {
                addToast('Ошибка', 'Не удалось загрузить список преподавателей.', 'error');
            }
        };

        const resetTeacherForm = () => {
            Object.assign(teacherForm, {
                id: null,
                short_name: '',
                full_name: '',
                position: '',
                rank: '',
                academic_degree: ''
            });
            editingTeacher.value = false;
        };

        const editTeacher = teacher => {
            Object.assign(teacherForm, teacher);
            editingTeacher.value = true;
            showTeachers.value = true;
        };

        const saveTeacher = async () => {
            teacherBusy.value = true;
            try {
                if (editingTeacher.value) {
                    await axios.put(`/api/teachers/${teacherForm.id}`, teacherForm);
                    addToast('Сохранено', 'Данные преподавателя обновлены.', 'success');
                } else {
                    await axios.post('/api/teachers', teacherForm);
                    addToast('Добавлено', 'Преподаватель добавлен.', 'success');
                }
                resetTeacherForm();
                await fetchTeachers();
            } catch (error) {
                addToast('Ошибка', error.response?.data?.detail || 'Не удалось сохранить преподавателя.', 'error');
            } finally {
                teacherBusy.value = false;
            }
        };

        const deleteTeacher = async teacher => {
            if (!confirm(`Удалить ${teacher.short_name}?`)) return;
            try {
                await axios.delete(`/api/teachers/${teacher.id}`);
                await fetchTeachers();
                addToast('Удалено', 'Преподаватель удалён.', 'success');
            } catch (error) {
                addToast('Ошибка', 'Не удалось удалить преподавателя.', 'error');
            }
        };

        const analyzeFiles = async files => {
            if (!files || files.length === 0) return;
            uploadBusy.value = true;
            result.value = null;
            const formData = new FormData();
            Array.from(files).forEach(file => formData.append('files', file));

            try {
                const response = await axios.post('/api/analyze', formData, {
                    headers: { 'Content-Type': 'multipart/form-data' }
                });
                sessionId.value = response.data.session_id;
                analyzedFiles.value = response.data.files.map(item => ({
                    ...item,
                    enabled: item.status !== 'error'
                }));
                Object.keys(layouts).forEach(key => delete layouts[key]);
                Object.keys(validations).forEach(key => delete validations[key]);
                analyzedFiles.value.forEach(item => {
                    if (item.analysis) layouts[item.file_id] = deepCopy(item.analysis.layout);
                });

                const first = analyzedFiles.value.find(item => item.analysis);
                if (!first) {
                    addToast('Файлы не распознаны', 'Ни один файл не удалось открыть для анализа.', 'error');
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
                        ? `Файлов с предупреждениями или ошибками: ${problems}.`
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

        const selectFile = async fileId => {
            selectedFileId.value = fileId;
            previewRegion.value = 'schedule';
            await loadPreview();
        };

        const numericOrNull = value => {
            if (value === '' || value === undefined || value === null) return null;
            const number = Number(value);
            return Number.isFinite(number) ? Math.trunc(number) : null;
        };

        const normalizedLayout = layout => {
            const copy = deepCopy(layout);
            const optionalFields = [
                'months_row',
                'grid_end_row',
                'teacher_row_offset',
                'legend_start_row',
                'legend_end_row',
                'legend_code_col',
                'legend_subject_col',
                'legend_lecturer_col',
                'legend_other_col'
            ];
            const integerFields = [
                'weeks_row',
                'first_week_col',
                'last_week_col',
                'week_col_step',
                'week_data_col_offset',
                'grid_start_row',
                'day_block_rows',
                'pairs_per_day',
                'pair_row_stride',
                'date_row_offset',
                'code_row_offset',
                'subject_row_offset',
                'room_row_offset',
                'legend_data_start_offset'
            ];
            optionalFields.forEach(field => copy[field] = numericOrNull(copy[field]));
            integerFields.forEach(field => copy[field] = Number(copy[field] || 0));
            copy.day_names = Array.isArray(copy.day_names)
                ? copy.day_names.map(value => String(value).trim()).filter(Boolean)
                : String(copy.day_names || '').split(',').map(value => value.trim()).filter(Boolean);
            return copy;
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
                ].map(numericOrNull).filter(Boolean);
                const startRow = numericOrNull(layout.legend_start_row) ||
                    file.analysis.legend_preview.row_start;
                const endRow = numericOrNull(layout.legend_end_row) ||
                    file.analysis.legend_preview.row_end;
                return {
                    row_start: Math.max(1, startRow - 2),
                    row_end: Math.min(maxRow, endRow + 2),
                    col_start: Math.max(1, Math.min(...(columns.length ? columns : [1])) - 1),
                    col_end: Math.min(maxColumn, Math.max(...(columns.length ? columns : [12])) + 2)
                };
            }

            const weeksRow = Number(layout.weeks_row || 1);
            const gridStart = Number(layout.grid_start_row || weeksRow + 1);
            const gridEnd = numericOrNull(layout.grid_end_row) ||
                Math.min(maxRow, gridStart + Number(layout.day_block_rows || 13) * (layout.day_names?.length || 6));
            return {
                row_start: Math.max(1, Math.min(weeksRow, gridStart) - 2),
                row_end: Math.min(maxRow, gridEnd + 2),
                col_start: Math.max(1, Number(layout.first_week_col || 1) - 4),
                col_end: Math.min(maxColumn, Number(layout.last_week_col || 1) + 2)
            };
        };

        const loadPreview = async () => {
            if (!sessionId.value || !currentFile.value || !currentFile.value.analysis) return;
            previewBusy.value = true;
            try {
                const bounds = previewBounds();
                const response = await axios.get(
                    `/api/analysis/${sessionId.value}/files/${currentFile.value.file_id}/preview`,
                    {
                        params: {
                            region: previewRegion.value,
                            sheet_name: currentLayout.value?.sheet_name || currentFile.value.analysis.selected_sheet,
                            ...bounds
                        }
                    }
                );
                preview.value = response.data;
            } catch (error) {
                preview.value = null;
                addToast('Предпросмотр', error.response?.data?.detail || 'Не удалось открыть область листа.', 'error');
            } finally {
                previewBusy.value = false;
            }
        };

        const switchRegion = async region => {
            previewRegion.value = region;
            await loadPreview();
        };

        const markFileDirty = fileId => {
            if (fileId) delete validations[fileId];
        };

        const markDirty = () => {
            markFileDirty(currentFile.value?.file_id);
        };

        const saveCurrentProfile = () => {
            const name = profileName.value.trim();
            if (!name || !currentLayout.value) {
                addToast('Шаблон разметки', 'Введите название шаблона.', 'warning');
                return;
            }
            const profile = {
                name,
                layout: normalizedLayout(currentLayout.value),
                updated_at: new Date().toISOString()
            };
            const index = layoutProfiles.value.findIndex(item => item.name === name);
            if (index >= 0) layoutProfiles.value.splice(index, 1, profile);
            else layoutProfiles.value.push(profile);
            layoutProfiles.value.sort((a, b) => a.name.localeCompare(b.name, 'ru'));
            selectedProfile.value = name;
            persistLayoutProfiles();
            addToast('Шаблон сохранён', `Разметка «${name}» доступна в этом браузере.`, 'success');
        };

        const applySelectedProfile = async () => {
            const profile = layoutProfiles.value.find(item => item.name === selectedProfile.value);
            if (!profile || !currentFile.value) return;
            const layout = deepCopy(profile.layout);
            if (!currentFile.value.analysis.sheet_names.includes(layout.sheet_name)) {
                layout.sheet_name = currentFile.value.analysis.selected_sheet;
            }
            layouts[currentFile.value.file_id] = layout;
            markFileDirty(currentFile.value.file_id);
            await loadPreview();
            addToast('Шаблон применён', `Разметка «${profile.name}» применена к текущему файлу.`, 'success');
        };

        const deleteSelectedProfile = () => {
            if (!selectedProfile.value) return;
            const name = selectedProfile.value;
            layoutProfiles.value = layoutProfiles.value.filter(item => item.name !== name);
            selectedProfile.value = '';
            persistLayoutProfiles();
            addToast('Шаблон удалён', `Разметка «${name}» удалена.`, 'info');
        };

        const copyLayoutToEnabled = () => {
            if (!currentLayout.value || !currentFile.value) return;
            let copied = 0;
            enabledFiles.value.forEach(file => {
                if (file.file_id === currentFile.value.file_id) return;
                const layout = deepCopy(normalizedLayout(currentLayout.value));
                if (!file.analysis.sheet_names.includes(layout.sheet_name)) {
                    layout.sheet_name = file.analysis.selected_sheet;
                }
                layouts[file.file_id] = layout;
                markFileDirty(file.file_id);
                copied += 1;
            });
            addToast('Разметка скопирована', `Обновлено файлов: ${copied}. Каждый файл необходимо проверить.`, 'info');
        };

        const changeDayNames = event => {
            if (!currentLayout.value) return;
            currentLayout.value.day_names = event.target.value
                .split(',')
                .map(value => value.trim())
                .filter(Boolean);
            markDirty();
        };

        const applySuggestion = async () => {
            if (!currentFile.value?.analysis) return;
            layouts[currentFile.value.file_id] = deepCopy(currentFile.value.analysis.layout);
            delete validations[currentFile.value.file_id];
            await loadPreview();
            addToast('Разметка восстановлена', 'Возвращены автоматически найденные координаты.', 'info');
        };

        const validateFile = async file => {
            if (!file?.analysis || !file.enabled) return null;
            const response = await axios.post(
                `/api/analysis/${sessionId.value}/validate`,
                {
                    file_id: file.file_id,
                    group_name: file.group_name,
                    layout: normalizedLayout(layouts[file.file_id])
                }
            );
            validations[file.file_id] = response.data;
            return response.data;
        };

        const validateCurrent = async () => {
            if (!currentFile.value) return;
            validateBusy.value = true;
            try {
                const validation = await validateFile(currentFile.value);
                const count = validation?.report?.lesson_count || 0;
                const type = validation.status === 'success'
                    ? 'success'
                    : validation.status === 'warning' ? 'warning' : 'error';
                addToast(
                    'Проверка разметки',
                    validation.status === 'error'
                        ? (validation.report.errors || []).join(' ')
                        : `Распознано занятий: ${count}.`,
                    type
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
                for (const file of enabledFiles.value) {
                    await validateFile(file);
                }
                const invalid = enabledFiles.value.filter(file => {
                    const report = validations[file.file_id]?.report;
                    return !report || report.errors?.length || !report.lesson_count;
                });
                addToast(
                    'Проверка файлов',
                    invalid.length
                        ? `Файлов с критическими ошибками: ${invalid.length}.`
                        : 'Все выбранные файлы пригодны для формирования расписания.',
                    invalid.length ? 'warning' : 'success'
                );
            } catch (error) {
                addToast('Ошибка проверки', error.response?.data?.detail || 'Проверка остановлена.', 'error');
            } finally {
                validateBusy.value = false;
            }
        };

        const generate = async () => {
            generateBusy.value = true;
            try {
                await validateAll();
                if (!canGenerate.value) {
                    addToast(
                        'Формирование остановлено',
                        'Исправьте разметку файлов с ошибками либо отключите их в списке слева.',
                        'error'
                    );
                    return;
                }
                const payload = {
                    files: analyzedFiles.value.map(file => ({
                        file_id: file.file_id,
                        group_name: file.group_name,
                        enabled: Boolean(file.enabled && file.analysis),
                        layout: file.analysis ? normalizedLayout(layouts[file.file_id]) : {}
                    }))
                };
                const response = await axios.post(
                    `/api/analysis/${sessionId.value}/generate`,
                    payload
                );
                result.value = response.data;
                if (response.data.filename) {
                    step.value = 3;
                    addToast(
                        'Готово',
                        response.data.message,
                        response.data.status === 'success' ? 'success' : 'warning'
                    );
                } else {
                    addToast('Не сформировано', response.data.message, 'error');
                }
            } catch (error) {
                addToast('Ошибка формирования', error.response?.data?.detail || 'Не удалось сформировать файл.', 'error');
            } finally {
                generateBusy.value = false;
            }
        };

        const fileStatus = file => {
            const validation = validations[file.file_id];
            if (!file.enabled) return 'disabled';
            if (!validation) return file.status;
            return validation.status;
        };

        const cellClass = (row, cell) => {
            const layout = currentLayout.value;
            if (!layout) return {};
            const col = cell.column;
            const classes = {
                'cell-merged': cell.merged,
                'cell-week': row.index === Number(layout.weeks_row) &&
                    col >= Number(layout.first_week_col) &&
                    col <= Number(layout.last_week_col),
                'cell-grid': row.index >= Number(layout.grid_start_row) &&
                    row.index <= Number(layout.grid_end_row || 999999) &&
                    col >= Number(layout.first_week_col) &&
                    col <= Number(layout.last_week_col),
                'cell-legend': layout.legend_start_row &&
                    row.index >= Number(layout.legend_start_row) &&
                    row.index <= Number(layout.legend_end_row || 999999)
            };
            return classes;
        };

        const resetWorkflow = async () => {
            if (sessionId.value) {
                try {
                    await axios.delete(`/api/analysis/${sessionId.value}`);
                } catch (_) {
                    // Session cleanup is best-effort.
                }
            }
            step.value = 1;
            sessionId.value = null;
            analyzedFiles.value = [];
            selectedFileId.value = null;
            preview.value = null;
            result.value = null;
            Object.keys(layouts).forEach(key => delete layouts[key]);
            Object.keys(validations).forEach(key => delete validations[key]);
        };

        onMounted(() => {
            fetchTeachers();
            loadLayoutProfiles();
        });

        return {
            step,
            teachers,
            teacherForm,
            editingTeacher,
            teacherBusy,
            showTeachers,
            analyzedFiles,
            currentFile,
            currentLayout,
            currentValidation,
            selectedFileId,
            preview,
            previewRegion,
            previewBusy,
            uploadBusy,
            validateBusy,
            generateBusy,
            result,
            toasts,
            layoutProfiles,
            profileName,
            selectedProfile,
            enabledFiles,
            checkedFilesCount,
            canGenerate,
            colLetter,
            confidenceLabel,
            confidenceClass,
            fileStatus,
            cellClass,
            handleFileInput,
            handleDrop,
            selectFile,
            loadPreview,
            switchRegion,
            markDirty,
            markFileDirty,
            saveCurrentProfile,
            applySelectedProfile,
            deleteSelectedProfile,
            copyLayoutToEnabled,
            changeDayNames,
            applySuggestion,
            validateCurrent,
            validateAll,
            generate,
            resetWorkflow,
            editTeacher,
            saveTeacher,
            deleteTeacher,
            resetTeacherForm,
            removeToast
        };
    }
}).mount('#app');
