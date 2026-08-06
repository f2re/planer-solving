const { ref, computed, watch } = Vue;

const RULE_PREFIX = '@';
const RULE_FIELDS = [
    ['lecturer', 'lecturer'],
    ['other', 'practice'],
    ['reserve', 'reserve']
];

function copy(value, fallback = {}) {
    try {
        return JSON.parse(JSON.stringify(value));
    } catch (_) {
        return fallback;
    }
}

function emptyRule(subject = '') {
    return { subject, lecturer: '', practice: '', reserve: '' };
}

function subjectKey(value) {
    return String(value || '')
        .trim()
        .toLocaleLowerCase('ru')
        .replaceAll('ё', 'е')
        .replace(/[^0-9a-zа-я]+/gi, '');
}

function overrideKey(role, subject) {
    return `${RULE_PREFIX}${role}|${subject}`;
}

function parseOverrideKey(value) {
    const raw = String(value || '');
    if (!raw.startsWith(RULE_PREFIX) || !raw.includes('|')) return null;
    const separator = raw.indexOf('|');
    const role = raw.slice(1, separator);
    const subject = raw.slice(separator + 1).trim();
    if (!['lecturer', 'other', 'reserve'].includes(role) || !subject) return null;
    return { role, subject };
}

export function createTeacherMappingState(addToast, schedule, activeWorkspaceId) {
    const teacherMappingOpen = ref(false);
    const teacherMappingBusy = ref(false);
    const teacherMappingFileId = ref(null);
    const teacherMappingSubjects = ref([]);
    const teacherMappingOptions = ref([]);
    const teacherMappingDraft = ref({});
    const teacherMappingSearch = ref('');
    const teacherMappingSaveDefaults = ref(false);
    const storedTeacherRules = ref([]);

    let cachedWorkspaceId = '';
    let cachedRules = [];
    let defaultsRequest = null;
    let appliedDefaultsSignature = '';

    const originalResetWorkflow = schedule.resetWorkflow;
    schedule.resetWorkflow = async (...args) => {
        clearTeacherMappingState();
        appliedDefaultsSignature = '';
        return originalResetWorkflow(...args);
    };

    const currentMappingFile = computed(() => schedule.analyzedFiles.value.find(
        file => file.file_id === teacherMappingFileId.value
    ) || null);

    const filteredMappingSubjects = computed(() => {
        const query = teacherMappingSearch.value.trim().toLocaleLowerCase('ru');
        if (!query) return teacherMappingSubjects.value;
        return teacherMappingSubjects.value.filter(item => {
            const rule = teacherMappingDraft.value[item.name] || {};
            return [item.name, rule.lecturer, rule.practice, rule.reserve]
                .some(value => String(value || '').toLocaleLowerCase('ru').includes(query));
        });
    });

    const configuredTeacherRulesCount = computed(() => Object.values(
        sessionRules()
    ).filter(rule => rule.lecturer || rule.practice || rule.reserve).length);

    function ensureOverrides(fileId) {
        if (!schedule.periodOverrides[fileId]) {
            schedule.periodOverrides[fileId] = { week_day_dates: {}, week_months: {} };
        }
        const state = schedule.periodOverrides[fileId];
        if (!state.teacher_overrides || typeof state.teacher_overrides !== 'object') {
            state.teacher_overrides = {};
        }
        return state.teacher_overrides;
    }

    function sessionRules() {
        const result = {};
        for (const file of schedule.analyzedFiles.value) {
            const overrides = schedule.periodOverrides[file.file_id]?.teacher_overrides || {};
            for (const [key, rawTeacher] of Object.entries(overrides)) {
                const teacher = String(rawTeacher || '').trim();
                if (!teacher) continue;
                const parsed = parseOverrideKey(key);
                if (parsed) {
                    const rule = result[parsed.subject] ||= emptyRule(parsed.subject);
                    const field = parsed.role === 'other' ? 'practice' : parsed.role;
                    rule[field] = teacher;
                    continue;
                }

                // 2.17–2.20 stored one hard teacher for the whole subject.
                // Expose it as lecture + practice so the operator sees and can
                // refine the old decision instead of leaving a hidden override.
                const subject = String(key || '').trim();
                if (!subject) continue;
                const rule = result[subject] ||= emptyRule(subject);
                rule.lecturer ||= teacher;
                rule.practice ||= teacher;
            }
        }
        return result;
    }

    function applyRulesToFile(fileId, rules, { replace = false } = {}) {
        const overrides = ensureOverrides(fileId);
        if (replace) {
            const displayedSubjects = new Set(
                rules.map(rule => subjectKey(rule.subject)).filter(Boolean)
            );
            for (const key of Object.keys(overrides)) {
                const parsed = parseOverrideKey(key);
                if (parsed || displayedSubjects.has(subjectKey(key))) delete overrides[key];
            }
        }
        for (const rule of rules) {
            const subject = String(rule.subject || '').trim();
            if (!subject) continue;
            for (const [role, field] of RULE_FIELDS) {
                const teacher = String(rule[field] || '').trim();
                const key = overrideKey(role, subject);
                if (teacher && (replace || !(key in overrides))) overrides[key] = teacher;
            }
        }
    }

    function applyRulesToSession(rules, options = {}) {
        for (const file of schedule.analyzedFiles.value) {
            if (!file.analysis) continue;
            applyRulesToFile(file.file_id, rules, options);
        }
    }

    async function loadWorkspaceRules({ force = false } = {}) {
        const workspaceId = String(activeWorkspaceId.value || '');
        if (!workspaceId) return [];
        if (!force && cachedWorkspaceId === workspaceId) return copy(cachedRules, []);
        if (defaultsRequest && !force) return defaultsRequest;
        defaultsRequest = axios.get(
            `/api/workspaces/${workspaceId}/teacher-assignment-rules`
        ).then(({ data }) => {
            cachedWorkspaceId = workspaceId;
            cachedRules = Array.isArray(data?.items) ? data.items : [];
            storedTeacherRules.value = copy(cachedRules, []);
            return copy(cachedRules, []);
        }).catch(error => {
            console.warn('[planner] assignment defaults unavailable', error);
            return [];
        }).finally(() => {
            defaultsRequest = null;
        });
        return defaultsRequest;
    }

    async function applyStoredRulesToSession() {
        const workspaceId = String(activeWorkspaceId.value || '');
        const sessionId = String(schedule.sessionId.value || '');
        const fileIds = schedule.analyzedFiles.value
            .filter(file => file.analysis)
            .map(file => file.file_id)
            .join(',');
        if (!workspaceId || !sessionId || !fileIds) return;
        const signature = `${workspaceId}:${sessionId}:${fileIds}`;
        if (signature === appliedDefaultsSignature) return;
        const rules = await loadWorkspaceRules();
        applyRulesToSession(rules, { replace: false });
        appliedDefaultsSignature = signature;
    }

    function collectSubjects(defaults = []) {
        const subjects = new Map();
        const include = (name, candidates = {}) => {
            const normalized = String(name || '').trim();
            if (!normalized) return;
            const current = subjects.get(normalized) || {
                name: normalized,
                candidates: { lecturer: [], practice: [], reserve: [] }
            };
            for (const field of ['lecturer', 'practice', 'reserve']) {
                const values = Array.isArray(candidates[field]) ? candidates[field] : [];
                current.candidates[field] = Array.from(new Set([
                    ...current.candidates[field],
                    ...values.map(value => String(value || '').trim()).filter(Boolean)
                ]));
            }
            subjects.set(normalized, current);
        };

        for (const file of schedule.analyzedFiles.value) {
            const report = schedule.validations[file.file_id]?.report || {};
            for (const subject of report.subjects || []) {
                include(subject, report.teacher_candidates?.[subject] || {});
            }
            for (const subject of report.unknown_subjects || []) include(subject);
            for (const sample of report.samples || []) include(sample?.subject);
            for (const [subject, candidates] of Object.entries(report.teacher_candidates || {})) {
                include(subject, candidates);
            }
        }
        for (const rule of defaults) include(rule.subject);
        for (const rule of Object.values(sessionRules())) include(rule.subject);
        return [...subjects.values()].sort((left, right) =>
            left.name.localeCompare(right.name, 'ru')
        );
    }

    function candidateHint(item) {
        const values = Array.from(new Set([
            ...(item?.candidates?.lecturer || []),
            ...(item?.candidates?.practice || []),
            ...(item?.candidates?.reserve || [])
        ])).filter(Boolean);
        if (!values.length) return 'Автоматика выберет преподавателя из данных файла';
        const shown = values.slice(0, 2).join(', ');
        return values.length > 2 ? `Авто: ${shown} и ещё ${values.length - 2}` : `Авто: ${shown}`;
    }

    function ruleSummary(subject) {
        const rule = teacherMappingDraft.value[subject] || {};
        const labels = [];
        if (rule.lecturer) labels.push(`лекции — ${rule.lecturer}`);
        if (rule.practice) labels.push(`практика — ${rule.practice}`);
        if (rule.reserve) labels.push(`резерв — ${rule.reserve}`);
        return labels.length ? labels.join(' · ') : 'Автоматическое распределение';
    }

    function clearTeacherRule(subject) {
        teacherMappingDraft.value[subject] = emptyRule(subject);
    }

    function resetAllTeacherRules() {
        teacherMappingDraft.value = Object.fromEntries(
            teacherMappingSubjects.value.map(item => [item.name, emptyRule(item.name)])
        );
    }

    async function openTeacherMapping(issue = null) {
        teacherMappingBusy.value = true;
        teacherMappingFileId.value = issue?.file_id || schedule.selectedFileId.value;
        try {
            if (!Object.keys(schedule.validations).length && schedule.enabledFiles.value.length) {
                await schedule.validateAll();
            }
            const workspaceId = String(activeWorkspaceId.value || '');
            const [teachersResponse, defaults] = await Promise.all([
                axios.get(`/api/workspaces/${workspaceId}/teachers`),
                loadWorkspaceRules()
            ]);
            teacherMappingOptions.value = (teachersResponse.data || []).slice().sort((left, right) =>
                String(left.full_name || left.short_name || '').localeCompare(
                    String(right.full_name || right.short_name || ''),
                    'ru'
                )
            );
            const subjects = collectSubjects(defaults);
            if (!subjects.length) {
                addToast(
                    'Преподаватели',
                    'Сначала добавьте и проверьте хотя бы один файл расписания.',
                    'info'
                );
                return;
            }

            const saved = Object.fromEntries(
                defaults.map(rule => [rule.subject, { ...emptyRule(rule.subject), ...rule }])
            );
            const current = sessionRules();
            teacherMappingSubjects.value = subjects;
            teacherMappingDraft.value = Object.fromEntries(subjects.map(item => [
                item.name,
                {
                    ...emptyRule(item.name),
                    ...(saved[item.name] || {}),
                    ...(current[item.name] || {})
                }
            ]));
            teacherMappingSearch.value = '';
            teacherMappingSaveDefaults.value = false;
            teacherMappingOpen.value = true;
        } catch (error) {
            addToast(
                'Преподаватели',
                error.response?.data?.detail || 'Не удалось открыть настройки преподавателей.',
                'warning'
            );
        } finally {
            teacherMappingBusy.value = false;
        }
    }

    function closeTeacherMapping() {
        teacherMappingOpen.value = false;
        teacherMappingSearch.value = '';
    }

    async function saveTeacherMapping() {
        const rules = teacherMappingSubjects.value.map(item => ({
            ...emptyRule(item.name),
            ...(teacherMappingDraft.value[item.name] || {})
        }));
        const activeRules = rules.filter(rule =>
            rule.lecturer || rule.practice || rule.reserve
        );

        teacherMappingBusy.value = true;
        try {
            // Pass every displayed subject so replace=true also removes a
            // cleared legacy or role rule. Empty subjects are not re-added.
            applyRulesToSession(rules, { replace: true });
            schedule.invalidateAll();
            if (teacherMappingSaveDefaults.value) {
                const workspaceId = String(activeWorkspaceId.value || '');
                const { data } = await axios.put(
                    `/api/workspaces/${workspaceId}/teacher-assignment-rules`,
                    { rules: activeRules }
                );
                cachedWorkspaceId = workspaceId;
                cachedRules = Array.isArray(data?.items) ? data.items : [];
                storedTeacherRules.value = copy(cachedRules, []);
            }
            closeTeacherMapping();
            await schedule.validateAll();
            window.__plannerSessionDraft?.flush?.();
            addToast(
                'Назначения применены',
                activeRules.length
                    ? `Настроено дисциплин: ${activeRules.length}.`
                    : 'Используется автоматическое распределение.',
                'success'
            );
        } catch (error) {
            addToast(
                'Преподаватели',
                error.response?.data?.detail || 'Настройки сохранены в сеансе, но пересчёт не завершён.',
                'warning'
            );
        } finally {
            teacherMappingBusy.value = false;
        }
    }

    function clearTeacherMappingState() {
        teacherMappingOpen.value = false;
        teacherMappingFileId.value = null;
        teacherMappingSubjects.value = [];
        teacherMappingOptions.value = [];
        teacherMappingDraft.value = {};
        teacherMappingSearch.value = '';
        teacherMappingSaveDefaults.value = false;
    }

    watch(
        () => JSON.stringify({
            workspace: activeWorkspaceId.value,
            session: schedule.sessionId.value,
            files: schedule.analyzedFiles.value.map(file => [file.file_id, Boolean(file.analysis)])
        }),
        () => applyStoredRulesToSession(),
        { flush: 'post' }
    );

    return {
        teacherMappingOpen,
        teacherMappingBusy,
        teacherMappingFileId,
        teacherMappingSubjects,
        teacherMappingOptions,
        teacherMappingDraft,
        teacherMappingSearch,
        teacherMappingSaveDefaults,
        storedTeacherRules,
        currentMappingFile,
        filteredMappingSubjects,
        configuredTeacherRulesCount,
        candidateHint,
        ruleSummary,
        openTeacherMapping,
        closeTeacherMapping,
        saveTeacherMapping,
        clearTeacherRule,
        resetAllTeacherRules,
        clearTeacherMappingState
    };
}
