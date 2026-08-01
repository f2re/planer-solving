import { installWorkspaceMarkup, createWorkspaceState } from './workspace-state.js';
import { createScheduleState } from './schedule-state.js';

const { createApp, ref, onMounted } = Vue;

export function mount() {
    installWorkspaceMarkup();
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
            schedule = createScheduleState(addToast, workspace.activeWorkspaceId);

            const invalidateAfter = handler => async (...args) => {
                const result = await handler(...args);
                schedule.invalidateAll();
                return result;
            };

            const switchWorkspace = async id => {
                await workspace.switchWorkspace(id);
                if (workspace.managerTab.value === 'spaces') {
                    workspace.editWorkspace(workspace.activeWorkspace.value);
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
            };

            const saveTeacher = invalidateAfter(workspace.saveTeacher);
            const importTeachers = invalidateAfter(workspace.importTeachers);
            const saveWorkspace = invalidateAfter(workspace.saveWorkspace);
            const duplicateWorkspace = invalidateAfter(workspace.duplicateWorkspace);
            const deleteWorkspace = invalidateAfter(workspace.deleteWorkspace);
            const importWorkspace = invalidateAfter(workspace.importWorkspace);

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
                    if (existing) {
                        await workspace.updateTemplateLayout(
                            existing.id,
                            layout,
                            name,
                            existing.description || ''
                        );
                    } else {
                        await workspace.createTemplate(name, '', layout);
                    }
                    workspace.profileName.value = name;
                    addToast(
                        'Шаблон сохранён',
                        `«${name}» сохранён в пространстве «${workspace.activeWorkspace.value?.name}».`,
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
                await workspace.init();
                await migrateLocalTemplates();
            });

            return {
                ...workspace,
                ...schedule,
                toasts,
                addToast,
                removeToast,
                switchWorkspace,
                saveTeacher,
                deleteTeacher,
                importTeachers,
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
