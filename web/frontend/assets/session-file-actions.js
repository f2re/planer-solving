const { ref, computed } = Vue;

function inferredScope(message) {
    const text = String(message || '').toLocaleLowerCase('ru');
    if (text.includes('преподавател') || text.includes('не назначен')) return 'teacher';
    if (text.includes('месяц') || text.includes('дат') || text.includes('семестр') || text.includes('год')) return 'calendar';
    if (text.includes('лист')) return 'sheet';
    if (text.includes('недел') || text.includes('столбц') || text.includes('сетк') || text.includes('размет')) return 'range';
    return 'file';
}

function defaultResolution(message, scope) {
    const text = String(message || '').toLocaleLowerCase('ru');
    if (scope === 'teacher') {
        return {
            decision: 'Занятие сохраняется в разделе «Не назначен».',
            impact: 'Занятие не теряется и может быть назначено преподавателю позже.'
        };
    }
    if (text.includes('занятия не найдены') || text.includes('недели пока не распознаны')) {
        return {
            decision: 'Файл остаётся в диагностическом результате без блокировки остальных книг.',
            impact: 'Из этого файла занятия пока не добавляются; исходник доступен для правки.'
        };
    }
    if (scope === 'calendar') {
        return {
            decision: 'Используется последовательность точных дат, соседних месяцев или период пространства.',
            impact: 'Календарь восстанавливается автоматически и записывается в отчёт.'
        };
    }
    if (scope === 'range' || scope === 'sheet') {
        return {
            decision: 'Используется безопасная нормализованная разметка.',
            impact: 'Пригодные занятия включаются, сомнительную область можно уточнить.'
        };
    }
    return {
        decision: 'Система продолжает обработку пригодных данных.',
        impact: 'Замечание сохраняется в отчёте и не блокирует другие файлы.'
    };
}

function normalizedReportIssues(file, validation) {
    const report = validation?.report || {};
    if (Array.isArray(report.issues) && report.issues.length) {
        return report.issues.map(issue => ({
            ...issue,
            file_id: file.file_id,
            filename: file.filename,
            group_name: file.group_name,
            action: issue.action || issue.actions?.[0] || null
        }));
    }

    const result = [];
    const seen = new Set();
    const actions = Array.isArray(report.actions) ? report.actions.filter(Boolean) : [];
    const add = issue => {
        const key = `${issue.code}:${issue.message}`;
        if (!issue.message || seen.has(key)) return;
        seen.add(key);
        result.push({
            blocking: false,
            resolved: true,
            ...issue,
            file_id: file.file_id,
            filename: file.filename,
            group_name: file.group_name
        });
    };

    for (const raw of report.period?.issues || []) {
        const automatic = raw.resolution === 'auto';
        add({
            code: raw.code || 'calendar_attention',
            scope: 'calendar',
            severity: raw.severity === 'info' ? 'info' : 'attention',
            message: raw.message,
            default_decision: automatic
                ? 'Календарное решение уже принято автоматически по фактическим датам.'
                : 'До уточнения используется безопасная календарная последовательность.',
            impact: 'Формирование не блокируется; решение будет записано в отчёт.',
            resolution: automatic ? 'auto' : 'default_with_override',
            action: raw.action || null,
            actions: raw.action ? [raw.action] : []
        });
    }

    for (const messageValue of report.errors || []) {
        const message = String(messageValue || '').trim();
        add({
            code: 'technical_file_issue',
            scope: 'file',
            severity: 'technical',
            message,
            default_decision: 'Этот файл или фрагмент исключается; остальные исходники продолжают обрабатываться.',
            impact: 'Доступные данные попадут в результат, а отказ сохранится в диагностике.',
            resolution: 'skipped_with_override',
            action: actions.find(action => ['replace_file', 'edit_layout', 'retry'].includes(action.type)) || actions[0] || null,
            actions
        });
    }

    for (const messageValue of report.warnings || []) {
        const message = String(messageValue || '').trim();
        const scope = inferredScope(message);
        const defaults = defaultResolution(message, scope);
        const acceptedTypes = {
            teacher: ['open_teacher_mapping'],
            calendar: ['edit_period', 'calendar_policy'],
            range: ['edit_layout', 'layout_patch'],
            sheet: ['edit_layout', 'layout_patch', 'replace_file'],
            file: []
        }[scope];
        const matchingActions = actions.filter(action => !acceptedTypes.length || acceptedTypes.includes(action.type));
        add({
            code: scope === 'teacher' ? 'unknown_teacher_mapping' : `${scope}_attention`,
            scope,
            severity: 'attention',
            message,
            default_decision: defaults.decision,
            impact: defaults.impact,
            resolution: 'default_with_override',
            action: matchingActions[0] || null,
            actions: matchingActions
        });
    }

    return result;
}

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
    const originalResetWorkflow = schedule.resetWorkflow;
    schedule.resetWorkflow = async (...args) => {
        clearRemovedFileUndo();
        return originalResetWorkflow(...args);
    };

    const operatorIssues = computed(() => schedule.analyzedFiles.value.flatMap(file =>
        normalizedReportIssues(file, schedule.validations[file.file_id])
    ));
    const attentionIssues = computed(() => operatorIssues.value.filter(issue =>
        issue.severity === 'attention' || issue.severity === 'technical'
    ));
    const automaticDecisions = computed(() => operatorIssues.value.filter(issue =>
        issue.severity === 'info' || issue.resolution === 'auto'
    ));

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

    async function openAttentionIssue(issue) {
        if (!issue?.file_id) return;
        schedule.step.value = 2;
        await schedule.selectFile(issue.file_id);
        if (issue.action) {
            await schedule.applyParserAction(issue.action);
        } else {
            addToast(
                'Решение уже применено',
                issue.default_decision || 'Формирование продолжится по безопасному варианту.',
                'info'
            );
        }
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
        operatorIssues,
        attentionIssues,
        automaticDecisions,
        openAttentionIssue,
        appendSessionFiles,
        replaceSessionFile,
        removeSessionFile,
        undoRemoveSessionFile,
        clearRemovedFileUndo
    };
}
