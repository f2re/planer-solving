import { installWorkspaceMarkup, createWorkspaceState } from './workspace-state.js';
import { createScheduleState } from './schedule-state.js';
import { installInteractionMarkup, createInteractionState } from './interaction-ui.js';
import { installPlatformMarkup, createPlatformState } from './platform-ui.js';
import { installPlatformEnhancements } from './platform-enhancements.js';
import { installHistoryUxMarkup } from './history-ux.js';
import { createHistoryUxState } from './history-ux-state.js';
import { installSampleLayoutMarkup, createSampleLayoutState } from './sample-layout-editor.js';
import { createReactiveWorkspaceState } from './reactive-workspace.js';
import { installEditorWorkspaceMarkup, createEditorWorkspaceState } from './editor-workspace.js';
import { createEditorHistoryState } from './editor-history-state.js';
import { createSessionFileActions } from './session-file-actions.js';
import { createTeacherMappingState } from './teacher-mapping-state.js';

const { createApp, ref, onMounted, nextTick } = Vue;

export function mount() {
    installWorkspaceMarkup();
    installInteractionMarkup();
    installPlatformMarkup();
    installHistoryUxMarkup();
    installPlatformEnhancements();
    installSampleLayoutMarkup();
    installEditorWorkspaceMarkup();

    createApp({
        setup() {
            const toasts = ref([]);
            const generatedFromEditor = ref(false);
            const addToast = (title, message, type = 'info') => {
                const id = `${Date.now()}-${Math.random()}`;
                toasts.value.push({ id, title, message, type });
                setTimeout(() => {
                    toasts.value = toasts.value.filter(item => item.id !== id);
                }, 6500);
            };
            const removeToast = id => {
                toasts.value = toasts.value.filter(item => item.id !== id);
            };
            const copy = value => JSON.parse(JSON.stringify(value || {}));

            let schedule;
            const workspace = createWorkspaceState(addToast, () => schedule?.invalidateAll());
            schedule = createScheduleState(addToast, workspace.activeWorkspaceId);
            const reactiveWorkspace = createReactiveWorkspaceState(addToast, workspace, schedule);
            workspace.loadData = reactiveWorkspace.refreshData;
            workspace.loadSpaces = reactiveWorkspace.refreshSpaces;
            workspace.refreshWorkspace = reactiveWorkspace.refreshWorkspace;

            const interaction = createInteractionState(
                addToast,
                schedule,
                workspace.activeWorkspaceId
            );
            const sampleLayout = createSampleLayoutState(addToast, schedule);
            const platform = createPlatformState(addToast, workspace, schedule);
            const historyUx = createHistoryUxState();
            const editor = createEditorWorkspaceState(
                addToast,
                schedule,
                interaction,
                workspace,
                platform
            );
            const editorHistory = createEditorHistoryState(
                addToast,
                schedule,
                editor
            );
            const sessionFiles = createSessionFileActions(
                addToast,
                schedule,
                workspace.activeWorkspaceId
            );
            const teacherMapping = createTeacherMappingState(
                addToast,
                schedule,
                workspace.activeWorkspaceId
            );

            const rawRefreshSpaces = reactiveWorkspace.refreshSpaces;
            workspace.loadSpaces = async preferred => {
                const result = await rawRefreshSpaces(preferred, { silent: true });
                if (platform.importJob.value?.status === 'committed') {
                    await reactiveWorkspace.refreshData({ silent: true });
                    platform.operationsOpen.value = false;
                    workspace.openManager(platform.importKind.value === 'teachers' ? 'teachers' : 'templates');
                }
                return result;
            };

            const rematchAfter = handler => async (...args) => {
                const result = await handler(...args);
                await reactiveWorkspace.refreshAfterMutation({ silent: true });
                schedule.invalidateAll();
                await interaction.rematchTemplates({ quiet: true });
                return result;
            };

            const switchWorkspace = async id => {
                const targetId = String(id || '');
                const previousId = String(localStorage.getItem('planner-workspace-id') || '');
                if (!targetId) return false;
                if (targetId === previousId) {
                    workspace.activeWorkspaceId.value = targetId;
                    return true;
                }

                const activeSession = Boolean(
                    schedule.sessionId.value && schedule.analyzedFiles.value.length
                );
                if (activeSession) {
                    const previous = workspace.workspaces.value.find(item => item.id === previousId);
                    const target = workspace.workspaces.value.find(item => item.id === targetId);
                    const accepted = window.confirm(
                        `Переключить пространство «${previous?.name || 'текущее'}» на «${target?.name || targetId}»?\n\n`
                        + 'Исходные файлы, группы, ручная разметка и календарные правки сохранятся. '
                        + 'Справочник преподавателей и рекомендации шаблонов будут взяты из нового пространства; '
                        + 'проверки файлов потребуется пересчитать.'
                    );
                    if (!accepted) {
                        workspace.activeWorkspaceId.value = previousId;
                        return false;
                    }
                    await window.__plannerSessionDraft?.flush?.();
                }

                const layoutSnapshot = Object.fromEntries(
                    Object.entries(schedule.layouts).map(([fileId, layout]) => [fileId, copy(layout)])
                );
                await workspace.switchWorkspace(targetId);
                await reactiveWorkspace.refreshWorkspace(targetId, { silent: true });
                if (workspace.managerTab.value === 'spaces') {
                    workspace.editWorkspace(workspace.activeWorkspace.value);
                }
                await interaction.rematchTemplates({ quiet: true });

                if (activeSession) {
                    for (const [fileId, layout] of Object.entries(layoutSnapshot)) {
                        schedule.layouts[fileId] = layout;
                    }
                    schedule.invalidateAll();
                    teacherMapping.clearTeacherMappingState();
                    editorHistory.resetEditorHistory();
                    if (schedule.currentFile.value?.analysis) await schedule.loadPreview();
                    addToast(
                        'Пространство изменено',
                        'Файлы и ручная разметка сохранены. Преподаватели, шаблоны и период взяты из нового пространства; пересчитайте проверки.',
                        'info'
                    );
                }
                return true;
            };

            const deleteTeacher = async value => {
                const teacher = typeof value === 'object' && value
                    ? value
                    : workspace.teachers.value.find(item => item.id === Number(value));
                if (!teacher) {
                    addToast('Преподаватель не найден', 'Обновите список и повторите действие.', 'warning');
                    return;
                }
                await workspace.deleteTeacher(teacher);
                await reactiveWorkspace.refreshAfterMutation({ silent: true });
                schedule.invalidateAll();
                await interaction.rematchTemplates({ quiet: true });
            };

            const saveTeacher = rematchAfter(workspace.saveTeacher);
            const importTeachers = () => platform.openOperations('import', 'teachers');
            const importTemplates = () => platform.openOperations('import', 'templates');
            const saveWorkspace = rematchAfter(workspace.saveWorkspace);
            const duplicateWorkspace = rematchAfter(workspace.duplicateWorkspace);
            const deleteWorkspace = rematchAfter(workspace.deleteWorkspace);
            const importWorkspace = rematchAfter(workspace.importWorkspace);

            const leaveSheetWorkspace = () => {
                if (!editor.layoutDirty.value) {
                    editor.leaveSheetWorkspace();
                    return;
                }
                editor.templateSaveOpen.value = false;
                editor.pendingEditorExit.value = false;
                editor.sheetWorkspaceOpen.value = false;
                editor.sheetWorkspacePreferred.value = false;
                document.documentElement.classList.remove('sheet-workspace-open');
                window.__plannerSessionDraft?.flush?.();
                addToast(
                    'Разметка файла сохранена',
                    'Изменения остались в текущем серверном черновике. Глобальный шаблон не изменён.',
                    'success'
                );
            };

            const refreshCurrentRun = async runId => {
                if (!runId || !workspace.activeWorkspaceId.value) return null;
                await platform.selectOperationsTab('history');
                const run = platform.processingRuns.value.find(item => item.id === runId);
                if (run) await platform.selectRun(run);
                return run || null;
            };

            const generate = async () => {
                await window.__plannerSessionDraft?.flush?.();
                await schedule.generate();
                const runId = schedule.result.value?.run_id;
                if (runId) await refreshCurrentRun(runId);
            };

            const generateFromEditor = async () => {
                generatedFromEditor.value = Boolean(editor.sheetWorkspaceOpen.value);
                editor.templateSaveOpen.value = false;
                editor.pendingEditorExit.value = false;
                editor.sheetWorkspaceOpen.value = false;
                document.documentElement.classList.remove('sheet-workspace-open');
                await generate();
            };

            const returnToCorrections = async () => {
                if (!schedule.sessionId.value || !schedule.analyzedFiles.value.length) {
                    addToast('Сеанс недоступен', 'Исходные файлы уже очищены; загрузите их повторно.', 'warning');
                    return;
                }
                schedule.step.value = 2;
                await nextTick();
                if (schedule.currentFile.value?.analysis) {
                    await schedule.loadPreview();
                }
                if (generatedFromEditor.value && schedule.currentFile.value?.analysis) {
                    await editor.enterSheetWorkspace(true);
                }
                addToast(
                    'Возврат к исправлениям',
                    'Файлы, разметка, даты и ручные назначения сохранены в текущем сеансе.',
                    'info'
                );
            };

            const openCurrentRunHistory = async () => {
                const runId = schedule.result.value?.run_id;
                platform.operationsOpen.value = true;
                await platform.selectOperationsTab('history');
                if (runId) await refreshCurrentRun(runId);
            };

            const saveCurrentProfile = async () => {
                const name = workspace.profileName.value.trim();
                if (!name || !schedule.currentLayout.value) {
                    addToast('Шаблон разметки', 'Введите название шаблона.', 'warning');
                    return;
                }
                try {
                    const existing = workspace.layoutProfiles.value.find(
                        item => item.name.toLocaleLowerCase('ru') === name.toLocaleLowerCase('ru')
                    );
                    const layout = schedule.normalizedLayout(schedule.currentLayout.value);
                    const fingerprint = schedule.currentFile.value?.analysis?.fingerprint || {};
                    const comment = `Подтверждено оператором для «${schedule.currentFile.value?.filename || 'файла'}»`;
                    let template;
                    if (existing) {
                        const { data } = await axios.put(
                            `/api/workspaces/${workspace.activeWorkspaceId.value}/templates/${existing.id}/profile`,
                            {
                                name,
                                description: existing.description || '',
                                layout,
                                composite: existing.composite || [],
                                fingerprint,
                                comment
                            }
                        );
                        template = data;
                    } else {
                        const { data } = await axios.post(
                            `/api/workspaces/${workspace.activeWorkspaceId.value}/templates`,
                            {
                                name,
                                description: '',
                                layout,
                                composite: [],
                                fingerprint,
                                comment
                            }
                        );
                        template = data;
                    }
                    await reactiveWorkspace.refreshWorkspace(workspace.activeWorkspaceId.value, { silent: true });
                    workspace.profileName.value = name;
                    workspace.selectedProfile.value = template.name;
                    addToast(
                        'Шаблон сохранён',
                        `«${name}» сохранён версией ${template.current_revision}.`,
                        'success'
                    );
                } catch (error) {
                    addToast(
                        'Ошибка шаблона',
                        error.response?.data?.detail || 'Не удалось сохранить шаблон.',
                        'error'
                    );
                }
            };

            const applySelectedProfile = async () => {
                if (workspace.selectedTemplate.value) {
                    await schedule.applyTemplate(workspace.selectedTemplate.value);
                    await editor.recalculateNow();
                }
            };

            const deleteSelectedProfile = async () => {
                if (workspace.selectedTemplate.value) {
                    await workspace.deleteTemplate(workspace.selectedTemplate.value);
                    await reactiveWorkspace.refreshAfterMutation({ silent: true });
                    await interaction.rematchTemplates({ quiet: true });
                }
            };

            const migrateLocalTemplates = async () => {
                const key = 'planner-solving-layout-profiles-v1';
                const migrationKey = `${key}-main-workspace-v2`;
                const oldDescription = 'Перенесён из локального хранилища браузера';
                if (localStorage.getItem(migrationKey)) return;
                try {
                    const legacyWorkspace = (
                        workspace.workspaces.value.find(
                            item => String(item.name || '').trim().toLocaleLowerCase('ru') === 'основное пространство'
                        )
                        || workspace.workspaces.value.find(item => item.is_default)
                        || workspace.workspaces.value[0]
                    );
                    if (!legacyWorkspace?.id) return;

                    const templatesByWorkspace = new Map();
                    for (const space of workspace.workspaces.value) {
                        const { data } = await axios.get(`/api/workspaces/${space.id}/templates`);
                        templatesByWorkspace.set(space.id, Array.isArray(data) ? data : []);
                    }

                    const rawLocal = JSON.parse(localStorage.getItem(key) || '[]');
                    const candidates = [];
                    for (const item of Array.isArray(rawLocal) ? rawLocal : []) {
                        if (item?.name && item?.layout) candidates.push(item);
                    }
                    for (const templates of templatesByWorkspace.values()) {
                        for (const item of templates) {
                            if (item?.description === oldDescription && item?.name && item?.layout) {
                                candidates.push(item);
                            }
                        }
                    }

                    const uniqueCandidates = new Map();
                    for (const item of candidates) {
                        const normalizedName = String(item.name || '').trim().toLocaleLowerCase('ru');
                        if (normalizedName && !uniqueCandidates.has(normalizedName)) {
                            uniqueCandidates.set(normalizedName, item);
                        }
                    }

                    const mainTemplates = templatesByWorkspace.get(legacyWorkspace.id) || [];
                    const mainNames = new Set(
                        mainTemplates
                            .map(item => String(item.name || '').trim().toLocaleLowerCase('ru'))
                            .filter(Boolean)
                    );
                    let imported = 0;
                    for (const [normalizedName, item] of uniqueCandidates.entries()) {
                        if (mainNames.has(normalizedName)) continue;
                        await axios.post(
                            `/api/workspaces/${legacyWorkspace.id}/templates`,
                            {
                                name: item.name,
                                description: 'Перенесён из данных, созданных до введения пространств',
                                layout: item.layout,
                                comment: 'Legacy-данные закреплены за Основным пространством'
                            }
                        );
                        mainNames.add(normalizedName);
                        imported += 1;
                    }

                    let removed = 0;
                    for (const space of workspace.workspaces.value) {
                        if (space.id === legacyWorkspace.id) continue;
                        for (const item of templatesByWorkspace.get(space.id) || []) {
                            const normalizedName = String(item.name || '').trim().toLocaleLowerCase('ru');
                            if (
                                item.description === oldDescription
                                && uniqueCandidates.has(normalizedName)
                            ) {
                                await axios.delete(`/api/workspaces/${space.id}/templates/${item.id}`);
                                removed += 1;
                            }
                        }
                    }

                    localStorage.setItem(migrationKey, '1');
                    await reactiveWorkspace.refreshWorkspace(
                        workspace.activeWorkspaceId.value,
                        { silent: true }
                    );
                    if (imported || removed) {
                        addToast(
                            'Старые шаблоны закреплены',
                            `Основное пространство: добавлено ${imported}; из других пространств удалено автоматических копий: ${removed}.`,
                            'success'
                        );
                    }
                } catch (error) {
                    console.warn('[planner] legacy template migration failed', error);
                }
            };

            const submitAuth = async () => {
                const success = await platform.submitAuth();
                if (success) {
                    await reactiveWorkspace.refreshWorkspace(null, { silent: true });
                    reactiveWorkspace.startReactiveSync();
                    await migrateLocalTemplates();
                }
                return success;
            };

            const logout = async () => {
                reactiveWorkspace.stopReactiveSync();
                sessionFiles.clearRemovedFileUndo();
                teacherMapping.clearTeacherMappingState();
                editorHistory.resetEditorHistory();
                historyUx.closeHistoryFileDecisions();
                if (schedule.sessionId.value) await schedule.resetWorkflow();
                await platform.logout();
                workspace.workspaces.value = [];
                workspace.teachers.value = [];
                workspace.layoutProfiles.value = [];
            };

            const repeatRun = async run => {
                if (!run || !workspace.activeWorkspaceId.value) return;
                if (!confirm('Повторить обработку с архивными исходниками и прежней разметкой?')) return;
                try {
                    const { data } = await axios.post(
                        `/api/workspaces/${workspace.activeWorkspaceId.value}/runs/${run.id}/repeat`
                    );
                    addToast(
                        'Обработка повторена',
                        data.message,
                        data.status === 'success' ? 'success' : 'warning'
                    );
                    historyUx.closeHistoryFileDecisions();
                    await platform.selectOperationsTab('history');
                } catch (error) {
                    addToast(
                        'Повтор не выполнен',
                        error.response?.data?.detail || 'Архивный запуск не удалось повторить.',
                        'error'
                    );
                }
            };

            onMounted(async () => {
                const access = await platform.initAuth();
                if (access?.setup_access || access?.authenticated) {
                    await reactiveWorkspace.refreshWorkspace(null, { silent: true });
                    reactiveWorkspace.startReactiveSync();
                    await migrateLocalTemplates();
                }
            });

            return {
                ...workspace,
                ...schedule,
                ...interaction,
                ...sampleLayout,
                ...platform,
                ...historyUx,
                ...reactiveWorkspace,
                ...editor,
                ...editorHistory,
                ...sessionFiles,
                ...teacherMapping,
                toasts,
                addToast,
                removeToast,
                switchWorkspace,
                leaveSheetWorkspace,
                generate,
                generateFromEditor,
                returnToCorrections,
                openCurrentRunHistory,
                saveTeacher,
                deleteTeacher,
                importTeachers,
                importTemplates,
                saveWorkspace,
                duplicateWorkspace,
                deleteWorkspace,
                importWorkspace,
                saveCurrentProfile,
                applySelectedProfile,
                deleteSelectedProfile,
                submitAuth,
                logout,
                repeatRun
            };
        }
    }).mount('#app');
}
