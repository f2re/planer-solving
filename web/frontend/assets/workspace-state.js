const { ref, reactive, computed } = Vue;

function formatIsoDate(year, month, day) {
    return [year, month, day]
        .map((value, index) => index === 0 ? String(value) : String(value).padStart(2, '0'))
        .join('-');
}

function defaultSemesterDates(reference = new Date()) {
    const year = reference.getFullYear();
    if (reference.getMonth() <= 5) {
        return {
            schedule_start_date: formatIsoDate(year, 2, 1),
            schedule_end_date: formatIsoDate(year, 6, 30)
        };
    }
    return {
        schedule_start_date: formatIsoDate(year, 9, 1),
        schedule_end_date: formatIsoDate(year + 1, 1, 31)
    };
}

function emptyWorkspaceForm() {
    return {
        id: null,
        name: '',
        color: '#315EFB',
        description: '',
        ...defaultSemesterDates(),
        is_default: false
    };
}

export function installWorkspaceMarkup() {
    const topbar = document.querySelector('.topbar');
    if (topbar && !document.querySelector('.workspace-switcher')) {
        topbar.insertAdjacentHTML('beforeend', `
            <div class="workspace-switcher">
                <span class="workspace-dot" :style="{background: activeWorkspace?.color || '#315EFB'}"></span>
                <select class="workspace-select" v-model="activeWorkspaceId" @change="switchWorkspace(activeWorkspaceId)" aria-label="Активное пространство">
                    <option v-for="space in workspaces" :key="space.id" :value="space.id">{{ space.name }}</option>
                </select>
                <button class="btn btn-secondary btn-small" type="button" @click="openManager('teachers')">Управление</button>
            </div>`);
    }

    const app = document.querySelector('#app');
    if (app && !document.querySelector('.workspace-modal')) {
        app.insertAdjacentHTML('beforeend', `
        <div v-if="managerOpen" class="modal-backdrop" @click.self="managerOpen=false">
          <section class="workspace-modal card" role="dialog" aria-modal="true" aria-label="Управление пространством">
            <header class="modal-header">
              <div><h2>{{ activeWorkspace?.name }}</h2><p>Преподаватели, шаблоны и параметры формируются независимо для каждого пространства.</p></div>
              <button class="modal-close" @click="managerOpen=false" aria-label="Закрыть">×</button>
            </header>
            <nav class="manager-tabs">
              <button :class="{active:managerTab==='teachers'}" @click="managerTab='teachers'">Преподаватели <b>{{ teachers.length }}</b></button>
              <button :class="{active:managerTab==='templates'}" @click="managerTab='templates'">Шаблоны <b>{{ layoutProfiles.length }}</b></button>
              <button :class="{active:managerTab==='spaces'}" @click="managerTab='spaces'">Пространства <b>{{ workspaces.length }}</b></button>
            </nav>
            <div class="modal-content">
              <div v-if="managerTab==='teachers'" class="manager-grid">
                <section>
                  <div class="manager-toolbar">
                    <input class="control" v-model.trim="teacherSearch" placeholder="Поиск по ФИО или должности">
                    <div class="button-row">
                      <a class="btn btn-secondary btn-small" :href="teacherExportUrl('csv')" download>CSV</a>
                      <a class="btn btn-secondary btn-small" :href="teacherExportUrl('json')" download>JSON</a>
                      <label class="btn btn-secondary btn-small">Импорт<input hidden type="file" accept=".csv,.json,.txt" @change="importTeachers"></label>
                    </div>
                  </div>
                  <div class="manager-list">
                    <article v-for="teacher in filteredTeachers" :key="teacher.id" class="manager-row">
                      <div><strong>{{ teacher.short_name }}</strong><span>{{ teacher.full_name }}</span><small>{{ teacher.position || 'Должность не указана' }}</small></div>
                      <div class="button-row"><button class="btn btn-secondary btn-small" @click="editTeacher(teacher)">Изменить</button><button class="btn btn-danger btn-small" @click="deleteTeacher(teacher)">Удалить</button></div>
                    </article>
                    <div v-if="!filteredTeachers.length" class="empty-state">Подходящих записей нет.</div>
                  </div>
                </section>
                <form class="manager-form" @submit.prevent="saveTeacher">
                  <h3>{{ editingTeacher ? 'Редактирование' : 'Новый преподаватель' }}</h3>
                  <label>Краткое имя<input class="control" v-model.trim="teacherForm.short_name" required></label>
                  <label>Полное ФИО<input class="control" v-model.trim="teacherForm.full_name" required></label>
                  <label>Должность<input class="control" v-model.trim="teacherForm.position"></label>
                  <label>Звание<input class="control" v-model.trim="teacherForm.rank"></label>
                  <label>Степень<input class="control" v-model.trim="teacherForm.academic_degree"></label>
                  <div class="button-row"><button class="btn btn-primary" :disabled="teacherBusy">{{ editingTeacher ? 'Сохранить' : 'Добавить' }}</button><button v-if="editingTeacher" type="button" class="btn btn-secondary" @click="resetTeacherForm">Отмена</button></div>
                </form>
              </div>

              <div v-else-if="managerTab==='templates'" class="manager-grid">
                <section>
                  <div class="manager-toolbar">
                    <p class="manager-hint">Шаблоны хранятся в SQLite на сервере и доступны с любого рабочего места.</p>
                    <div class="button-row"><a class="btn btn-secondary btn-small" :href="templateExportUrl" download>Экспорт JSON</a><label class="btn btn-secondary btn-small">Импорт JSON<input hidden type="file" accept=".json" @change="importTemplates"></label></div>
                  </div>
                  <div class="manager-list">
                    <article v-for="profile in layoutProfiles" :key="profile.id" class="manager-row" :class="{selected:selectedProfile===profile.name}" @click="selectTemplateForEdit(profile)">
                      <div><strong>{{ profile.name }}</strong><span>{{ profile.description || 'Без описания' }}</span><small>Версия {{ profile.revision_number || 1 }} · успешно {{ profile.success_count || 0 }} · ошибок {{ profile.failure_count || 0 }}</small></div>
                      <button class="btn btn-danger btn-small" @click.stop="deleteTemplate(profile)">Удалить</button>
                    </article>
                    <div v-if="!layoutProfiles.length" class="empty-state">Шаблоны ещё не сохранены.</div>
                  </div>
                </section>
                <form class="manager-form" @submit.prevent="saveTemplateMetadata">
                  <h3>{{ templateForm.id ? 'Свойства шаблона' : 'Новый шаблон создаётся из текущей разметки' }}</h3>
                  <label>Название<input class="control" v-model.trim="templateForm.name" required></label>
                  <label>Описание<textarea class="control textarea" v-model.trim="templateForm.description"></textarea></label>
                  <label>Комментарий к версии<input class="control" v-model.trim="templateForm.comment" placeholder="Что изменено"></label>
                  <div class="button-row"><button class="btn btn-primary" :disabled="!templateForm.id">Сохранить свойства</button><button type="button" class="btn btn-secondary" @click="clearTemplateForm">Очистить</button></div>
                  <p class="manager-hint">Для создания нового шаблона откройте этап разметки и нажмите «Сохранить текущую разметку».</p>
                </form>
              </div>

              <div v-else class="spaces-layout">
                <section class="space-cards">
                  <article v-for="space in workspaces" :key="space.id" class="space-card" :class="{active:space.id===activeWorkspaceId}" @click="switchWorkspace(space.id)">
                    <span class="space-color" :style="{background:space.color}"></span>
                    <div><strong>{{ space.name }}</strong><span>{{ space.description || 'Без описания' }}</span><small>{{ space.teacher_count }} преподавателей · {{ space.template_count }} шаблонов</small></div>
                    <span v-if="space.is_default" class="default-badge">Основное</span>
                  </article>
                </section>
                <form class="manager-form" @submit.prevent="saveWorkspace">
                  <h3>{{ workspaceForm.id ? 'Настройки пространства' : 'Новое пространство' }}</h3>
                  <label>Название<input class="control" v-model.trim="workspaceForm.name" required></label>
                  <label>Цвет<div class="color-control"><input type="color" v-model="workspaceForm.color"><input class="control" v-model.trim="workspaceForm.color" pattern="#[0-9A-Fa-f]{6}"></div></label>
                  <label>Описание<textarea class="control textarea" v-model.trim="workspaceForm.description"></textarea></label>
                  <div class="field-grid"><label>Начало семестра<input class="control" type="date" v-model="workspaceForm.schedule_start_date"></label><label>Конец семестра<input class="control" type="date" v-model="workspaceForm.schedule_end_date"></label></div>
                  <label v-if="workspaceForm.id" class="check-row"><input type="checkbox" v-model="workspaceForm.is_default"> Использовать по умолчанию</label>
                  <div class="button-row"><button class="btn btn-primary">{{ workspaceForm.id ? 'Сохранить' : 'Создать' }}</button><button type="button" class="btn btn-secondary" @click="newWorkspace">Новое</button></div>
                  <div v-if="workspaceForm.id" class="danger-zone"><button type="button" class="btn btn-secondary btn-small" @click="duplicateWorkspace">Создать копию</button><a class="btn btn-secondary btn-small" :href="workspaceExportUrl" download>Экспорт</a><button type="button" class="btn btn-danger btn-small" @click="deleteWorkspace">Удалить</button></div>
                  <label class="import-space">Импортировать пространство из JSON<input type="file" accept=".json" @change="importWorkspace"></label>
                </form>
              </div>
            </div>
          </section>
        </div>`);
    }
}

export function createWorkspaceState(addToast, onWorkspaceChanged) {
    const workspaces = ref([]);
    const activeWorkspaceId = ref(localStorage.getItem('planner-workspace-id') || '');
    const teachers = ref([]);
    const layoutProfiles = ref([]);
    const selectedProfile = ref('');
    const profileName = ref('');
    const showTeachers = ref(false);
    const managerOpen = ref(false);
    const managerTab = ref('teachers');
    const teacherBusy = ref(false);
    const editingTeacher = ref(false);
    const teacherSearch = ref('');

    const teacherForm = reactive({
        id: null,
        short_name: '',
        full_name: '',
        position: '',
        rank: '',
        academic_degree: ''
    });
    const templateForm = reactive({ id: null, name: '', description: '', comment: '' });
    const workspaceForm = reactive(emptyWorkspaceForm());

    const activeWorkspace = computed(
        () => workspaces.value.find(item => item.id === activeWorkspaceId.value) || null
    );
    const filteredTeachers = computed(() => {
        const query = teacherSearch.value.toLocaleLowerCase('ru');
        if (!query) return teachers.value;
        return teachers.value.filter(teacher =>
            `${teacher.short_name} ${teacher.full_name} ${teacher.position}`
                .toLocaleLowerCase('ru')
                .includes(query)
        );
    });
    const selectedTemplate = computed(() =>
        layoutProfiles.value.find(item =>
            item.id === selectedProfile.value || item.name === selectedProfile.value
        ) || null
    );
    const templateExportUrl = computed(() => api('/templates/export'));
    const workspaceExportUrl = computed(
        () => activeWorkspaceId.value ? api('/export') : '#'
    );

    const api = path => `/api/workspaces/${activeWorkspaceId.value}${path}`;
    const errorMessage = (error, fallback) => error.response?.data?.detail || fallback;
    const setTheme = () => document.documentElement.style.setProperty(
        '--primary',
        activeWorkspace.value?.color || '#315EFB'
    );

    const loadSpaces = async preferred => {
        const { data } = await axios.get('/api/workspaces');
        workspaces.value = data;
        const target = preferred || activeWorkspaceId.value;
        const exists = data.some(item => item.id === target);
        activeWorkspaceId.value = exists
            ? target
            : (data.find(item => item.is_default)?.id || data[0]?.id || '');
        localStorage.setItem('planner-workspace-id', activeWorkspaceId.value);
        setTheme();
    };

    const clearTemplateForm = () => Object.assign(templateForm, {
        id: null,
        name: '',
        description: '',
        comment: ''
    });

    const loadData = async () => {
        if (!activeWorkspaceId.value) return;
        const previousTemplateId = selectedTemplate.value?.id || '';
        const [teacherResponse, templateResponse] = await Promise.all([
            axios.get(api('/teachers')),
            axios.get(api('/templates'))
        ]);
        teachers.value = teacherResponse.data;
        layoutProfiles.value = templateResponse.data;
        const preserved = layoutProfiles.value.find(item => item.id === previousTemplateId);
        selectedProfile.value = preserved?.name || '';
        if (!preserved) clearTemplateForm();
    };

    const resetTeacherForm = () => {
        Object.assign(teacherForm, {
            id: null,
            short_name: '',
            full_name: '',
            position: '',
            rank: '',
            academic_degree: ''
        });
        editingTeacher.value = false;
    };

    const switchWorkspace = async id => {
        if (!id) return;
        try {
            activeWorkspaceId.value = id;
            localStorage.setItem('planner-workspace-id', id);
            setTheme();
            resetTeacherForm();
            selectedProfile.value = '';
            clearTemplateForm();
            await loadData();
            if (onWorkspaceChanged) await onWorkspaceChanged();
            addToast(
                'Пространство выбрано',
                `Активно: ${activeWorkspace.value?.name || ''}`,
                'success'
            );
        } catch (error) {
            addToast('Ошибка', errorMessage(error, 'Не удалось переключить пространство.'), 'error');
        }
    };

    const init = async () => {
        try {
            await loadSpaces();
            await loadData();
        } catch (error) {
            addToast('Ошибка', errorMessage(error, 'Не удалось загрузить пространства.'), 'error');
        }
    };

    const openManager = tab => {
        managerTab.value = tab;
        managerOpen.value = true;
        if (tab === 'spaces') editWorkspace(activeWorkspace.value);
    };

    const resetTeacherForm = () => {
        Object.assign(teacherForm, {
            id: null,
            short_name: '',
            full_name: '',
            position: '',
            rank: '',
            academic_degree: ''
        });
        editingTeacher.value = false;
    };

    const editTeacher = teacher => {
        Object.assign(teacherForm, teacher);
        editingTeacher.value = true;
        showTeachers.value = true;
    };

    const saveTeacher = async () => {
        teacherBusy.value = true;
        try {
            const url = teacherForm.id
                ? api(`/teachers/${teacherForm.id}`)
                : api('/teachers');
            await axios[teacherForm.id ? 'put' : 'post'](url, teacherForm);
            resetTeacherForm();
            await loadData();
            await loadSpaces(activeWorkspaceId.value);
            addToast('Сохранено', 'Список преподавателей обновлён.', 'success');
        } catch (error) {
            addToast('Ошибка', errorMessage(error, 'Не удалось сохранить запись.'), 'error');
        } finally {
            teacherBusy.value = false;
        }
    };

    const deleteTeacher = async teacher => {
        if (!confirm(`Удалить ${teacher.short_name}?`)) return;
        try {
            await axios.delete(api(`/teachers/${teacher.id}`));
            await loadData();
            await loadSpaces(activeWorkspaceId.value);
            addToast('Удалено', 'Преподаватель удалён из пространства.', 'success');
        } catch (error) {
            addToast('Удаление', errorMessage(error, 'Не удалось удалить преподавателя.'), 'error');
        }
    };

    const teacherExportUrl = format => api(`/teachers/export?format=${format}`);

    const importFile = async () => {
        addToast('Импорт', 'Используйте вкладку «Импорт» — там данные можно проверить до записи.', 'info');
    };
    const importTeachers = importFile;
    const importTemplates = importFile;

    const selectTemplateForEdit = profile => {
        selectedProfile.value = profile.name;
        Object.assign(templateForm, {
            id: profile.id,
            name: profile.name,
            description: profile.description || '',
            comment: ''
        });
    };

    const saveTemplateMetadata = async () => {
        if (!templateForm.id) return;
        try {
            const { data } = await axios.put(api(`/templates/${templateForm.id}`), {
                name: templateForm.name,
                description: templateForm.description,
                comment: templateForm.comment || 'Изменены свойства шаблона.'
            });
            await loadData();
            selectedProfile.value = data.name;
            templateForm.comment = '';
            addToast('Шаблон сохранён', 'Создана новая ревизия свойств.', 'success');
        } catch (error) {
            addToast('Ошибка шаблона', errorMessage(error, 'Не удалось сохранить шаблон.'), 'error');
        }
    };

    const deleteTemplate = async profile => {
        if (!confirm(`Удалить шаблон «${profile.name}» со всеми ревизиями?`)) return;
        try {
            await axios.delete(api(`/templates/${profile.id}`));
            selectedProfile.value = '';
            clearTemplateForm();
            await loadData();
            addToast('Шаблон удалён', profile.name, 'success');
        } catch (error) {
            addToast('Удаление', errorMessage(error, 'Не удалось удалить шаблон.'), 'error');
        }
    };

    const createTemplate = async (name, description, layout, comment = '') => {
        const { data } = await axios.post(api('/templates'), {
            name,
            description,
            layout,
            comment
        });
        await loadData();
        selectedProfile.value = data.name;
        return data;
    };

    const updateTemplateLayout = async (id, layout, name, description, comment = '') => {
        const { data } = await axios.put(api(`/templates/${id}`), {
            layout,
            name,
            description,
            comment
        });
        await loadData();
        selectedProfile.value = data.name;
        return data;
    };

    const newWorkspace = () => Object.assign(workspaceForm, emptyWorkspaceForm());

    const editWorkspace = workspace => {
        if (!workspace) {
            newWorkspace();
            return;
        }
        const defaults = defaultSemesterDates();
        Object.assign(workspaceForm, {
            id: workspace.id,
            name: workspace.name,
            color: workspace.color,
            description: workspace.description || '',
            schedule_start_date:
                workspace.settings?.schedule_start_date || defaults.schedule_start_date,
            schedule_end_date:
                workspace.settings?.schedule_end_date || defaults.schedule_end_date,
            is_default: Boolean(workspace.is_default)
        });
    };

    const saveWorkspace = async () => {
        if (workspaceForm.schedule_start_date > workspaceForm.schedule_end_date) {
            addToast(
                'Проверьте даты',
                'Дата начала семестра не может быть позже даты окончания.',
                'warning'
            );
            return;
        }
        const payload = {
            name: workspaceForm.name,
            color: workspaceForm.color,
            description: workspaceForm.description,
            is_default: workspaceForm.is_default,
            settings: {
                schedule_start_date: workspaceForm.schedule_start_date,
                schedule_end_date: workspaceForm.schedule_end_date
            }
        };
        try {
            const { data } = workspaceForm.id
                ? await axios.put(`/api/workspaces/${workspaceForm.id}`, payload)
                : await axios.post('/api/workspaces', payload);
            await loadSpaces(data.id);
            await loadData();
            editWorkspace(activeWorkspace.value);
            addToast('Пространство сохранено', 'Настройки применены.', 'success');
        } catch (error) {
            addToast('Ошибка', errorMessage(error, 'Не удалось сохранить пространство.'), 'error');
        }
    };

    const duplicateWorkspace = async () => {
        try {
            const { data } = await axios.post(api('/duplicate'), {});
            await loadSpaces(data.id);
            await loadData();
            editWorkspace(activeWorkspace.value);
            addToast('Пространство скопировано', data.name, 'success');
        } catch (error) {
            addToast('Копирование', errorMessage(error, 'Не удалось создать копию.'), 'error');
        }
    };

    const deleteWorkspace = async () => {
        if (!confirm(`Удалить пространство «${activeWorkspace.value?.name}» со всеми данными?`)) {
            return;
        }
        try {
            await axios.delete(`/api/workspaces/${activeWorkspaceId.value}`);
            await loadSpaces();
            await loadData();
            editWorkspace(activeWorkspace.value);
            addToast('Пространство удалено', 'Активировано основное пространство.', 'success');
        } catch (error) {
            addToast('Удаление', errorMessage(error, 'Не удалось удалить пространство.'), 'error');
        }
    };

    const importWorkspace = async () => {
        managerTab.value = 'imports';
        addToast('Импорт пространства', 'Выберите тип «Пространство» в мастере импорта.', 'info');
    };

    const formatDate = value => value
        ? new Date(value).toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' })
        : '—';

    return {
        workspaces,
        activeWorkspaceId,
        activeWorkspace,
        teachers,
        layoutProfiles,
        selectedProfile,
        selectedTemplate,
        profileName,
        showTeachers,
        managerOpen,
        managerTab,
        teacherBusy,
        editingTeacher,
        teacherSearch,
        filteredTeachers,
        teacherForm,
        templateForm,
        workspaceForm,
        init,
        loadSpaces,
        loadData,
        switchWorkspace,
        openManager,
        resetTeacherForm,
        editTeacher,
        saveTeacher,
        deleteTeacher,
        teacherExportUrl,
        templateExportUrl,
        workspaceExportUrl,
        importTeachers,
        importTemplates,
        selectTemplateForEdit,
        saveTemplateMetadata,
        clearTemplateForm,
        deleteTemplate,
        createTemplate,
        updateTemplateLayout,
        newWorkspace,
        editWorkspace,
        saveWorkspace,
        duplicateWorkspace,
        deleteWorkspace,
        importWorkspace,
        formatDate
    };
}
