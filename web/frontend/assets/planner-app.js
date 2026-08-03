import { installWorkspaceMarkup, createWorkspaceState } from './workspace-state.js';
import { createScheduleState } from './schedule-state.js';
import { installInteractionMarkup, createInteractionState } from './interaction-ui.js';
import { installPlatformMarkup, createPlatformState } from './platform-ui.js';

const { createApp, ref, onMounted } = Vue;

export function mount() {
    installWorkspaceMarkup();
    installInteractionMarkup();
    installPlatformMarkup();
    createApp({
        setup() {
            const toasts = ref([]);
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

            let schedule;
            const workspace = createWorkspaceState(addToast, () => schedule?.invalidateAll());
            // Stable refresh aliases for operational modules without exposing
            // internal implementation details of workspace-state.
            workspace.loadData = workspace.init;
            workspace.loadSpaces = workspace.init;
            schedule = createScheduleState(addToast, workspace.activeWorkspaceId);
            const interaction = createInteractionState(
                addToast,
                schedule,
                workspace.activeWorkspaceId
            );
            const platform = createPlatformState(addToast, workspace, schedule);

            const rematchAfter = handler => async (...args) => {
                const result = await handler(...args);
                schedule.invalidateAll();
                await interaction.rematchTemplates({ quiet: true });
                return result;
            };

            const switchWorkspace = async id => {
                await workspace.switchWorkspace(id);
                if (workspace.managerTab.value === 'spaces') {
                    workspace.editWorkspace(workspace.activeWorkspace.value);
                }
                await interaction.rematchTemplates({ quiet: true });
                if (platform.operationsOpen.value) {
                    await platform.selectOperationsTab(platform.operationsTab.value);
                }
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

            const attachCurrentFingerprint = async template => {
                const fingerprint = schedule.currentFile.value?.analysis?.fingerprint || {};
                const response = await axios.put(
                    `/api/workspaces/${workspace.activeWorkspaceId.value}/templates/${template.id}/profile`,
                    {
                        layout: schedule.normalizedLayout(schedule.currentLayout.value),
                        composite: template.composite || [],
                        fingerprint,
                        comment: `Подтверждено оператором для «${schedule.currentFile.value?.filename || 'файла'}»`
                    }
                );
                await workspace.init();
                return response.data;
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
                    let template;
                    if (existing) {
                        template = await workspace.updateTemplateLayout(
                            existing.id,
                            layout,
                            name,
                            existing.description || ''
                        );
                    } else {
                        template = await workspace.createTemplate(name, '', layout);
                    }
                    template = await attachCurrentFingerprint(template);
                    workspace.profileName.value = name;
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
                }
            };

            const deleteSelectedProfile = async () => {
                if (workspace.selectedTemplate.value) {
                    await workspace.deleteTemplate(workspace.selectedTemplate.value);
                    await interaction.rematchTemplates({ quiet: true });
                }
            };

            const migrateLocalTemplates = async () => {
                const key = 'planner-solving-layout-profiles-v1';
                if (
                    workspace.layoutProfiles.value.length ||
                    localStorage.getItem(`${key}-migrated`)
                ) {
                    return;
                }
                try {
                    const oldTemplates = JSON.parse(localStorage.getItem(key) || '[]');
                    for (const item of Array.isArray(oldTemplates) ? oldTemplates : []) {
                        if (item?.name && item?.layout) {
                            await workspace.createTemplate(
                                item.name,
                                'Перенесён из локального хранилища браузера',
                                item.layout
                            );
                        }
                    }
                    if (oldTemplates.length) {
                        addToast(
                            'Шаблоны перенесены',
                            `На сервер перенесено: ${oldTemplates.length}.`,
                            'success'
                        );
                    }
                    localStorage.setItem(`${key}-migrated`, '1');
                } catch (_) {
                    localStorage.setItem(`${key}-migrated`, '1');
                }
            };

            onMounted(async () => {
                const access = await platform.initAuth();
                if (access?.setup_access || access?.authenticated) {
                    await workspace.init();
                    await migrateLocalTemplates();
                }
            });

            return {
                ...workspace,
                ...schedule,
                ...interaction,
                ...platform,
                toasts,
                addToast,
                removeToast,
                switchWorkspace,
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
                deleteSelectedProfile
            };
        }
    }).mount('#app');
}
