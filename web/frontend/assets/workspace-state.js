const { ref, reactive, computed } = Vue;

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
                    <p class="manager-hint">Шаблоны хранятся на сервере и доступны с любого рабочего места.</p>
                    <div class="button-row"><a class="btn btn-secondary btn-small" :href="templateExportUrl" download>Экспорт JSON</a><label class="btn btn-secondary btn-small">Импорт JSON<input hidden type="file" accept=".json" @change="importTemplates"></label></div>
                  </div>
                  <div class="manager-list">
                    <article v-for="profile in layoutProfiles" :key="profile.id" class="manager-row" :class="{selected:selectedProfile===profile.name}" @click="selectTemplateForEdit(profile)">
                      <div><strong>{{ profile.name }}</strong><span>{{ profile.description || 'Без описания' }}</span><small>Изменён {{ formatDate(profile.updated_at) }}</small></div>
                      <button class="btn btn-danger btn-small" @click.stop="deleteTemplate(profile)">Удалить</button>
                    </article>
                    <div v-if="!layoutProfiles.length" class="empty-state">Шаблоны ещё не сохранены.</div>
                  </div>
                </section>
                <form class="manager-form" @submit.prevent="saveTemplateMetadata">
                  <h3>{{ templateForm.id ? 'Свойства шаблона' : 'Новый шаблон создаётся из текущей разметки' }}</h3>
                  <label>Название<input class="control" v-model.trim="templateForm.name" required></label>
                  <label>Описание<textarea class="control textarea" v-model.trim="templateForm.description"></textarea></label>
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
    const workspaces = ref([]), activeWorkspaceId = ref(localStorage.getItem('planner-workspace-id') || '');
    const teachers = ref([]), layoutProfiles = ref([]), selectedProfile = ref(''), profileName = ref('');
    const showTeachers = ref(false), managerOpen = ref(false), managerTab = ref('teachers');
    const teacherBusy = ref(false), editingTeacher = ref(false), teacherSearch = ref('');
    const teacherForm = reactive({id:null,short_name:'',full_name:'',position:'',rank:'',academic_degree:''});
    const templateForm = reactive({id:null,name:'',description:''});
    const workspaceForm = reactive({id:null,name:'',color:'#315EFB',description:'',schedule_start_date:'2026-02-10',schedule_end_date:'2026-06-30',is_default:false});
    const activeWorkspace = computed(() => workspaces.value.find(x => x.id === activeWorkspaceId.value) || null);
    const filteredTeachers = computed(() => {
        const q = teacherSearch.value.toLocaleLowerCase('ru');
        return q ? teachers.value.filter(t => `${t.short_name} ${t.full_name} ${t.position}`.toLocaleLowerCase('ru').includes(q)) : teachers.value;
    });
    const api = path => `/api/workspaces/${activeWorkspaceId.value}${path}`;
    const setTheme = () => document.documentElement.style.setProperty('--primary', activeWorkspace.value?.color || '#315EFB');
    const loadSpaces = async preferred => {
        const {data} = await axios.get('/api/workspaces'); workspaces.value = data;
        const exists = data.some(x => x.id === (preferred || activeWorkspaceId.value));
        activeWorkspaceId.value = exists ? (preferred || activeWorkspaceId.value) : (data.find(x => x.is_default)?.id || data[0]?.id || '');
        localStorage.setItem('planner-workspace-id', activeWorkspaceId.value); setTheme();
    };
    const loadData = async () => {
        if (!activeWorkspaceId.value) return;
        const [t,p] = await Promise.all([axios.get(api('/teachers')), axios.get(api('/templates'))]);
        teachers.value=t.data; layoutProfiles.value=p.data; selectedProfile.value=''; clearTemplateForm();
    };
    const switchWorkspace = async id => {
        if (!id) return; activeWorkspaceId.value=id; localStorage.setItem('planner-workspace-id',id); setTheme();
        resetTeacherForm(); await loadData(); if (onWorkspaceChanged) onWorkspaceChanged();
        addToast('Пространство выбрано', `Активно: ${activeWorkspace.value?.name || ''}`, 'success');
    };
    const init = async () => { try { await loadSpaces(); await loadData(); } catch(e) { addToast('Ошибка','Не удалось загрузить пространства.','error'); } };
    const openManager = tab => { managerTab.value=tab; managerOpen.value=true; if(tab==='spaces') editWorkspace(activeWorkspace.value); };
    const resetTeacherForm = () => { Object.assign(teacherForm,{id:null,short_name:'',full_name:'',position:'',rank:'',academic_degree:''}); editingTeacher.value=false; };
    const editTeacher = t => { Object.assign(teacherForm,t); editingTeacher.value=true; showTeachers.value=true; };
    const saveTeacher = async () => { teacherBusy.value=true; try { const url=teacherForm.id?api(`/teachers/${teacherForm.id}`):api('/teachers'); await axios[teacherForm.id?'put':'post'](url,teacherForm); resetTeacherForm(); await loadData(); await loadSpaces(activeWorkspaceId.value); addToast('Сохранено','Список преподавателей обновлён.','success'); } catch(e){ addToast('Ошибка',e.response?.data?.detail||'Не удалось сохранить запись.','error'); } finally { teacherBusy.value=false; } };
    const deleteTeacher = async t => { if(!confirm(`Удалить ${t.short_name}?`))return; await axios.delete(api(`/teachers/${t.id}`)); await loadData(); await loadSpaces(activeWorkspaceId.value); };
    const teacherExportUrl = format => api(`/teachers/export?format=${format}`);
    const templateExportUrl = computed(() => api('/templates/export'));
    const workspaceExportUrl = computed(() => activeWorkspaceId.value ? api('/export') : '#');
    const importFile = async (event,url,label) => { const file=event.target.files?.[0]; if(!file)return; const form=new FormData(); form.append('file',file); try { const {data}=await axios.post(url,form,{headers:{'Content-Type':'multipart/form-data'}}); await loadData(); await loadSpaces(activeWorkspaceId.value); addToast(label,`Добавлено: ${data.added ?? 1}, пропущено: ${data.skipped ?? 0}.`,'success'); } catch(e){ addToast('Ошибка импорта',e.response?.data?.detail||'Файл не импортирован.','error'); } finally { event.target.value=''; } };
    const importTeachers = e => importFile(e,api('/teachers/import?mode=append'),'Преподаватели импортированы');
    const importTemplates = e => importFile(e,api('/templates/import?mode=append'),'Шаблоны импортированы');
    const clearTemplateForm = () => Object.assign(templateForm,{id:null,name:'',description:''});
    const selectTemplateForEdit = p => { selectedProfile.value=p.name; Object.assign(templateForm,{id:p.id,name:p.name,description:p.description||''}); };
    const saveTemplateMetadata = async () => { if(!templateForm.id)return; await axios.put(api(`/templates/${templateForm.id}`),{name:templateForm.name,description:templateForm.description}); await loadData(); addToast('Шаблон сохранён','Название и описание обновлены.','success'); };
    const deleteTemplate = async p => { if(!confirm(`Удалить шаблон «${p.name}»?`))return; await axios.delete(api(`/templates/${p.id}`)); selectedProfile.value=''; clearTemplateForm(); await loadData(); };
    const createTemplate = async (name,description,layout) => { const {data}=await axios.post(api('/templates'),{name,description,layout}); await loadData(); selectedProfile.value=data.name; return data; };
    const updateTemplateLayout = async (id,layout,name,description) => { const {data}=await axios.put(api(`/templates/${id}`),{layout,name,description}); await loadData(); selectedProfile.value=data.name; return data; };
    const selectedTemplate = computed(() => layoutProfiles.value.find(x => x.id === selectedProfile.value || x.name === selectedProfile.value) || null);
    const newWorkspace = () => Object.assign(workspaceForm,{id:null,name:'',color:'#315EFB',description:'',schedule_start_date:'2026-02-10',schedule_end_date:'2026-06-30',is_default:false});
    const editWorkspace = s => { if(!s)return newWorkspace(); Object.assign(workspaceForm,{id:s.id,name:s.name,color:s.color,description:s.description||'',schedule_start_date:s.settings?.schedule_start_date||'2026-02-10',schedule_end_date:s.settings?.schedule_end_date||'2026-06-30',is_default:!!s.is_default}); };
    const saveWorkspace = async () => { const payload={name:workspaceForm.name,color:workspaceForm.color,description:workspaceForm.description,is_default:workspaceForm.is_default,settings:{schedule_start_date:workspaceForm.schedule_start_date,schedule_end_date:workspaceForm.schedule_end_date}}; try { const {data}=workspaceForm.id?await axios.put(`/api/workspaces/${workspaceForm.id}`,payload):await axios.post('/api/workspaces',payload); await loadSpaces(data.id); await loadData(); editWorkspace(activeWorkspace.value); addToast('Пространство сохранено','Настройки применены.','success'); } catch(e){ addToast('Ошибка',e.response?.data?.detail||'Не удалось сохранить пространство.','error'); } };
    const duplicateWorkspace = async () => { const {data}=await axios.post(api('/duplicate'),{}); await loadSpaces(data.id); await loadData(); editWorkspace(activeWorkspace.value); };
    const deleteWorkspace = async () => { if(!confirm(`Удалить пространство «${activeWorkspace.value?.name}» со всеми данными?`))return; try { await axios.delete(`/api/workspaces/${activeWorkspaceId.value}`); await loadSpaces(); await loadData(); editWorkspace(activeWorkspace.value); } catch(e){ addToast('Удаление',e.response?.data?.detail||'Не удалось удалить пространство.','error'); } };
    const importWorkspace = async e => { const file=e.target.files?.[0]; if(!file)return; const form=new FormData(); form.append('file',file); try { const {data}=await axios.post('/api/workspaces/import',form,{headers:{'Content-Type':'multipart/form-data'}}); await loadSpaces(data.id); await loadData(); editWorkspace(activeWorkspace.value); addToast('Пространство импортировано',data.name,'success'); } catch(err){ addToast('Ошибка импорта',err.response?.data?.detail||'Файл не импортирован.','error'); } finally { e.target.value=''; } };
    const formatDate = value => value ? new Date(value).toLocaleString('ru-RU',{dateStyle:'short',timeStyle:'short'}) : '—';
    return {workspaces,activeWorkspaceId,activeWorkspace,teachers,layoutProfiles,selectedProfile,selectedTemplate,profileName,showTeachers,managerOpen,managerTab,teacherBusy,editingTeacher,teacherSearch,filteredTeachers,teacherForm,templateForm,workspaceForm,init,switchWorkspace,openManager,resetTeacherForm,editTeacher,saveTeacher,deleteTeacher,teacherExportUrl,templateExportUrl,workspaceExportUrl,importTeachers,importTemplates,selectTemplateForEdit,saveTemplateMetadata,clearTemplateForm,deleteTemplate,createTemplate,updateTemplateLayout,newWorkspace,editWorkspace,saveWorkspace,duplicateWorkspace,deleteWorkspace,importWorkspace,formatDate};
}
