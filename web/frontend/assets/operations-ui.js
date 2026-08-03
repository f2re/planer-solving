export function installOperationsMarkup() {
    const app = document.querySelector('#app');
    if (!app) return;

    const topbar = document.querySelector('.topbar');
    if (topbar && !document.querySelector('.user-menu')) {
        topbar.insertAdjacentHTML('beforeend', `
          <div v-if="currentUser" class="user-menu">
            <button type="button" class="user-chip" @click="openManager(canAdmin ? 'users' : 'history')">
              <span class="user-avatar">{{ userInitials }}</span>
              <span class="user-chip-text"><strong>{{ currentUser.display_name }}</strong><small>{{ currentUser.role_label }}</small></span>
            </button>
            <button type="button" class="btn btn-secondary btn-small logout-button" @click="logout">Выйти</button>
          </div>`);
    }

    if (!document.querySelector('.auth-gate')) {
        app.insertAdjacentHTML('beforeend', `
          <div v-if="authReady && !currentUser" class="auth-gate">
            <section class="auth-card card" role="dialog" aria-modal="true" aria-label="Вход в Planner Solving">
              <div class="auth-brand"><span class="brand-mark">П</span><div><strong>Planner Solving</strong><small>{{ setupRequired ? 'Первоначальная настройка' : 'Защищённый вход' }}</small></div></div>
              <div v-if="setupRequired" class="auth-content">
                <h1>Создайте администратора</h1>
                <p>Это единственный обязательный шаг. После него можно добавить операторов и пользователей только для просмотра.</p>
                <label>Логин<input class="control" v-model.trim="authForm.username" autocomplete="username" placeholder="admin"></label>
                <label>Имя в журнале<input class="control" v-model.trim="authForm.display_name" placeholder="Администратор"></label>
                <label>Пароль<input class="control" type="password" v-model="authForm.password" autocomplete="new-password"></label>
                <label>Повторите пароль<input class="control" type="password" v-model="authForm.password_confirm" autocomplete="new-password" @keyup.enter="bootstrap"></label>
                <button class="btn btn-primary auth-submit" :disabled="authBusy" @click="bootstrap">{{ authBusy ? 'Создаём…' : 'Создать и войти' }}</button>
              </div>
              <div v-else class="auth-content">
                <h1>Вход в систему</h1>
                <p>Действия операторов и изменения данных фиксируются в журнале.</p>
                <label>Логин<input class="control" v-model.trim="authForm.username" autocomplete="username"></label>
                <label>Пароль<input class="control" type="password" v-model="authForm.password" autocomplete="current-password" @keyup.enter="login"></label>
                <button class="btn btn-primary auth-submit" :disabled="authBusy" @click="login">{{ authBusy ? 'Проверяем…' : 'Войти' }}</button>
              </div>
              <div class="auth-security">Локальные пароли хранятся как PBKDF2-хэши. Сеанс защищён HttpOnly-cookie и CSRF-токеном.</div>
            </section>
          </div>`);
    }

    const spacesPanel = document.querySelector('.spaces-layout');
    if (spacesPanel?.hasAttribute('v-else')) {
        spacesPanel.removeAttribute('v-else');
        spacesPanel.setAttribute('v-else-if', "managerTab==='spaces'");
    }

    const tabs = document.querySelector('.manager-tabs');
    if (tabs && !document.querySelector('.operations-tabs-marker')) {
        tabs.insertAdjacentHTML('beforeend', `
          <span class="operations-tabs-marker" hidden></span>
          <button v-if="canOperate" :class="{active:managerTab==='imports'}" @click="managerTab='imports'">Импорт</button>
          <button :class="{active:managerTab==='history'}" @click="managerTab='history'">История <b>{{ historyRuns.length }}</b></button>
          <button v-if="canAdmin" :class="{active:managerTab==='users'}" @click="managerTab='users'">Пользователи <b>{{ users.length }}</b></button>
          <button v-if="canAdmin" :class="{active:managerTab==='audit'}" @click="managerTab='audit'">Журнал</button>`);
    }

    const modalContent = document.querySelector('.modal-content');
    if (modalContent && !document.querySelector('.operations-panels-marker')) {
        modalContent.insertAdjacentHTML('beforeend', `
          <span class="operations-panels-marker" hidden></span>

          <div v-if="managerTab==='imports'" class="operations-panel import-wizard">
            <header class="operations-header">
              <div><h3>Предварительный импорт</h3><p>Ни одна запись не изменится до последнего шага.</p></div>
              <button class="btn btn-secondary btn-small" @click="resetImport">Начать заново</button>
            </header>
            <div class="wizard-steps">
              <span :class="{active:importStep===1,done:importStep>1}">1 · Файл</span>
              <span :class="{active:importStep===2,done:importStep>2}">2 · Сопоставление</span>
              <span :class="{active:importStep===3,done:importStep>3}">3 · Проверка</span>
              <span :class="{active:importStep===4}">4 · Результат</span>
            </div>

            <section v-if="importStep===1" class="wizard-source">
              <div class="import-kind-grid">
                <label :class="{selected:importKind==='teachers'}"><input type="radio" v-model="importKind" value="teachers"><strong>Преподаватели</strong><span>CSV, TXT или JSON с ручным сопоставлением полей</span></label>
                <label :class="{selected:importKind==='templates'}"><input type="radio" v-model="importKind" value="templates"><strong>Шаблоны</strong><span>JSON с предварительным сравнением и ревизиями</span></label>
                <label v-if="canAdmin" :class="{selected:importKind==='workspace'}"><input type="radio" v-model="importKind" value="workspace"><strong>Пространство</strong><span>Полный переносимый пакет JSON</span></label>
              </div>
              <label class="wizard-dropzone">
                <input hidden type="file" :accept="importKind==='teachers' ? '.csv,.txt,.json' : '.json'" @change="previewImport">
                <span class="wizard-drop-icon">↥</span>
                <strong>{{ importBusy ? 'Читаем и анализируем…' : 'Выберите файл' }}</strong>
                <small>Сначала будет показан только предварительный результат.</small>
              </label>
            </section>

            <section v-else-if="importStep===2" class="wizard-review">
              <div class="source-summary">
                <div><span>Файл</span><strong>{{ importJob.filename }}</strong></div>
                <div><span>Строк</span><strong>{{ importJob.source.total_rows || 0 }}</strong></div>
                <div><span>Кодировка</span><strong>{{ importJob.metadata.encoding || 'JSON' }}</strong></div>
                <div><span>Заголовок</span><strong>{{ importJob.metadata.header_row ? 'строка ' + importJob.metadata.header_row : 'структура JSON' }}</strong></div>
              </div>
              <div v-if="importKind==='teachers'" class="mapping-grid">
                <label v-for="(label, field) in importJob.field_labels" :key="field"><span>{{ label }}</span><select class="control" v-model="importMapping[field]"><option value="">Не импортировать</option><option v-for="column in importJob.source.columns" :key="column" :value="column">{{ column }}</option></select></label>
              </div>
              <div class="preview-table-wrap">
                <table class="operations-table"><thead><tr><th>№</th><th v-for="column in importJob.source.columns" :key="column">{{ column }}</th></tr></thead><tbody><tr v-for="(row,index) in importJob.source.rows.slice(0,50)" :key="index"><td>{{ index+1 }}</td><td v-for="column in importJob.source.columns" :key="column">{{ row[column] }}</td></tr></tbody></table>
              </div>
              <div class="wizard-actions"><label>Режим<select class="control" v-model="importMode"><option value="append">Добавить и обновить</option><option value="replace">Полностью заменить набор</option></select></label><button class="btn btn-primary" :disabled="importBusy" @click="evaluateImport">Проверить результат</button></div>
            </section>

            <section v-else-if="importStep===3" class="wizard-review">
              <div class="import-summary-cards"><div v-for="action in ['add','update','conflict','skip','error']" :key="action" :class="'summary-'+action"><strong>{{ importJob.evaluation.summary?.[action] || 0 }}</strong><span>{{ importActionLabel(action) }}</span></div></div>
              <div class="preview-table-wrap tall"><table class="operations-table"><thead><tr><th>Строка</th><th>Данные</th><th>Состояние</th><th>Действие</th></tr></thead><tbody><tr v-for="row in importJob.evaluation.rows" :key="row.row_index" :class="'row-'+row.suggested_action"><td>{{ row.row_index+1 }}</td><td><strong>{{ row.record.full_name || row.record.name || '—' }}</strong><small>{{ row.record.position || row.record.description || '' }}</small></td><td><span class="operation-badge" :class="row.suggested_action">{{ importActionLabel(row.suggested_action) }}</span><small>{{ row.message }}</small></td><td><select class="control action-select" v-model="importDecisions[row.row_index]" :disabled="row.suggested_action==='error'"><option value="add">Добавить</option><option value="update">Обновить</option><option v-if="importKind==='teachers'" value="merge">Объединить</option><option value="skip">Пропустить</option></select></td></tr></tbody></table></div>
              <div class="wizard-actions"><a class="btn btn-secondary" :href="'/api/imports/'+importJob.id+'/report.csv'" download>Скачать отчёт CSV</a><button class="btn btn-primary" :disabled="importBusy" @click="commitImport">Подтвердить и записать</button></div>
            </section>

            <section v-else class="wizard-complete"><div class="complete-icon">✓</div><h3>Импорт завершён</h3><p>Все изменения записаны одной транзакцией и добавлены в журнал действий.</p><div class="button-row"><button class="btn btn-primary" @click="resetImport">Импортировать ещё</button><button class="btn btn-secondary" @click="managerTab=importKind==='templates'?'templates':'teachers'">Открыть данные</button></div></section>
          </div>

          <div v-if="managerTab==='history'" class="operations-panel history-panel">
            <header class="operations-header"><div><h3>История обработок</h3><p>Исходные файлы, разметка, проверки и результаты связаны с пространством.</p></div><button class="btn btn-secondary btn-small" @click="loadHistory">Обновить</button></header>
            <div class="history-layout">
              <section><div class="operations-filters"><input class="control" v-model.trim="historyQuery" placeholder="Файл, группа или сообщение" @keyup.enter="loadHistory"><select class="control" v-model="historyStatus" @change="loadHistory"><option value="">Все статусы</option><option value="success">Успешно</option><option value="warning">С замечаниями</option><option value="error">Ошибка</option></select></div><div class="history-list"><article v-for="run in historyRuns" :key="run.id" class="history-row" :class="{selected:selectedRun?.id===run.id}" @click="openHistoryRun(run)"><span class="history-status" :class="run.status"></span><div><strong>{{ new Date(run.started_at).toLocaleString('ru-RU') }}</strong><span>{{ run.message || 'Обработка расписаний' }}</span><small>{{ run.total_files }} файлов · {{ run.artifact_count }} результатов · {{ run.user_name || 'Система' }}</small></div></article><div v-if="!historyRuns.length" class="empty-state">История пока пуста.</div></div></section>
              <section class="history-detail"><div v-if="!selectedRun" class="empty-state">Выберите запуск слева.</div><template v-else><div class="history-detail-head"><div><span class="operation-badge" :class="selectedRun.status">{{ selectedRun.status }}</span><h3>{{ new Date(selectedRun.started_at).toLocaleString('ru-RU') }}</h3><p>{{ selectedRun.message }}</p></div><button v-if="canOperate" class="btn btn-primary btn-small" @click="reopenHistoryRun(selectedRun)">Повторить с этими настройками</button></div><div class="history-files"><article v-for="file in selectedRun.files" :key="file.id"><span class="status-dot" :class="file.status"></span><div><strong>{{ file.original_name }}</strong><span>{{ file.group_name }} · {{ file.lesson_count }} занятий</span><small>{{ file.message }}</small></div></article></div><div class="artifact-list"><a v-for="artifact in selectedRun.artifacts" :key="artifact.id" class="artifact-card" :href="historyArtifactUrl(artifact)" download><span>↓</span><div><strong>{{ artifact.kind==='weekly'?'Недельное расписание':'Общее расписание' }}</strong><small>{{ artifact.filename }} · {{ Math.round(artifact.size/1024) }} КБ</small></div></a></div></template></section>
            </div>
          </div>

          <div v-if="managerTab==='users' && canAdmin" class="operations-panel users-panel">
            <header class="operations-header"><div><h3>Пользователи и роли</h3><p>Администратор управляет данными, оператор обрабатывает файлы, роль «Просмотр» ничего не изменяет.</p></div><button class="btn btn-secondary btn-small" @click="loadUsers">Обновить</button></header>
            <div class="manager-grid"><section class="user-list"><article v-for="user in users" :key="user.id" class="manager-row" @click="editUser(user)"><div><strong>{{ user.display_name }}</strong><span>@{{ user.username }}</span><small>{{ ({admin:'Администратор',operator:'Оператор',viewer:'Просмотр'})[user.role] }} · {{ user.active ? 'активен' : 'отключён' }}</small></div><span class="operation-badge" :class="user.active?'success':'disabled'">{{ user.active?'Доступ разрешён':'Отключён' }}</span></article></section><form class="manager-form" @submit.prevent="saveUser"><h3>{{ userForm.id?'Изменение пользователя':'Новый пользователь' }}</h3><label v-if="!userForm.id">Логин<input class="control" v-model.trim="userForm.username" required></label><label>Отображаемое имя<input class="control" v-model.trim="userForm.display_name" required></label><label>Роль<select class="control" v-model="userForm.role"><option value="admin">Администратор</option><option value="operator">Оператор</option><option value="viewer">Просмотр</option></select></label><label>{{ userForm.id?'Новый пароль — необязательно':'Пароль' }}<input class="control" type="password" v-model="userForm.password" :required="!userForm.id"></label><label v-if="userForm.id" class="check-row"><input type="checkbox" v-model="userForm.active"> Доступ разрешён</label><div class="button-row"><button class="btn btn-primary" :disabled="usersBusy">Сохранить</button><button type="button" class="btn btn-secondary" @click="resetUserForm">Очистить</button></div></form></div>
          </div>

          <div v-if="managerTab==='audit' && canAdmin" class="operations-panel audit-panel">
            <header class="operations-header"><div><h3>Журнал действий</h3><p>Неизменяемая последовательность входов, импортов, правок, обработок и удалений.</p></div><button class="btn btn-secondary btn-small" @click="loadAudit">Обновить</button></header>
            <div class="operations-filters"><input class="control" v-model.trim="auditQuery" placeholder="Поиск по объекту или описанию" @keyup.enter="loadAudit"><select class="control" v-model="auditAction" @change="loadAudit"><option value="">Все действия</option><option value="create">Создание</option><option value="update">Изменение</option><option value="delete">Удаление</option><option value="commit">Импорт</option><option value="finish">Обработка</option><option value="login">Вход</option></select></div>
            <div class="audit-list"><article v-for="entry in auditEntries" :key="entry.id"><span class="audit-icon">{{ ({create:'+',update:'↻',delete:'×',commit:'⇩',finish:'✓',login:'→',logout:'←'})[entry.action] || '•' }}</span><div><strong>{{ entry.summary }}</strong><span>{{ entry.user_display_name || 'Система' }} · {{ entry.workspace_name || 'Без пространства' }}</span><small>{{ new Date(entry.created_at).toLocaleString('ru-RU') }} · {{ entry.entity_type }} {{ entry.entity_id || '' }}</small></div></article><div v-if="!auditEntries.length" class="empty-state">Записей не найдено.</div></div>
          </div>`);
    }

    const templateGrids = document.querySelectorAll('.manager-grid');
    const templateGrid = templateGrids[1];
    if (templateGrid && !document.querySelector('.template-revision-panel')) {
        templateGrid.insertAdjacentHTML('beforeend', `
          <section class="template-revision-panel">
            <header class="operations-header compact"><div><h3>Версии и варианты формата</h3><p>Каждая правка сохраняется отдельной ревизией. Откат также создаёт новую версию.</p></div><button class="btn btn-secondary btn-small" :disabled="!selectedTemplate" @click="loadTemplateRevisions">Обновить</button></header>
            <div v-if="!selectedTemplate" class="empty-state">Выберите шаблон в списке выше.</div>
            <template v-else>
              <div class="template-components"><article v-for="component in templateComponents" :key="component.id"><div><strong>{{ component.label }}</strong><span>{{ component.selector?.sheet_name || component.layout?.sheet_name || 'Любой лист' }}</span><small>{{ component.fingerprint?.signature ? 'Есть структурный отпечаток' : 'Без отпечатка' }}</small></div><button v-if="canOperate && templateComponents.length>1" class="btn btn-danger btn-small" @click="removeTemplateComponent(component)">Удалить</button></article></div>
              <div v-if="canOperate" class="learn-format-card"><div><strong>Обучить по открытому файлу</strong><p>Сохранит текущую разметку, лист и структурный отпечаток книги как ещё один вариант шаблона.</p></div><div class="learn-format-fields"><input class="control" v-if="!selectedTemplate" v-model.trim="learnForm.template_name" placeholder="Название шаблона"><input class="control" v-model.trim="learnForm.component_label" placeholder="Название варианта"><input class="control" v-model.trim="learnForm.comment" placeholder="Комментарий к ревизии"><button class="btn btn-primary" :disabled="!currentFile || revisionsBusy" @click="learnCurrentFormat">Сохранить текущий формат</button></div></div>
              <div class="revision-compare"><select class="control" v-model="compareFrom"><option v-for="revision in templateRevisions" :key="revision.id" :value="revision.id">Версия {{ revision.revision_number }} · {{ new Date(revision.created_at).toLocaleString('ru-RU') }}</option></select><span>→</span><select class="control" v-model="compareTo"><option v-for="revision in templateRevisions" :key="revision.id" :value="revision.id">Версия {{ revision.revision_number }} · {{ new Date(revision.created_at).toLocaleString('ru-RU') }}</option></select><button class="btn btn-secondary btn-small" @click="compareRevisions">Сравнить</button></div>
              <div v-if="revisionComparison" class="revision-diff"><div v-if="!revisionComparison.changes.length" class="empty-state">Различий нет.</div><article v-for="change in revisionComparison.changes.slice(0,200)" :key="change.path"><code>{{ change.path }}</code><span class="diff-before">{{ JSON.stringify(change.before) }}</span><span>→</span><span class="diff-after">{{ JSON.stringify(change.after) }}</span></article></div>
              <div class="revision-timeline"><article v-for="revision in templateRevisions" :key="revision.id"><span class="revision-number">{{ revision.revision_number }}</span><div><strong>{{ revision.comment || revision.source }}</strong><span>{{ revision.author_name || 'Система' }} · {{ new Date(revision.created_at).toLocaleString('ru-RU') }}</span><small>{{ revision.summary?.component_count || 1 }} вариантов · {{ revision.source }}</small></div><button v-if="canOperate && revision.id!==templateRevisions[0]?.id" class="btn btn-secondary btn-small" @click="rollbackRevision(revision)">Вернуть</button></article></div>
            </template>
          </section>`);
    }

    // Role-aware visibility for the existing management interface.
    const teacherGrid = templateGrids[0];
    teacherGrid?.querySelector('.manager-form')?.setAttribute('v-if', 'canAdmin');
    teacherGrid?.querySelectorAll('.manager-row .button-row').forEach(node => node.setAttribute('v-if', 'canAdmin'));
    templateGrid?.querySelector('.manager-form')?.setAttribute('v-if', 'canOperate');
    templateGrid?.querySelectorAll('.btn-danger').forEach(node => node.setAttribute('v-if', 'canOperate'));
    spacesPanel?.querySelector('.manager-form')?.setAttribute('v-if', 'canAdmin');

    const directImportLabels = document.querySelectorAll('.manager-toolbar label.btn');
    directImportLabels.forEach(label => label.style.display = 'none');

    const uploadCard = document.querySelector('.upload-card');
    uploadCard?.setAttribute('v-if', 'canOperate');
    const teacherCard = document.querySelector('.teacher-card');
    teacherCard?.setAttribute('v-if', 'canAdmin');
}
