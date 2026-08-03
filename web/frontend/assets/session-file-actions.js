const { ref } = Vue;

/**
 * Управление отдельными исходниками активного сеанса.
 *
 * Важное правило: добавление или замена одного файла не должно повторно
 * применять шаблоны к уже исправленным книгам. Поэтому автоподбор запускается
 * только для изменённого файла.
 */
export function createSessionFileActions(addToast, schedule, activeWorkspaceId) {
    const fileMutationBusy = ref(false);
    const mutatingFileId = ref(null);
    const lastRemovedFile = ref(null);

    const copy = value => value == null ? value : JSON.parse(JSON.stringify(value));

    function normalizedClientFile(item, previous = null) {
        return {
            ...item,
            enabled: previous?.enabled ?? Boolean(item.analysis),
            matching: false,
            template_match: null,
            template_candidates: []
        };
    }

    function resetDerivedState(fileId) {
        delete schedule.validations[fileId];
        delete schedule.periodOverrides[fileId];
        schedule.periodOverrides[fileId] = { week_day_dates: {}, week_months: {} };
    }

    async function matchOneFile(file, { applyLayout = true } = {}) {
        if (!file?.analysis || !schedule.sessionId.value || !activeWorkspaceId.value) return;
        file.matching = true;
        try {
            const { data } = await axios.post(
                `/api/analysis/${schedule.sessionId.value}/files/${file.file_id}/match-templates`,
                { workspace_id: activeWorkspaceId.value }
            );
            file.template_candidates = data.candidates || [];
            file.template_match = data.selected || null;
            if (applyLayout && data.selected?.usable && data.selected?.layout) {
                schedule.layouts[file.file_id] = copy(data.selected.layout);
            }
        } catch (error) {
            file.template_match = null;
            file.template_candidates = [];
            addToast(
                'Автоподбор разметки',
                error.response?.data?.detail || `Шаблоны для «${file.filename}» не проверены. Автоматическая разметка остаётся доступной.`,
                'warning'
            );
        } finally {
            file.matching = false;
        }
    }

    async function appendSessionFiles(event) {
        const input = event?.target;
        const files = Array.from(input?.files || []);
        if (!files.length || !schedule.sessionId.value) return;
        fileMutationBusy.value = true;
        mutatingFileId.value = 'append';
        const form = new FormData();
        files.forEach(file => form.append('files', file));
        try {
            const { data } = await axios.post(
                `/api/analysis/${schedule.sessionId.value}/files`,
                form,
                { headers: { 'Content-Type': 'multipart/form-data' } }
            );
            const added = (data.files || []).map(item => normalizedClientFile(item));
            for (const file of added) {
                schedule.analyzedFiles.value.push(file);
                if (file.analysis) {
                    schedule.layouts[file.file_id] = copy(file.analysis.layout);
                    resetDerivedState(file.file_id);
                    await matchOneFile(file, { applyLayout: true });
                }
            }
            const firstUsable = added.find(file => file.analysis);
            if (firstUsable) {
                schedule.selectedFileId.value = firstUsable.file_id;
                schedule.previewRegion.value = 'schedule';
                await schedule.loadPreview();
            }
            addToast(
                'Файлы добавлены',
                `Добавлено: ${added.length}. Ранее исправленные файлы не изменены.`,
                added.some(file => !file.analysis) ? 'warning' : 'success'
            );
        } catch (error) {
            addToast(
                'Добавление файлов',
                error.response?.data?.detail || 'Не удалось добавить файлы в текущий сеанс. Остальные данные сохранены.',
                'warning'
            );
        } finally {
            fileMutationBusy.value = false;
            mutatingFileId.value = null;
            if (input) input.value = '';
        }
    }

    async function replaceSessionFile(fileId, event) {
        const input = event?.target;
        const upload = input?.files?.[0];
        const index = schedule.analyzedFiles.value.findIndex(file => file.file_id === fileId);
        if (!upload || index < 0 || !schedule.sessionId.value) return;

        const previous = schedule.analyzedFiles.value[index];
        const previousGroup = previous.group_name;
        const previousLayout = copy(schedule.layouts[fileId]);
        fileMutationBusy.value = true;
        mutatingFileId.value = fileId;
        const form = new FormData();
        form.append('file', upload);
        try {
            const { data } = await axios.put(
                `/api/analysis/${schedule.sessionId.value}/files/${fileId}`,
                form,
                { headers: { 'Content-Type': 'multipart/form-data' } }
            );
            const replacement = normalizedClientFile(data, previous);
            replacement.group_name = previousGroup;
            schedule.analyzedFiles.value.splice(index, 1, replacement);
            resetDerivedState(fileId);

            const previousSheet = previousLayout?.sheet_name;
            const canKeepLayout = Boolean(
                replacement.analysis
                && previousLayout
                && replacement.analysis.sheet_names?.includes(previousSheet)
            );
            if (canKeepLayout) {
                schedule.layouts[fileId] = previousLayout;
                await matchOneFile(replacement, { applyLayout: false });
            } else if (replacement.analysis) {
                schedule.layouts[fileId] = copy(replacement.analysis.layout);
                await matchOneFile(replacement, { applyLayout: true });
            } else {
                delete schedule.layouts[fileId];
            }

            schedule.selectedFileId.value = fileId;
            schedule.previewRegion.value = 'schedule';
            if (replacement.analysis) await schedule.loadPreview();
            else schedule.preview.value = null;
            addToast(
                'Файл заменён',
                canKeepLayout
                    ? 'Название группы и текущая разметка сохранены; пересчитайте файл.'
                    : 'Название группы сохранено, для новой структуры выбрана безопасная разметка.',
                replacement.analysis ? 'success' : 'warning'
            );
        } catch (error) {
            addToast(
                'Замена файла',
                error.response?.data?.detail || 'Файл не заменён. Прежний исходник и все правки сохранены.',
                'warning'
            );
        } finally {
            fileMutationBusy.value = false;
            mutatingFileId.value = null;
            if (input) input.value = '';
        }
    }

    async function removeSessionFile(file) {
        if (!file?.file_id || !schedule.sessionId.value) return;
        const index = schedule.analyzedFiles.value.findIndex(item => item.file_id === file.file_id);
        if (index < 0) return;
        if (!window.confirm(`Убрать «${file.filename}» из текущего сеанса? Это действие можно отменить.`)) return;

        fileMutationBusy.value = true;
        mutatingFileId.value = file.file_id;
        const snapshot = {
            file: copy(file),
            index,
            layout: copy(schedule.layouts[file.file_id]),
            validation: copy(schedule.validations[file.file_id]),
            periodOverrides: copy(schedule.periodOverrides[file.file_id])
        };
        try {
            const { data } = await axios.delete(
                `/api/analysis/${schedule.sessionId.value}/files/${file.file_id}`
            );
            schedule.analyzedFiles.value.splice(index, 1);
            delete schedule.layouts[file.file_id];
            delete schedule.validations[file.file_id];
            delete schedule.periodOverrides[file.file_id];
            lastRemovedFile.value = snapshot;

            if (schedule.selectedFileId.value === file.file_id) {
                const next = schedule.analyzedFiles.value.find(item => item.file_id === data.next_file_id)
                    || schedule.analyzedFiles.value.find(item => item.analysis)
                    || null;
                schedule.selectedFileId.value = next?.file_id || null;
                if (next?.analysis) await schedule.loadPreview();
                else schedule.preview.value = null;
            }
            addToast('Файл убран', 'Остальные файлы и результат сеанса не изменены. Действие можно отменить.', 'info');
        } catch (error) {
            addToast(
                'Удаление файла',
                error.response?.data?.detail || 'Файл остался в сеансе.',
                'warning'
            );
        } finally {
            fileMutationBusy.value = false;
            mutatingFileId.value = null;
        }
    }

    async function undoRemoveSessionFile() {
        const snapshot = lastRemovedFile.value;
        if (!snapshot?.file?.file_id || !schedule.sessionId.value) return;
        fileMutationBusy.value = true;
        mutatingFileId.value = snapshot.file.file_id;
        try {
            const { data } = await axios.post(
                `/api/analysis/${schedule.sessionId.value}/files/${snapshot.file.file_id}/restore`
            );
            const restored = normalizedClientFile({ ...data, group_name: snapshot.file.group_name }, snapshot.file);
            const index = Math.min(snapshot.index, schedule.analyzedFiles.value.length);
            schedule.analyzedFiles.value.splice(index, 0, restored);
            if (snapshot.layout) schedule.layouts[restored.file_id] = snapshot.layout;
            else if (restored.analysis) schedule.layouts[restored.file_id] = copy(restored.analysis.layout);
            if (snapshot.validation) schedule.validations[restored.file_id] = snapshot.validation;
            schedule.periodOverrides[restored.file_id] = snapshot.periodOverrides || {
                week_day_dates: {},
                week_months: {}
            };
            schedule.selectedFileId.value = restored.file_id;
            if (restored.analysis) await schedule.loadPreview();
            lastRemovedFile.value = null;
            addToast('Файл восстановлен', 'Разметка, группа и результаты проверки возвращены.', 'success');
        } catch (error) {
            addToast(
                'Восстановление файла',
                error.response?.data?.detail || 'Не удалось отменить удаление.',
                'warning'
            );
        } finally {
            fileMutationBusy.value = false;
            mutatingFileId.value = null;
        }
    }

    function clearRemovedFileUndo() {
        lastRemovedFile.value = null;
    }

    return {
        fileMutationBusy,
        mutatingFileId,
        lastRemovedFile,
        appendSessionFiles,
        replaceSessionFile,
        removeSessionFile,
        undoRemoveSessionFile,
        clearRemovedFileUndo
    };
}
