const { ref, reactive, computed, watch } = Vue;

export function createOperationsState(
    addToast,
    workspace,
    schedule,
    interaction,
    initializeWorkspace
) {
    const authReady = ref(false);
    const authBusy = ref(false);
    const setupRequired = ref(false);
    const currentUser = ref(null);
    const csrfToken = ref('');
    const authForm = reactive({
        username: '',
        display_name: '',
        password: '',
        password_confirm: ''
    });

    const canAdmin = computed(() => currentUser.value?.role === 'admin');
    const canOperate = computed(() => ['admin', 'operator'].includes(currentUser.value?.role));
    const canView = computed(() => Boolean(currentUser.value));
    const userInitials = computed(() => {
        const text = currentUser.value?.display_name || currentUser.value?.username || '?';
        return text.split(/\s+/).filter(Boolean).slice(0, 2).map(item => item[0]).join('').toUpperCase();
    });

    axios.defaults.withCredentials = true;
    axios.interceptors.request.use(config => {
        if (csrfToken.value && !['get', 'head', 'options'].includes(String(config.method || 'get').toLowerCase())) {
            config.headers = config.headers || {};
            config.headers['X-CSRF-Token'] = csrfToken.value;
        }
        return config;
    });

    const applyAuth = payload => {
        setupRequired.value = Boolean(payload.setup_required);
        currentUser.value = payload.user || null;
        csrfToken.value = payload.csrf_token || '';
        authReady.value = true;
    };

    const refreshAuth = async () => {
        try {
            const { data } = await axios.get('/api/auth/status');
            applyAuth(data);
            return Boolean(data.authenticated);
        } catch (error) {
            authReady.value = true;
            addToast('Авторизация', error.response?.data?.detail || 'Не удалось проверить сеанс.', 'error');
            return false;
        }
    };

    const bootstrap = async () => {
        if (authForm.password !== authForm.password_confirm) {
            addToast('Пароль', 'Введённые пароли не совпадают.', 'warning');
            return;
        }
        authBusy.value = true;
        try {
            const { data } = await axios.post('/api/auth/bootstrap', {
                username: authForm.username,
                display_name: authForm.display_name,
                password: authForm.password
            });
            applyAuth(data);
            Object.assign(authForm, { password: '', password_confirm: '' });
            await initializeWorkspace();
            addToast('Система настроена', 'Создан первоначальный администратор.', 'success');
        } catch (error) {
            addToast('Настройка', error.response?.data?.detail || 'Не удалось создать администратора.', 'error');
        } finally {
            authBusy.value = false;
        }
    };

    const login = async () => {
        authBusy.value = true;
        try {
            const { data } = await axios.post('/api/auth/login', {
                username: authForm.username,
                password: authForm.password
            });
            applyAuth(data);
            authForm.password = '';
            await initializeWorkspace();
            addToast('Вход выполнен', `Здравствуйте, ${data.user.display_name}.`, 'success');
        } catch (error) {
            addToast('Вход', error.response?.data?.detail || 'Не удалось войти.', 'error');
        } finally {
            authBusy.value = false;
        }
    };

    const logout = async () => {
        try {
            await axios.post('/api/auth/logout');
        } catch (_) {
            // Cookie is cleared by a page reset even when the server session expired.
        }
        currentUser.value = null;
        csrfToken.value = '';
        setupRequired.value = false;
        workspace.managerOpen.value = false;
        window.location.reload();
    };

    // --------------------------------------------------------------- imports
    const importKind = ref('teachers');
    const importStep = ref(1);
    const importBusy = ref(false);
    const importJob = ref(null);
    const importMapping = reactive({});
    const importMode = ref('append');
    const importDecisions = reactive({});
    const importFileName = ref('');

    const loadImportJob = job => {
        importJob.value = job;
        Object.keys(importMapping).forEach(key => delete importMapping[key]);
        Object.assign(importMapping, job.mapping || job.source?.suggested_mapping || {});
        Object.keys(importDecisions).forEach(key => delete importDecisions[key]);
        for (const row of job.evaluation?.rows || []) {
            importDecisions[row.row_index] = row.suggested_action === 'conflict'
                ? 'skip'
                : row.suggested_action;
        }
        importStep.value = 2;
    };

    const previewImport = async event => {
        const file = event.target.files?.[0];
        if (!file || !workspace.activeWorkspaceId.value) return;
        importBusy.value = true;
        importFileName.value = file.name;
        const form = new FormData();
        form.append('file', file);
        try {
            const { data } = await axios.post(
                `/api/workspaces/${workspace.activeWorkspaceId.value}/imports/preview?kind=${importKind.value}`,
                form,
                { headers: { 'Content-Type': 'multipart/form-data' } }
            );
            loadImportJob(data);
            addToast('Файл прочитан', 'Данные ещё не записаны. Проверьте сопоставление и действия.', 'success');
        } catch (error) {
            addToast('Импорт', error.response?.data?.detail || 'Не удалось прочитать файл.', 'error');
        } finally {
            importBusy.value = false;
            event.target.value = '';
        }
    };

    const evaluateImport = async () => {
        if (!importJob.value) return;
        importBusy.value = true;
        try {
            const { data } = await axios.post(`/api/imports/${importJob.value.id}/evaluate`, {
                mapping: { ...importMapping },
                mode: importMode.value
            });
            loadImportJob(data);
            importStep.value = 3;
        } catch (error) {
            addToast('Проверка импорта', error.response?.data?.detail || 'Не удалось пересчитать импорт.', 'error');
        } finally {
            importBusy.value = false;
        }
    };

    const commitImport = async () => {
        if (!importJob.value) return;
        importBusy.value = true;
        try {
            const decisions = Object.entries(importDecisions).map(([row_index, action]) => ({
                row_index: Number(row_index),
                action
            }));
            const { data } = await axios.post(`/api/imports/${importJob.value.id}/commit`, {
                mode: importMode.value,
                decisions
            });
            importStep.value = 4;
            await workspace.loadData();
            await workspace.loadSpaces(workspace.activeWorkspaceId.value);
            if (data.workspace?.id) {
                await workspace.switchWorkspace(data.workspace.id);
            }
            addToast(
                'Импорт завершён',
                `Добавлено: ${data.added || 0}, обновлено: ${data.updated || data.merged || 0}, пропущено: ${data.skipped || 0}.`,
                data.errors ? 'warning' : 'success'
            );
        } catch (error) {
            addToast('Импорт', error.response?.data?.detail || 'Данные не записаны.', 'error');
        } finally {
            importBusy.value = false;
        }
    };

    const resetImport = () => {
        importStep.value = 1;
        importJob.value = null;
        importFileName.value = '';
        Object.keys(importMapping).forEach(key => delete importMapping[key]);
        Object.keys(importDecisions).forEach(key => delete importDecisions[key]);
    };

    const importActionLabel = action => ({
        add: 'Добавить',
        update: 'Обновить',
        merge: 'Объединить',
        skip: 'Пропустить',
        conflict: 'Конфликт',
        error: 'Ошибка'
    })[action] || action;

    // -------------------------------------------------------------- revisions
    const templateRevisions = ref([]);
    const revisionsBusy = ref(false);
    const compareFrom = ref('');
    const compareTo = ref('');
    const revisionComparison = ref(null);
    const revisionComment = ref('');
    const learnForm = reactive({
        template_name: '',
        component_label: '',
        comment: '',
        priority: 0,
        replace_component_id: ''
    });

    const templateComponents = computed(() => {
        const definition = workspace.selectedTemplate.value?.layout;
        if (!definition) return [];
        if (Array.isArray(definition.components)) return definition.components;
        return [{
            id: 'legacy',
            label: 'Основной формат',
            selector: { sheet_name: definition.sheet_name || '' },
            layout: definition,
            fingerprint: {}
        }];
    });

    const loadTemplateRevisions = async () => {
        const template = workspace.selectedTemplate.value;
        if (!template || !workspace.activeWorkspaceId.value) {
            templateRevisions.value = [];
            return;
        }
        revisionsBusy.value = true;
        try {
            const { data } = await axios.get(
                `/api/workspaces/${workspace.activeWorkspaceId.value}/templates/${template.id}/revisions`
            );
            templateRevisions.value = data;
            compareTo.value = data[0]?.id || '';
            compareFrom.value = data[1]?.id || data[0]?.id || '';
            revisionComparison.value = null;
        } catch (error) {
            addToast('Версии шаблона', error.response?.data?.detail || 'Не удалось загрузить ревизии.', 'error');
        } finally {
            revisionsBusy.value = false;
        }
    };

    const compareRevisions = async () => {
        if (!compareFrom.value || !compareTo.value) return;
        revisionsBusy.value = true;
        try {
            const { data } = await axios.get('/api/template-revisions/compare', {
                params: { from: compareFrom.value, to: compareTo.value }
            });
            revisionComparison.value = data;
        } catch (error) {
            addToast('Сравнение', error.response?.data?.detail || 'Не удалось сравнить версии.', 'error');
        } finally {
            revisionsBusy.value = false;
        }
    };

    const rollbackRevision = async revision => {
        if (!confirm(`Вернуть шаблон к ревизии ${revision.revision_number}? Текущее состояние сохранится новой ревизией.`)) return;
        revisionsBusy.value = true;
        try {
            await axios.post(
                `/api/workspaces/${workspace.activeWorkspaceId.value}/templates/${revision.template_id}/rollback`,
                { revision_id: revision.id, comment: revisionComment.value }
            );
            await workspace.loadData();
            await loadTemplateRevisions();
            addToast('Шаблон восстановлен', `Создана новая ревизия из версии ${revision.revision_number}.`, 'success');
        } catch (error) {
            addToast('Откат', error.response?.data?.detail || 'Не удалось восстановить версию.', 'error');
        } finally {
            revisionsBusy.value = false;
        }
    };

    const learnCurrentFormat = async () => {
        if (!schedule.currentFile.value || !schedule.currentLayout.value || !schedule.sessionId.value) {
            addToast('Правило формата', 'Сначала откройте и проверьте файл расписания.', 'warning');
            return;
        }
        revisionsBusy.value = true;
        try {
            const selected = workspace.selectedTemplate.value;
            const { data } = await axios.post(
                `/api/workspaces/${workspace.activeWorkspaceId.value}/templates/learn`,
                {
                    session_id: schedule.sessionId.value,
                    file_id: schedule.currentFile.value.file_id,
                    layout: schedule.normalizedLayout(schedule.currentLayout.value),
                    template_id: selected?.id || null,
                    template_name: selected ? null : (learnForm.template_name || schedule.currentFile.value.filename),
                    component_label: learnForm.component_label || schedule.currentFile.value.analysis?.selected_sheet,
                    replace_component_id: learnForm.replace_component_id || null,
                    comment: learnForm.comment,
                    priority: Number(learnForm.priority || 0)
                }
            );
            await workspace.loadData();
            workspace.selectedProfile.value = data.template.name;
            await loadTemplateRevisions();
            await interaction.rematchTemplates({ quiet: true });
            addToast('Формат сохранён', 'Разметка и структурный отпечаток добавлены в обучение.', 'success');
        } catch (error) {
            addToast('Правило формата', error.response?.data?.detail || 'Не удалось сохранить правило.', 'error');
        } finally {
            revisionsBusy.value = false;
        }
    };

    const removeTemplateComponent = async component => {
        const selected = workspace.selectedTemplate.value;
        if (!selected || !confirm(`Удалить вариант «${component.label}»?`)) return;
        try {
            await axios.delete(
                `/api/workspaces/${workspace.activeWorkspaceId.value}/templates/${selected.id}/components`,
                { data: { component_id: component.id, comment: 'Удалено оператором.' } }
            );
            await workspace.loadData();
            await loadTemplateRevisions();
            addToast('Вариант удалён', component.label, 'success');
        } catch (error) {
            addToast('Шаблон', error.response?.data?.detail || 'Не удалось удалить вариант.', 'error');
        }
    };

    watch(
        () => workspace.selectedTemplate.value?.id,
        () => loadTemplateRevisions()
    );

    // --------------------------------------------------------------- history
    const historyRuns = ref([]);
    const historyBusy = ref(false);
    const historyQuery = ref('');
    const historyStatus = ref('');
    const selectedRun = ref(null);

    const loadHistory = async () => {
        if (!workspace.activeWorkspaceId.value) return;
        historyBusy.value = true;
        try {
            const { data } = await axios.get(
                `/api/workspaces/${workspace.activeWorkspaceId.value}/history`,
                { params: { query: historyQuery.value || undefined, status: historyStatus.value || undefined } }
            );
            historyRuns.value = data;
        } catch (error) {
            addToast('История', error.response?.data?.detail || 'Не удалось загрузить историю.', 'error');
        } finally {
            historyBusy.value = false;
        }
    };

    const openHistoryRun = async run => {
        historyBusy.value = true;
        try {
            const { data } = await axios.get(`/api/history/${run.id}`);
            selectedRun.value = data;
        } catch (error) {
            addToast('История', error.response?.data?.detail || 'Не удалось открыть запуск.', 'error');
        } finally {
            historyBusy.value = false;
        }
    };

    const reopenHistoryRun = async run => {
        historyBusy.value = true;
        try {
            const { data } = await axios.post(`/api/history/${run.id}/reopen`);
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
                if (file.analysis) schedule.layouts[file.file_id] = JSON.parse(JSON.stringify(file.analysis.layout));
            });
            const first = schedule.analyzedFiles.value.find(file => file.analysis);
            if (first) {
                schedule.selectedFileId.value = first.file_id;
                schedule.step.value = 2;
                workspace.managerOpen.value = false;
                await schedule.loadPreview();
                await interaction.rematchTemplates({ quiet: true });
            }
            addToast('Запуск восстановлен', 'Файлы и разметка открыты для повторной проверки.', 'success');
        } catch (error) {
            addToast('Повтор запуска', error.response?.data?.detail || 'Не удалось восстановить запуск.', 'error');
        } finally {
            historyBusy.value = false;
        }
    };

    const historyArtifactUrl = artifact => `/api/history/artifacts/${artifact.id}`;

    // ----------------------------------------------------------- users/audit
    const users = ref([]);
    const usersBusy = ref(false);
    const userForm = reactive({
        id: null,
        username: '',
        display_name: '',
        password: '',
        role: 'operator',
        active: true
    });
    const auditEntries = ref([]);
    const auditBusy = ref(false);
    const auditQuery = ref('');
    const auditAction = ref('');

    const loadUsers = async () => {
        if (!canAdmin.value) return;
        usersBusy.value = true;
        try {
            const { data } = await axios.get('/api/auth/users');
            users.value = data;
        } catch (error) {
            addToast('Пользователи', error.response?.data?.detail || 'Не удалось загрузить пользователей.', 'error');
        } finally {
            usersBusy.value = false;
        }
    };

    const resetUserForm = () => Object.assign(userForm, {
        id: null,
        username: '',
        display_name: '',
        password: '',
        role: 'operator',
        active: true
    });

    const editUser = user => Object.assign(userForm, {
        id: user.id,
        username: user.username,
        display_name: user.display_name,
        password: '',
        role: user.role,
        active: Boolean(user.active)
    });

    const saveUser = async () => {
        usersBusy.value = true;
        try {
            if (userForm.id) {
                const payload = {
                    display_name: userForm.display_name,
                    role: userForm.role,
                    active: userForm.active
                };
                if (userForm.password) payload.password = userForm.password;
                await axios.put(`/api/auth/users/${userForm.id}`, payload);
            } else {
                await axios.post('/api/auth/users', {
                    username: userForm.username,
                    display_name: userForm.display_name,
                    password: userForm.password,
                    role: userForm.role
                });
            }
            resetUserForm();
            await loadUsers();
            addToast('Пользователь сохранён', 'Права доступа обновлены.', 'success');
        } catch (error) {
            addToast('Пользователь', error.response?.data?.detail || 'Не удалось сохранить пользователя.', 'error');
        } finally {
            usersBusy.value = false;
        }
    };

    const loadAudit = async () => {
        if (!canAdmin.value) return;
        auditBusy.value = true;
        try {
            const { data } = await axios.get('/api/audit', {
                params: {
                    workspace_id: workspace.activeWorkspaceId.value || undefined,
                    query: auditQuery.value || undefined,
                    action: auditAction.value || undefined
                }
            });
            auditEntries.value = data;
        } catch (error) {
            addToast('Журнал', error.response?.data?.detail || 'Не удалось загрузить журнал.', 'error');
        } finally {
            auditBusy.value = false;
        }
    };

    watch(
        () => workspace.managerTab.value,
        tab => {
            if (tab === 'history') loadHistory();
            if (tab === 'users') loadUsers();
            if (tab === 'audit') loadAudit();
            if (tab === 'templates') loadTemplateRevisions();
        }
    );

    const initOperations = async () => {
        const authenticated = await refreshAuth();
        if (authenticated) await initializeWorkspace();
        return authenticated;
    };

    const onWorkspaceChanged = async () => {
        selectedRun.value = null;
        historyRuns.value = [];
        auditEntries.value = [];
        resetImport();
        if (workspace.managerTab.value === 'history') await loadHistory();
        if (workspace.managerTab.value === 'audit') await loadAudit();
    };

    return {
        authReady,
        authBusy,
        setupRequired,
        currentUser,
        authForm,
        canAdmin,
        canOperate,
        canView,
        userInitials,
        initOperations,
        refreshAuth,
        bootstrap,
        login,
        logout,
        importKind,
        importStep,
        importBusy,
        importJob,
        importMapping,
        importMode,
        importDecisions,
        importFileName,
        previewImport,
        evaluateImport,
        commitImport,
        resetImport,
        importActionLabel,
        templateRevisions,
        revisionsBusy,
        compareFrom,
        compareTo,
        revisionComparison,
        revisionComment,
        learnForm,
        templateComponents,
        loadTemplateRevisions,
        compareRevisions,
        rollbackRevision,
        learnCurrentFormat,
        removeTemplateComponent,
        historyRuns,
        historyBusy,
        historyQuery,
        historyStatus,
        selectedRun,
        loadHistory,
        openHistoryRun,
        reopenHistoryRun,
        historyArtifactUrl,
        users,
        usersBusy,
        userForm,
        loadUsers,
        resetUserForm,
        editUser,
        saveUser,
        auditEntries,
        auditBusy,
        auditQuery,
        auditAction,
        loadAudit,
        onWorkspaceChanged
    };
}
