const { computed } = Vue;

export function createScheduleDiagnosticGenerationState(addToast, schedule, scheduleDraft) {
    const recoverableFiles = computed(() =>
        schedule.analyzedFiles.value.filter(file => !file.analysis || file.enabled)
    );
    const canGenerate = computed(() => recoverableFiles.value.length > 0);

    async function generate() {
        if (!canGenerate.value || !schedule.sessionId.value) {
            addToast(
                'Нет файлов для результата',
                'Включите хотя бы один разобранный файл или оставьте неразобранный файл для диагностического отчёта.',
                'warning'
            );
            return;
        }

        schedule.generateBusy.value = true;
        try {
            await schedule.validateAll();
            const payload = {
                workspace_id: schedule.activeWorkspaceId?.value,
                allow_partial: true,
                calendar_overrides: {
                    policy: schedule.calendarOverrides.policy,
                    week_day_dates: { ...(schedule.calendarOverrides.week_day_dates || {}) },
                    week_months: { ...(schedule.calendarOverrides.week_months || {}) }
                },
                files: schedule.analyzedFiles.value.map(file => ({
                    file_id: file.file_id,
                    group_name: file.group_name,
                    // An unreadable workbook is deliberately included so the
                    // backend can record it and produce a recovery workbook.
                    // A readable file still respects the operator checkbox.
                    enabled: file.analysis ? Boolean(file.enabled) : true,
                    layout: file.analysis
                        ? schedule.normalizedLayout(schedule.layouts[file.file_id])
                        : {},
                    period_overrides: file.analysis
                        ? JSON.parse(JSON.stringify(schedule.periodOverrides[file.file_id] || {}))
                        : {}
                }))
            };
            const { data } = await axios.post(
                `/api/analysis/${schedule.sessionId.value}/generate`,
                payload
            );
            schedule.result.value = data;
            if (data.filename) {
                schedule.step.value = 3;
                addToast(
                    data.filename.startsWith('schedule_recovery_')
                        ? 'Диагностический результат готов'
                        : 'Результат готов',
                    data.message,
                    data.status === 'success' ? 'success' : 'warning'
                );
                await scheduleDraft.flushDraft({ quiet: false });
            } else {
                addToast('Результат не создан', data.message, 'warning');
            }
        } catch (error) {
            addToast(
                'Формирование не завершено',
                error.response?.data?.detail
                    || 'Произошла техническая ошибка сервера. Исходники и черновик сохранены.',
                'error'
            );
        } finally {
            schedule.generateBusy.value = false;
        }
    }

    return {
        recoverableFiles,
        canGenerate,
        generate
    };
}
