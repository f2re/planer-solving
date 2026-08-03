const { ref, computed } = Vue;

const STATUS_LABELS = {
    success: 'Готово',
    warning: 'Готово с замечаниями',
    partial: 'Частичный результат',
    running: 'Выполняется',
    pending: 'Ожидает запуска',
    failed: 'Не завершено',
    error: 'Не завершено',
    skipped: 'Пропущено',
    cancelled: 'Отменено'
};

const SCOPE_LABELS = {
    file: 'Файл',
    sheet: 'Лист',
    range: 'Разметка',
    calendar: 'Календарь',
    teacher: 'Преподаватель',
    export: 'Экспорт'
};

export function createHistoryUxState() {
    const historyDecisionOpen = ref(false);
    const selectedHistoryFile = ref(null);

    const processingStatusLabel = status => STATUS_LABELS[String(status || '').toLowerCase()]
        || String(status || 'Неизвестно');

    const historyIssueScopeLabel = scope => SCOPE_LABELS[String(scope || '').toLowerCase()]
        || 'Файл';

    const historyResolutionLabel = value => ({
        auto: 'Решено автоматически',
        default_with_override: 'Применено безопасное решение',
        skipped_with_override: 'Пропущено без остановки остальных данных',
        operator: 'Изменено оператором'
    }[String(value || '')] || 'Решение сохранено');

    function fallbackIssues(file) {
        const report = file?.report || {};
        const result = [];
        for (const issue of report.period?.issues || []) {
            if (!issue?.message) continue;
            result.push({
                code: issue.code || 'calendar',
                scope: 'calendar',
                severity: issue.severity === 'info' ? 'info' : 'attention',
                message: issue.message,
                default_decision: issue.resolution === 'auto'
                    ? 'Календарное решение принято автоматически.'
                    : 'Использована безопасная последовательность дат.',
                impact: 'Формирование не блокировалось; решение сохранено в отчёте.',
                resolution: issue.resolution || 'default_with_override'
            });
        }
        for (const message of report.errors || []) {
            result.push({
                code: 'legacy_error',
                scope: 'file',
                severity: 'technical',
                message,
                default_decision: 'Этот файл или фрагмент был исключён, остальные данные продолжили обрабатываться.',
                impact: 'Доступные занятия других файлов сохранены.',
                resolution: 'skipped_with_override'
            });
        }
        for (const message of report.warnings || []) {
            result.push({
                code: 'legacy_warning',
                scope: 'file',
                severity: 'attention',
                message,
                default_decision: 'Система использовала безопасный вариант и продолжила формирование.',
                impact: 'Замечание сохранено для последующего уточнения.',
                resolution: 'default_with_override'
            });
        }
        return result;
    }

    function historyFileIssues(file) {
        const structured = file?.report?.issues;
        if (Array.isArray(structured) && structured.length) {
            return structured.filter(issue => issue && issue.message);
        }
        return fallbackIssues(file);
    }

    const selectedHistoryIssues = computed(() => historyFileIssues(selectedHistoryFile.value));

    function openHistoryFileDecisions(file) {
        selectedHistoryFile.value = file || null;
        historyDecisionOpen.value = Boolean(file);
    }

    function closeHistoryFileDecisions() {
        historyDecisionOpen.value = false;
        selectedHistoryFile.value = null;
    }

    return {
        historyDecisionOpen,
        selectedHistoryFile,
        selectedHistoryIssues,
        processingStatusLabel,
        historyIssueScopeLabel,
        historyResolutionLabel,
        historyFileIssues,
        openHistoryFileDecisions,
        closeHistoryFileDecisions
    };
}
