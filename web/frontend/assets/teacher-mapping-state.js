const { ref, computed } = Vue;

export function createTeacherMappingState(addToast, schedule, activeWorkspaceId) {
    const teacherMappingOpen = ref(false);
    const teacherMappingBusy = ref(false);
    const teacherMappingFileId = ref(null);
    const teacherMappingSubjects = ref([]);
    const teacherMappingOptions = ref([]);
    const teacherMappingDraft = ref({});
    const teacherMappingSearch = ref('');

    const currentMappingFile = computed(() => schedule.analyzedFiles.value.find(
        file => file.file_id === teacherMappingFileId.value
    ) || null);

    const filteredMappingSubjects = computed(() => {
        const query = teacherMappingSearch.value.trim().toLocaleLowerCase('ru');
        if (!query) return teacherMappingSubjects.value;
        return teacherMappingSubjects.value.filter(subject =>
            subject.toLocaleLowerCase('ru').includes(query)
            || String(teacherMappingDraft.value[subject] || '').toLocaleLowerCase('ru').includes(query)
        );
    });

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

    async function openTeacherMapping(issue) {
        const fileId = issue?.file_id || schedule.selectedFileId.value;
        const file = schedule.analyzedFiles.value.find(item => item.file_id === fileId);
        if (!file) return;
        const report = schedule.validations[fileId]?.report || {};
        const subjects = Array.from(new Set(
            (report.unknown_subjects || []).map(value => String(value || '').trim()).filter(Boolean)
        )).sort((left, right) => left.localeCompare(right, 'ru'));
        if (!subjects.length) {
            addToast(
                'Назначение преподавателей',
                'Сначала пересчитайте этот файл: система соберёт список нераспознанных дисциплин.',
                'info'
            );
            schedule.selectedFileId.value = fileId;
            await schedule.validateCurrent();
            return;
        }

        teacherMappingBusy.value = true;
        teacherMappingFileId.value = fileId;
        try {
            const { data } = await axios.get(
                `/api/workspaces/${activeWorkspaceId.value}/teachers`
            );
            teacherMappingOptions.value = (data || []).slice().sort((left, right) =>
                String(left.full_name || left.short_name || '').localeCompare(
                    String(right.full_name || right.short_name || ''),
                    'ru'
                )
            );
            const existing = ensureOverrides(fileId);
            teacherMappingSubjects.value = subjects;
            teacherMappingDraft.value = Object.fromEntries(
                subjects.map(subject => [subject, existing[subject] || ''])
            );
            teacherMappingSearch.value = '';
            teacherMappingOpen.value = true;
        } catch (error) {
            addToast(
                'Назначение преподавателей',
                error.response?.data?.detail || 'Не удалось загрузить справочник преподавателей.',
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
        const fileId = teacherMappingFileId.value;
        if (!fileId) return;
        const overrides = ensureOverrides(fileId);
        for (const subject of teacherMappingSubjects.value) {
            const teacher = String(teacherMappingDraft.value[subject] || '').trim();
            if (teacher) overrides[subject] = teacher;
            else delete overrides[subject];
        }

        teacherMappingBusy.value = true;
        try {
            schedule.selectedFileId.value = fileId;
            delete schedule.validations[fileId];
            closeTeacherMapping();
            await schedule.validateCurrent();
            const assigned = Object.values(overrides).filter(Boolean).length;
            addToast(
                'Назначения применены',
                assigned
                    ? `Сохранено назначений: ${assigned}. Результат файла пересчитан.`
                    : 'Оставлено безопасное значение «Не назначен». Результат файла пересчитан.',
                'success'
            );
        } catch (error) {
            addToast(
                'Назначение преподавателей',
                error.response?.data?.detail || 'Назначения сохранены в сеансе, но файл не удалось пересчитать.',
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
    }

    return {
        teacherMappingOpen,
        teacherMappingBusy,
        teacherMappingFileId,
        teacherMappingSubjects,
        teacherMappingOptions,
        teacherMappingDraft,
        teacherMappingSearch,
        currentMappingFile,
        filteredMappingSubjects,
        openTeacherMapping,
        closeTeacherMapping,
        saveTeacherMapping,
        clearTeacherMappingState
    };
}
