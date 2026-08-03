const { computed } = Vue;

export function createScheduleResultCoverageState(schedule) {
    const resultExcludedFiles = computed(() => {
        const details = schedule.result.value?.details || [];
        const includedIds = new Set(
            details.map(item => String(item.file_id || '')).filter(Boolean)
        );
        return schedule.analyzedFiles.value
            .filter(file =>
                !includedIds.has(String(file.file_id))
                && (!file.analysis || !file.enabled)
            )
            .map(file => ({
                file_id: file.file_id,
                filename: file.filename,
                status: 'warning',
                used: false,
                warning_count: 1,
                action_count: 1,
                message: file.analysis
                    ? 'Файл был отключён оператором и не включён в текущий результат.'
                    : (file.message || 'Файл не разобран и не включён в текущий результат.')
            }));
    });

    return { resultExcludedFiles };
}
