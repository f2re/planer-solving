const { ref, reactive, computed } = Vue;

export function installPlatformMarkup() {
    const topbar = document.querySelector('.topbar');
    if (topbar && !document.querySelector('.operations-button')) {
        topbar.insertAdjacentHTML('beforeend', `
          <button v-if="platformAccess" type="button" class="btn btn-primary btn-small operations-button" @click="openOperations('overview')">
            Центр операций
          </button>
          <button v-if="currentUser && !currentUser.bootstrap" type="button" class="user-chip" @click="openOperations('profile')" :title="currentUser.role">
            <span>{{ userInitials }}</span><b>{{ currentUser.display_name }}</b>
          </button>`);
    }

    const managerToolbars = document.querySelectorAll('.manager-toolbar');
    if (managerToolbars[0]) {
        const label = managerToolbars[0].querySelector('label.btn');
        if (label) {
            label.outerHTML = '<button type="button" class="btn btn-secondary btn-small" @click="openOperations(\'import\', \'teachers\')">Мастер импорта</button>';
        }
    }
    if (managerToolbars[1]) {
        const label = managerToolbars[1].querySelector('label.btn');
        if (label) {
            label.outerHTML = '<button type="button" class="btn btn-secondary btn-small" @click="openOperations(\'import\', \'templates\')">Мастер импорта</button>';
        }
    }

    const app = document.querySelector('#app');
    if (!app || document.querySelector('.platform-shell')) return;
    app.insertAdjacentHTML('beforeend', `
      <div class="platform-shell">
        <div v-if="authModalOpen" class="auth-backdrop">
          <section class="auth-card card" role="dialog" aria-modal="true">
            <div class="auth-symbol">П</div>
            <h2>{{ authStatus.bootstrap_required ? 'Первоначальная настройка' : 'Вход в Planner Solving' }}</h2>
            <p v-if="authStatus.bootstrap_required">Создайте первого администратора. После этого изменения будут защищены ролями и записываться в журнал.</p>
            <p v-else>Введите данные локального пользователя.</p>
            <form @submit.prevent="submitAuth" class="auth-form">
              <label>Логин<input class="control" autocomplete="username" v-model.trim="authForm.username" required></label>
              <label v-if="authStatus.bootstrap_required">Отображаемое имя<input class="control" v-model.trim="authForm.display_name" required></label>
              <label>Пароль<input class="control" type="password" autocomplete="current-password" v-model="authForm.password" minlength="10" required></label>
              <button class="btn btn-primary" :disabled="authBusy">{{ authBusy ? 'Проверяем…' : authStatus.bootstrap_required ? 'Создать администратора' : 'Войти' }}</button>
            </form>
            <p v-if="authStatus.bootstrap_required" class="auth-note">До завершения настройки доступ разрешён только локальному администратору этого сервера.</p>
          </section>
        </div>

        <div v-if="operationsOpen" class="operations-backdrop" @click.self="closeOperations">
          <section class="operations-modal card" role="dialog" aria-modal="true" aria-label="Центр операций">
            <aside class="operations-nav">
              <div class="operations-brand"><span>П</span><div><strong>Центр операций</strong><small>{{ activeWorkspace?.name }}</small></div></div>
              <button v-for="tab in visibleOperationTabs" :key="tab.id" :class="{active:operationsTab===tab.id}" @click="selectOperationsTab(tab.id)">
                <span>{{ tab.icon }}</span><div><b>{{ tab.name }}</b><small>{{ tab.hint }}</small></div>
              </button>
              <div class="operations-user" v-if="currentUser"><span>{{ userInitials }}</span><div><b>{{ currentUser.display_name }}</b><small>{{ roleLabel(currentUser.role) }}</small></div></div>
            </aside>

            <main class="operations-content">
              <header class="operations-header">
                <div><h2>{{ activeOperationTab?.name }}</h2><p>{{ activeOperationTab?.description }}</p></div>
                <button type="button" class="modal-close" @click="closeOperations" aria-label="Закрыть">×</button>
              </header>

              <div class="operations-scroll">
                <section v-if="operationsTab==='overview'" class="operations-section">
                  <div class="ops-metrics">
                    <article><span>Запуски</span><strong>{{ operationsSummary.runs?.total || 0 }}</strong><small>{{ operationsSummary.runs?.attention || 0 }} требуют внимания</small></article>
                    <article><span>Импорт</span><strong>{{ operationsSummary.imports?.pending || 0 }}</strong><small>ожидают подтверждения</small></article>
                    <article><span>Шаблоны</span><strong>{{ operationsSummary.templates?.total || 0 }}</strong><small>среднее качество {{ operationsSummary.templates?.average_quality || 0 }}%</small></article>
                  </div>
                  <div class="ops-actions">
                    <button class="action-card" @click="openOperations('import','teachers')"><span>⇩</span><div><b>Импортировать преподавателей</b><small>С предпросмотром и выбором конфликтов</small></div></button>
                    <button class="action-card" @click="selectOperationsTab('history')"><span>◷</span><div><b>История обработок</b><small>Исходники, отчёты и результаты</small></div></button>
                    <button class="action-card" @click="selectOperationsTab('templates')"><span>▦</span><div><b>Версии шаблонов</b><small>Сравнение, составные правила и откат</small></div></button>
                  </div>
                </section>

                <section v-else-if="operationsTab==='import'" class="operations-section import-wizard">
                  <div class="wizard-steps"><span :class="{active:importStep>=1}">1 · Файл</span><span :class="{active:importStep>=2}">2 · Сопоставление</span><span :class="{active:importStep>=3}">3 · Проверка</span><span :class="{active:importStep>=4}">4 · Готово</span></div>
                  <div v-if="!importJob" class="import-drop">
                    <div class="segmented"><button :class="{active:importKind==='teachers'}" @click="importKind='teachers'">Преподаватели</button><button :class="{active:importKind==='templates'}" @click="importKind='templates'">Шаблоны</button></div>
                    <label class="import-dropzone"><input hidden type="file" accept=".csv,.tsv,.txt,.json" @change="previewImport"><span>⇩</span><b>Выберите или перетащите файл</b><small>Данные не изменятся до подтверждения</small></label>
                  </div>
                  <template v-else>
                    <div class="import-summary"><div><b>{{ importJob.filename }}</b><small>{{ importJob.source?.rows?.length || 0 }} строк · {{ importJob.source?.encoding }}</small></div><a class="btn btn-secondary btn-small" :href="importReportUrl" download>Отчёт CSV</a><button class="btn btn-secondary btn-small" @click="resetImport">Другой файл</button></div>
                    <div v-if="importKind==='teachers'" class="mapping-grid">
                      <label v-for="field in importJob.teacher_fields" :key="field.id"><span>{{ field.name }}</span><select class="control" v-model="importMapping[field.id]" @change="recalculateImport"><option value="">Не использовать</option><option v-for="header in importJob.source.headers" :key="header" :value="header">{{ header }}</option></select></label>
                    </div>
                    <div class="import-counts"><span class="add">Добавится <b>{{ importJob.preview.counts?.add || 0 }}</b></span><span class="update">Обновится <b>{{ importJob.preview.counts?.update || 0 }}</b></span><span class="duplicate">Совпадений <b>{{ importJob.preview.counts?.duplicate || 0 }}</b></span><span class="conflict">Конфликтов <b>{{ (importJob.preview.counts?.conflict || 0) + (importJob.preview.counts?.invalid || 0) }}</b></span></div>
                    <div class="import-table-wrap"><table class="import-table"><thead><tr><th>№</th><th>Статус</th><th>Запись</th><th>Изменения</th><th>Действие</th></tr></thead><tbody><tr v-for="row in visibleImportRows" :key="row.row"><td>{{ row.row }}</td><td><span class="status-pill" :class="row.status">{{ importStatusLabel(row.status) }}</span></td><td><b>{{ importEntityName(row) }}</b><small>{{ row.message }}</small></td><td><div v-for="(change,key) in row.changes" :key="key" class="field-change"><span>{{ key }}</span><del>{{ change.before || '—' }}</del><ins>{{ change.after }}</ins></div><span v-if="!Object.keys(row.changes||{}).length">—</span></td><td><select class="control decision" v-model="importDecisions[row.row]"><option value="add">Добавить</option><option value="merge">Объединить</option><option value="replace">Заменить</option><option value="skip">Пропустить</option></select></td></tr></tbody></table></div>
                    <div class="import-footer"><span>Показано {{ visibleImportRows.length }} из {{ importJob.preview.rows.length }}</span><button v-if="canAdmin" class="btn btn-primary" :disabled="importBusy || importJob.status==='committed'" @click="commitImport">{{ importJob.status==='committed' ? 'Импорт применён' : 'Применить выбранные изменения' }}</button><span v-else class="permission-note">Подтвердить импорт может администратор.</span></div>
                  </template>
                </section>

                <section v-else-if="operationsTab==='history'" class="operations-section history-layout">
                  <div class="history-list"><button v-for="run in processingRuns" :key="run.id" :class="{active:selectedRun?.id===run.id}" @click="selectRun(run)"><span class="run-status" :class="run.status"></span><div><b>{{ formatOperationDate(run.created_at) }}</b><small>{{ run.lesson_count }} занятий · {{ run.source_count }} файлов</small></div><em>{{ run.status }}</em></button><div v-if="!processingRuns.length" class="empty-state">История пока пуста.</div></div>
                  <article v-if="selectedRun" class="run-details"><div class="run-hero"><div><span class="status-pill" :class="selectedRun.status">{{ selectedRun.status }}</span><h3>{{ formatOperationDate(selectedRun.created_at) }}</h3><p>{{ selectedRun.actor_name || 'Система' }}</p></div><div class="run-metrics"><span><b>{{ selectedRun.lesson_count }}</b>занятий</span><span><b>{{ selectedRun.warning_count }}</b>замечаний</span><span><b>{{ selectedRun.error_count }}</b>ошибок</span></div></div><h4>Исходные файлы</h4><div class="detail-list"><div v-for="file in selectedRun.files" :key="file.file_id"><b>{{ file.filename }}</b><small>{{ file.group_name }} · SHA-256 {{ file.checksum.slice(0,12) }}…</small></div></div><h4>Результаты</h4><div class="artifact-list"><a v-for="artifact in selectedRun.artifacts" :key="artifact.id" :href="'/api/download/'+artifact.filename" download><span>⇩</span><div><b>{{ artifact.filename }}</b><small>{{ formatBytes(artifact.size) }}</small></div></a></div></article>
                  <div v-else class="empty-state large">Выберите запуск слева.</div>
                </section>

                <section v-else-if="operationsTab==='templates'" class="operations-section templates-layout">
                  <div class="template-catalog"><button v-for="template in layoutProfiles" :key="template.id" :class="{active:selectedOperationsTemplate?.id===template.id}" @click="selectOperationsTemplate(template)"><div><b>{{ template.name }}</b><small>версия {{ template.current_revision }} · качество {{ Math.round(template.avg_quality||0) }}%</small></div><span>{{ template.composite?.length || 0 }} правил</span></button><div v-if="!layoutProfiles.length" class="empty-state">Шаблонов нет.</div></div>
                  <article v-if="selectedOperationsTemplate" class="template-workbench"><div class="template-score"><div><h3>{{ selectedOperationsTemplate.name }}</h3><p>{{ selectedOperationsTemplate.description || 'Без описания' }}</p></div><strong>{{ Math.round(selectedOperationsTemplate.avg_quality||0) }}%</strong></div><div class="template-tabs"><button :class="{active:templateWorkbenchTab==='revisions'}" @click="templateWorkbenchTab='revisions'">Версии</button><button :class="{active:templateWorkbenchTab==='composite'}" @click="templateWorkbenchTab='composite'">Правила листов</button></div><div v-if="templateWorkbenchTab==='revisions'" class="revision-list"><article v-for="revision in templateRevisions" :key="revision.id"><div><b>Версия {{ revision.revision_no }}</b><small>{{ formatOperationDate(revision.created_at) }} · {{ revision.actor_name }}</small><p>{{ revision.comment || 'Без комментария' }}</p></div><div class="revision-changes"><span v-for="change in revision.changes.slice(0,5)" :key="change.field">{{ change.field }}: {{ change.before ?? '—' }} → {{ change.after ?? '—' }}</span></div><button v-if="canOperate && revision.revision_no!==selectedOperationsTemplate.current_revision" class="btn btn-secondary btn-small" @click="restoreRevision(revision)">Восстановить</button></article></div><div v-else class="composite-editor"><p>Правила выбирают отдельную разметку по названию листа. Регулярное выражение необязательно.</p><article v-for="(rule,index) in compositeRules" :key="rule.id"><label>Название<input class="control" v-model.trim="rule.name"></label><label>Шаблон имени листа<input class="control" v-model.trim="rule.sheet_pattern" placeholder="Например: очная|заочная"></label><div class="button-row"><button class="btn btn-secondary btn-small" @click="useCurrentLayout(rule)">Взять текущую разметку</button><button class="btn btn-danger btn-small" @click="removeCompositeRule(index)">Удалить</button></div></article><button class="btn btn-secondary" @click="addCompositeRule">Добавить правило листа</button><button v-if="canOperate" class="btn btn-primary" @click="saveCompositeRules">Сохранить новой версией</button></div></article>
                  <div v-else class="empty-state large">Выберите шаблон слева.</div>
                </section>

                <section v-else-if="operationsTab==='users'" class="operations-section users-layout">
                  <div class="users-list"><article v-for="user in platformUsers" :key="user.id"><span class="user-avatar">{{ initials(user.display_name) }}</span><div><b>{{ user.display_name }}</b><small>{{ user.username }} · {{ roleLabel(user.role) }}</small></div><span class="status-pill" :class="user.is_active?'success':'disabled'">{{ user.is_active ? 'Активен' : 'Отключён' }}</span><button class="btn btn-secondary btn-small" @click="editPlatformUser(user)">Изменить</button></article></div><form class="user-form card" @submit.prevent="savePlatformUser"><h3>{{ userForm.id ? 'Изменение пользователя' : 'Новый пользователь' }}</h3><label>Логин<input class="control" v-model.trim="userForm.username" :disabled="!!userForm.id" required></label><label>Отображаемое имя<input class="control" v-model.trim="userForm.display_name" required></label><label>Роль<select class="control" v-model="userForm.role"><option value="admin">Администратор</option><option value="operator">Оператор</option><option value="viewer">Просмотр</option></select></label><label>{{ userForm.id ? 'Новый пароль, необязательно' : 'Пароль' }}<input class="control" type="password" v-model="userForm.password" :required="!userForm.id" minlength="10"></label><label v-if="userForm.id" class="check-row"><input type="checkbox" v-model="userForm.is_active"> Пользователь активен</label><div class="button-row"><button class="btn btn-primary">Сохранить</button><button type="button" class="btn btn-secondary" @click="resetUserForm">Очистить</button></div></form>
                </section>

                <section v-else-if="operationsTab==='audit'" class="operations-section audit-list"><article v-for="item in auditItems" :key="item.id"><span>{{ auditIcon(item.action) }}</span><div><b>{{ item.summary }}</b><small>{{ item.actor_name }} · {{ formatOperationDate(item.created_at) }}</small><code>{{ item.action }}</code></div></article><div v-if="!auditItems.length" class="empty-state">Журнал пока пуст.</div></section>

                <section v-else-if="operationsTab==='profile'" class="operations-section profile-section"><div class="profile-card"><span class="profile-avatar">{{ userInitials }}</span><h3>{{ currentUser?.display_name }}</h3><p>{{ currentUser?.username }} · {{ roleLabel(currentUser?.role) }}</p><button class="btn btn-secondary" @click="logout">Выйти</button></div></section>
              </div>
            </main>
          </section>
        </div>
      </div>`);
}

export function createPlatformState(addToast, workspace, schedule) {
    const authStatus = reactive({ authenticated: false, bootstrap_required: false, setup_access: false, user: null });
    const currentUser = ref(null);
    const authModalOpen = ref(false);
    const authBusy = ref(false);
    const authForm = reactive({ username: 'admin', display_name: 'Администратор', password: '' });
    const operationsOpen = ref(false);
    const operationsTab = ref('overview');
    const operationsSummary = ref({});
    const importKind = ref('teachers');
    const importJob = ref(null);
    const importStep = ref(1);
    const importBusy = ref(false);
    const importMapping = reactive({});
    const importDecisions = reactive({});
    const processingRuns = ref([]);
    const selectedRun = ref(null);
    const selectedOperationsTemplate = ref(null);
    const templateRevisions = ref([]);
    const templateWorkbenchTab = ref('revisions');
    const compositeRules = ref([]);
    const platformUsers = ref([]);
    const auditItems = ref([]);
    const userForm = reactive({ id: null, username: '', display_name: '', role: 'viewer', password: '', is_active: true });

    const tabs = [
        { id: 'overview', icon: '⌂', name: 'Обзор', hint: 'Состояние и действия', description: 'Главные показатели активного пространства.' },
        { id: 'import', icon: '⇩', name: 'Импорт', hint: 'Предпросмотр и конфликты', description: 'Безопасный импорт без записи до подтверждения.' },
        { id: 'history', icon: '◷', name: 'История', hint: 'Файлы и результаты', description: 'Все обработки, отчёты и сформированные файлы.' },
        { id: 'templates', icon: '▦', name: 'Шаблоны', hint: 'Версии и правила', description: 'История разметок, откат и составные шаблоны.' },
        { id: 'users', icon: '♙', name: 'Пользователи', hint: 'Роли и доступ', description: 'Локальные пользователи и разграничение прав.', adminOnly: true },
        { id: 'audit', icon: '≡', name: 'Журнал', hint: 'Кто и что изменил', description: 'Неизменяемая последовательность значимых действий.' },
        { id: 'profile', icon: '●', name: 'Профиль', hint: 'Текущая сессия', description: 'Данные текущего пользователя.' }
    ];
    const activeOperationTab = computed(() => tabs.find(tab => tab.id === operationsTab.value));
    const canAdmin = computed(() => currentUser.value?.role === 'admin' || currentUser.value?.bootstrap);
    const canOperate = computed(() => ['admin', 'operator'].includes(currentUser.value?.role) || currentUser.value?.bootstrap);
    const platformAccess = computed(() => Boolean(currentUser.value));
    const visibleOperationTabs = computed(() => tabs.filter(tab => !tab.adminOnly || canAdmin.value));
    const userInitials = computed(() => initials(currentUser.value?.display_name || '?'));
    const activeWorkspaceId = workspace.activeWorkspaceId;
    const activeWorkspace = workspace.activeWorkspace;
    const layoutProfiles = workspace.layoutProfiles;
    const visibleImportRows = computed(() => (importJob.value?.preview?.rows || []).slice(0, 300));
    const importReportUrl = computed(() => importJob.value ? `/api/workspaces/${activeWorkspaceId.value}/imports/${importJob.value.id}/report.csv` : '#');

    const initials = value => String(value || '?').split(/\s+/).filter(Boolean).slice(0, 2).map(part => part[0].toUpperCase()).join('');
    const roleLabel = role => ({ admin: 'Администратор', operator: 'Оператор', viewer: 'Просмотр' }[role] || role || '—');
    const formatOperationDate = value => value ? new Date(value).toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' }) : '—';
    const formatBytes = value => { const size=Number(value||0); if(size<1024)return `${size} Б`; if(size<1048576)return `${(size/1024).toFixed(1)} КБ`; return `${(size/1048576).toFixed(1)} МБ`; };
    const importStatusLabel = status => ({ add:'Новая', update:'Изменение', duplicate:'Совпадение', conflict:'Конфликт', invalid:'Ошибка' }[status] || status);
    const importEntityName = row => row.teacher?.full_name || row.template?.name || 'Не распознано';
    const auditIcon = action => action.includes('delete') ? '−' : action.includes('create') || action.includes('commit') ? '+' : action.includes('login') ? '→' : '•';

    async function refreshAuth() {
        const { data } = await axios.get('/api/auth/status');
        Object.assign(authStatus, data);
        currentUser.value = data.user;
        authModalOpen.value = data.bootstrap_required || (!data.authenticated && !data.setup_access);
        return data;
    }
    async function submitAuth() {
        authBusy.value = true;
        try {
            const url = authStatus.bootstrap_required ? '/api/auth/bootstrap' : '/api/auth/login';
            const payload = authStatus.bootstrap_required ? authForm : { username: authForm.username, password: authForm.password };
            await axios.post(url, payload);
            authForm.password = '';
            await refreshAuth();
            authModalOpen.value = false;
            addToast('Доступ разрешён', `Пользователь: ${currentUser.value?.display_name}`, 'success');
            return true;
        } catch (error) {
            addToast('Вход не выполнен', error.response?.data?.detail || 'Проверьте введённые данные.', 'error');
            return false;
        } finally { authBusy.value = false; }
    }
    async function logout() {
        await axios.post('/api/auth/logout');
        currentUser.value = null;
        operationsOpen.value = false;
        authModalOpen.value = true;
        await refreshAuth();
    }
    async function initAuth() { try { return await refreshAuth(); } catch(error) { addToast('Ошибка доступа','Не удалось проверить локальную сессию.','error'); return null; } }

    async function openOperations(tab='overview', kind=null) {
        if (kind) importKind.value = kind;
        operationsTab.value = tab;
        operationsOpen.value = true;
        await loadOperationTab(tab);
    }
    const closeOperations = () => { operationsOpen.value = false; };
    async function selectOperationsTab(tab) { operationsTab.value = tab; await loadOperationTab(tab); }
    async function loadOperationTab(tab) {
        if (!activeWorkspaceId.value) return;
        try {
            if (tab === 'overview') operationsSummary.value = (await axios.get('/api/operations/summary', { params: { workspace_id: activeWorkspaceId.value } })).data;
            if (tab === 'history') { processingRuns.value = (await axios.get(`/api/workspaces/${activeWorkspaceId.value}/runs`)).data.items; if(processingRuns.value[0]) await selectRun(processingRuns.value[0]); }
            if (tab === 'templates' && selectedOperationsTemplate.value) await selectOperationsTemplate(selectedOperationsTemplate.value);
            if (tab === 'users' && canAdmin.value) platformUsers.value = (await axios.get('/api/admin/users')).data.users;
            if (tab === 'audit') auditItems.value = (await axios.get(`/api/workspaces/${activeWorkspaceId.value}/audit`)).data.items;
        } catch(error) { addToast('Центр операций', error.response?.data?.detail || 'Не удалось загрузить данные.', 'error'); }
    }

    async function previewImport(event) {
        const file = event.target.files?.[0]; if(!file)return;
        importBusy.value=true; const form=new FormData(); form.append('file',file);
        try { const {data}=await axios.post(`/api/workspaces/${activeWorkspaceId.value}/imports/preview?kind=${importKind.value}`,form,{headers:{'Content-Type':'multipart/form-data'}}); importJob.value=data; importStep.value=3; Object.keys(importMapping).forEach(k=>delete importMapping[k]); Object.assign(importMapping,data.mapping||{}); Object.keys(importDecisions).forEach(k=>delete importDecisions[k]); for(const row of data.preview.rows||[]) importDecisions[row.row]=row.decision; }
        catch(error){addToast('Импорт',error.response?.data?.detail||'Файл не разобран.','error');}
        finally{importBusy.value=false;event.target.value='';}
    }
    async function recalculateImport() { if(!importJob.value)return; importBusy.value=true; try{const {data}=await axios.put(`/api/workspaces/${activeWorkspaceId.value}/imports/${importJob.value.id}/preview`,{mapping:{...importMapping}});importJob.value=data;Object.keys(importDecisions).forEach(k=>delete importDecisions[k]);for(const row of data.preview.rows||[])importDecisions[row.row]=row.decision;}catch(error){addToast('Сопоставление',error.response?.data?.detail||'Предпросмотр не обновлён.','error');}finally{importBusy.value=false;} }
    async function commitImport() { if(!importJob.value)return; importBusy.value=true; try{const {data}=await axios.post(`/api/workspaces/${activeWorkspaceId.value}/imports/${importJob.value.id}/commit`,{decisions:{...importDecisions}});importJob.value.status='committed';importStep.value=4;await workspace.loadData?.();await workspace.loadSpaces?.(activeWorkspaceId.value);addToast('Импорт применён',`Добавлено: ${data.added}, обновлено: ${data.updated}, пропущено: ${data.skipped}.`,'success');}catch(error){addToast('Импорт',error.response?.data?.detail||'Изменения не применены.','error');}finally{importBusy.value=false;} }
    function resetImport(){importJob.value=null;importStep.value=1;Object.keys(importMapping).forEach(k=>delete importMapping[k]);Object.keys(importDecisions).forEach(k=>delete importDecisions[k]);}

    async function selectRun(run){selectedRun.value=(await axios.get(`/api/workspaces/${activeWorkspaceId.value}/runs/${run.id}`)).data;}
    async function selectOperationsTemplate(template){selectedOperationsTemplate.value=template;templateRevisions.value=(await axios.get(`/api/workspaces/${activeWorkspaceId.value}/templates/${template.id}/revisions`)).data.items;compositeRules.value=JSON.parse(JSON.stringify(template.composite||[]));}
    async function restoreRevision(revision){if(!confirm(`Восстановить версию ${revision.revision_no}?`))return;const {data}=await axios.post(`/api/workspaces/${activeWorkspaceId.value}/templates/${selectedOperationsTemplate.value.id}/restore`,{revision_no:revision.revision_no});await workspace.loadData();await selectOperationsTemplate(data);addToast('Версия восстановлена',data.name,'success');}
    function addCompositeRule(){compositeRules.value.push({id:`rule-${Date.now()}`,name:`Правило ${compositeRules.value.length+1}`,sheet_pattern:'',layout:JSON.parse(JSON.stringify(schedule.currentLayout.value||selectedOperationsTemplate.value.layout))});}
    function removeCompositeRule(index){compositeRules.value.splice(index,1);}
    function useCurrentLayout(rule){rule.layout=JSON.parse(JSON.stringify(schedule.currentLayout.value||{}));addToast('Разметка скопирована','Правило использует текущие координаты.','success');}
    async function saveCompositeRules(){const {data}=await axios.put(`/api/workspaces/${activeWorkspaceId.value}/templates/${selectedOperationsTemplate.value.id}/profile`,{layout:selectedOperationsTemplate.value.layout,composite:compositeRules.value,fingerprint:schedule.currentFile.value?.analysis?.fingerprint||selectedOperationsTemplate.value.fingerprint,comment:'Изменены правила листов'});await workspace.loadData();await selectOperationsTemplate(data);addToast('Шаблон обновлён','Создана новая версия составного шаблона.','success');}

    function resetUserForm(){Object.assign(userForm,{id:null,username:'',display_name:'',role:'viewer',password:'',is_active:true});}
    function editPlatformUser(user){Object.assign(userForm,{id:user.id,username:user.username,display_name:user.display_name,role:user.role,password:'',is_active:Boolean(user.is_active)});}
    async function savePlatformUser(){try{if(userForm.id)await axios.put(`/api/admin/users/${userForm.id}`,{display_name:userForm.display_name,role:userForm.role,is_active:userForm.is_active,...(userForm.password?{password:userForm.password}:{})});else await axios.post('/api/admin/users',userForm);platformUsers.value=(await axios.get('/api/admin/users')).data.users;resetUserForm();addToast('Пользователь сохранён','Настройки доступа применены.','success');}catch(error){addToast('Пользователь',error.response?.data?.detail||'Не удалось сохранить пользователя.','error');}}

    return {authStatus,currentUser,authModalOpen,authBusy,authForm,operationsOpen,operationsTab,operationsSummary,importKind,importJob,importStep,importBusy,importMapping,importDecisions,processingRuns,selectedRun,selectedOperationsTemplate,templateRevisions,templateWorkbenchTab,compositeRules,platformUsers,auditItems,userForm,activeWorkspace,layoutProfiles,activeOperationTab,canAdmin,canOperate,platformAccess,visibleOperationTabs,userInitials,visibleImportRows,importReportUrl,initials,roleLabel,formatOperationDate,formatBytes,importStatusLabel,importEntityName,auditIcon,initAuth,submitAuth,logout,openOperations,closeOperations,selectOperationsTab,previewImport,recalculateImport,commitImport,resetImport,selectRun,selectOperationsTemplate,restoreRevision,addCompositeRule,removeCompositeRule,useCurrentLayout,saveCompositeRules,resetUserForm,editPlatformUser,savePlatformUser};
}
