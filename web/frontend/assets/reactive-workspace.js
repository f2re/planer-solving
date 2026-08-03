const { ref, computed, onBeforeUnmount } = Vue;

export function createReactiveWorkspaceState(addToast, workspace, schedule) {
    const syncBusy = ref(false);
    const syncRevision = ref(0);
    const lastSyncedAt = ref(null);
    const syncError = ref('');
    let timer = null;
    let lastSignature = '';

    const jsonSignature = value => JSON.stringify(value || []);
    const syncLabel = computed(() => {
        if (syncBusy.value) return 'Синхронизация…';
        if (syncError.value) return 'Нет связи';
        if (!lastSyncedAt.value) return 'Не синхронизировано';
        return `Обновлено ${lastSyncedAt.value.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}`;
    });

    async function refreshSpaces(preferred = workspace.activeWorkspaceId.value, options = {}) {
        const { silent = true } = options;
        try {
            const { data } = await axios.get('/api/workspaces', { params: { _: Date.now() } });
            const target = preferred || workspace.activeWorkspaceId.value;
            workspace.workspaces.value = Array.isArray(data) ? data : [];
            const exists = workspace.workspaces.value.some(item => item.id === target);
            workspace.activeWorkspaceId.value = exists
                ? target
                : (workspace.workspaces.value.find(item => item.is_default)?.id || workspace.workspaces.value[0]?.id || '');
            if (workspace.activeWorkspaceId.value) {
                localStorage.setItem('planner-workspace-id', workspace.activeWorkspaceId.value);
            }
            document.documentElement.style.setProperty(
                '--primary',
                workspace.activeWorkspace.value?.color || '#315EFB'
            );
            syncError.value = '';
            return workspace.workspaces.value;
        } catch (error) {
            syncError.value = error.response?.data?.detail || 'Не удалось обновить пространства.';
            if (!silent) addToast('Синхронизация', syncError.value, 'error');
            throw error;
        }
    }

    async function refreshData(options = {}) {
        const { silent = true } = options;
        const workspaceId = workspace.activeWorkspaceId.value;
        if (!workspaceId) return { teachers: [], templates: [], changed: false };
        try {
            const selected = workspace.selectedProfile.value;
            const [teachersResponse, templatesResponse] = await Promise.all([
                axios.get(`/api/workspaces/${workspaceId}/teachers`, { params: { _: Date.now() } }),
                axios.get(`/api/workspaces/${workspaceId}/templates`, { params: { _: Date.now() } })
            ]);
            const teachers = Array.isArray(teachersResponse.data) ? teachersResponse.data : [];
            const templates = Array.isArray(templatesResponse.data) ? templatesResponse.data : [];
            const signature = jsonSignature([teachers, templates]);
            const changed = signature !== lastSignature;
            if (changed) {
                workspace.teachers.value = teachers;
                workspace.layoutProfiles.value = templates;
                lastSignature = signature;
                syncRevision.value += 1;
                schedule.invalidateAll();
            }
            if (selected) {
                const stillExists = templates.some(item => item.id === selected || item.name === selected);
                workspace.selectedProfile.value = stillExists ? selected : '';
            }
            lastSyncedAt.value = new Date();
            syncError.value = '';
            return { teachers, templates, changed };
        } catch (error) {
            syncError.value = error.response?.data?.detail || 'Не удалось обновить справочники.';
            if (!silent) addToast('Синхронизация', syncError.value, 'error');
            throw error;
        }
    }

    async function refreshWorkspace(preferred = workspace.activeWorkspaceId.value, options = {}) {
        if (syncBusy.value) return null;
        syncBusy.value = true;
        try {
            await refreshSpaces(preferred, options);
            const result = await refreshData(options);
            lastSyncedAt.value = new Date();
            return result;
        } finally {
            syncBusy.value = false;
        }
    }

    async function refreshAfterMutation(options = {}) {
        const result = await refreshWorkspace(workspace.activeWorkspaceId.value, { silent: true });
        if (!options.silent) {
            addToast(
                'Данные обновлены',
                `Преподавателей: ${workspace.teachers.value.length}; шаблонов: ${workspace.layoutProfiles.value.length}.`,
                'success'
            );
        }
        return result;
    }

    function startReactiveSync(intervalMs = 8000) {
        stopReactiveSync();
        const tick = () => {
            if (document.visibilityState !== 'visible' || syncBusy.value || !workspace.activeWorkspaceId.value) return;
            refreshWorkspace(workspace.activeWorkspaceId.value, { silent: true }).catch(() => {});
        };
        timer = window.setInterval(tick, intervalMs);
        window.addEventListener('focus', tick);
        document.addEventListener('visibilitychange', tick);
        startReactiveSync._tick = tick;
    }

    function stopReactiveSync() {
        if (timer) window.clearInterval(timer);
        timer = null;
        if (startReactiveSync._tick) {
            window.removeEventListener('focus', startReactiveSync._tick);
            document.removeEventListener('visibilitychange', startReactiveSync._tick);
            startReactiveSync._tick = null;
        }
    }

    onBeforeUnmount(stopReactiveSync);

    return {
        syncBusy,
        syncRevision,
        lastSyncedAt,
        syncError,
        syncLabel,
        refreshSpaces,
        refreshData,
        refreshWorkspace,
        refreshAfterMutation,
        startReactiveSync,
        stopReactiveSync
    };
}
