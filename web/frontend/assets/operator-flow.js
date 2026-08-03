const FLOW_READY = 'operatorFlowReady';

function text(selector, value) {
    const node = document.querySelector(selector);
    if (node) node.textContent = value;
    return node;
}

function insertOnce(target, position, marker, html) {
    if (!target || document.querySelector(marker)) return;
    target.insertAdjacentHTML(position, html);
}

/**
 * Нормализует исходный статический шаблон до монтирования Vue.
 *
 * Прежний интерфейс последовательно наращивался несколькими DOM-модулями и
 * сохранил формулировки старой блокирующей модели. Этот слой не меняет
 * предметную логику: он собирает действия оператора в один понятный маршрут и
 * использует уже существующие методы состояния приложения.
 */
export function installOperatorFlowMarkup() {
    if (document.documentElement.dataset[FLOW_READY] === '1') return;
    document.documentElement.dataset[FLOW_READY] = '1';
    document.title = 'Planner Solving — рабочее место оператора';

    text('.topbar .version', 'Рабочее место оператора');
    text('.upload-header .page-title', 'Сформировать расписание');
    text(
        '.upload-header .page-lead',
        'Загрузите книги расписаний. Система сама выберет безопасную разметку, сформирует результат из пригодных данных и покажет всё, что стоит уточнить. Любой файл можно исправить на месте без повторной загрузки остальных.'
    );
    text('.dropzone h2', 'Добавить файлы расписаний');
    text('.dropzone p', 'Можно выбрать несколько книг с разной структурой и оформлением.');

    const chips = document.querySelectorAll('.steps .step-chip');
    if (chips[0]) chips[0].textContent = '1  Исходные файлы';
    if (chips[1]) chips[1].textContent = '2  Проверка и исправление';
    if (chips[2]) chips[2].textContent = '3  Готовый результат';

    const uploadCard = document.querySelector('.upload-card');
    insertOnce(uploadCard, 'beforeend', '.operator-principles', `
      <div class="operator-principles" aria-label="Принципы обработки">
        <article><span>1</span><div><b>Автоматика сначала</b><small>Система применяет лучший безопасный вариант без лишних вопросов.</small></div></article>
        <article><span>2</span><div><b>Ничего не блокируется</b><small>Пригодные данные попадут в результат, сомнительные останутся доступными для уточнения.</small></div></article>
        <article><span>3</span><div><b>Правка на месте</b><small>Файл, разметка, календарь и назначения исправляются в текущем сеансе.</small></div></article>
      </div>`);

    const workflow = document.querySelector('.workflow-grid');
    insertOnce(workflow, 'beforebegin', '.operator-readiness', `
      <section class="operator-readiness" aria-label="Готовность результата">
        <div class="readiness-copy">
          <span class="eyebrow">Текущий сеанс</span>
          <strong>{{ enabledFiles.length }} {{ enabledFiles.length === 1 ? 'файл включён' : 'файлов включено' }}</strong>
          <small>
            {{ enabledFiles.filter(file => (validations[file.file_id]?.report?.lesson_count || 0) > 0).length }} уже дают занятия.
            Файлы без найденных занятий останутся в отчёте и доступны для исправления.
          </small>
        </div>
        <div class="readiness-metrics">
          <span><b>{{ checkedFilesCount }}</b><small>пересчитано</small></span>
          <span><b>{{ enabledFiles.filter(file => (validations[file.file_id]?.report?.unknown_teacher_lessons || 0) > 0).length }}</b><small>нужно назначить</small></span>
          <span><b>{{ attentionIssues.length }}</b><small>решений показано</small></span>
        </div>
        <div class="operator-primary-actions">
          <label class="btn btn-secondary operator-add-files" :class="{disabled:fileMutationBusy}">
            Добавить файлы
            <input id="session-add-files" hidden type="file" multiple accept=".xlsx,.xlsm" :disabled="fileMutationBusy" @change="appendSessionFiles">
          </label>
          <button type="button" class="btn btn-primary operator-generate" @click="generate" :disabled="generateBusy || fileMutationBusy || !canGenerate">
            {{ generateBusy ? 'Формируем…' : 'Сформировать результат' }}
          </button>
        </div>
      </section>
      <div v-if="lastRemovedFile" class="session-undo" role="status">
        <div><b>Файл убран из сеанса</b><small>{{ lastRemovedFile.file.filename }} · разметка и группа сохранены для отмены</small></div>
        <button type="button" class="btn btn-secondary btn-small" :disabled="fileMutationBusy" @click="undoRemoveSessionFile">Вернуть файл</button>
        <button type="button" class="session-undo-close" aria-label="Скрыть сообщение" @click="clearRemovedFileUndo">×</button>
      </div>
      <section class="attention-queue" aria-label="Решения по замечаниям">
        <header class="attention-header">
          <div>
            <span class="eyebrow">Контроль решений</span>
            <strong>{{ attentionIssues.length ? 'Есть решения, которые можно уточнить' : 'Без обязательных действий' }}</strong>
            <small v-if="attentionIssues.length">Система уже выбрала безопасный вариант для каждого пункта. Ручная правка необязательна.</small>
            <small v-else>Проверьте файлы, чтобы увидеть принятые системой решения до формирования.</small>
          </div>
          <button type="button" class="btn btn-secondary btn-small" :disabled="validateBusy || !enabledFiles.length" @click="validateAll">
            {{ validateBusy ? 'Проверяем…' : 'Проверить все файлы' }}
          </button>
        </header>
        <div v-if="attentionIssues.length" class="attention-list">
          <article v-for="issue in attentionIssues.slice(0,8)" :key="issue.file_id + ':' + issue.code + ':' + issue.message" class="attention-item" :class="issue.severity">
            <span class="attention-dot"></span>
            <div class="attention-copy">
              <div class="attention-meta"><b>{{ issue.filename }}</b><span>{{ issue.scope === 'teacher' ? 'Преподаватель' : issue.scope === 'calendar' ? 'Календарь' : issue.scope === 'range' ? 'Разметка' : issue.scope === 'sheet' ? 'Лист' : 'Файл' }}</span></div>
              <strong>{{ issue.message }}</strong>
              <p><b>По умолчанию:</b> {{ issue.default_decision }}</p>
              <small>{{ issue.impact }}</small>
            </div>
            <button
              type="button"
              class="btn btn-secondary btn-small"
              @click="issue.scope === 'teacher' ? openTeacherMapping(issue) : openAttentionIssue(issue)"
            >
              {{ issue.scope === 'teacher' ? 'Назначить преподавателей' : (issue.action?.label || 'Показать файл') }}
            </button>
          </article>
          <p v-if="attentionIssues.length > 8" class="attention-more">Ещё решений: {{ attentionIssues.length - 8 }}. Они доступны в соответствующих файлах и итоговом отчёте.</p>
        </div>
      </section>`);

    const groupInput = document.querySelector('.file-item .group-input');
    insertOnce(groupInput, 'afterend', '.file-resolution-state', `
      <div class="file-resolution-state">
        <span v-if="validations[file.file_id]?.report?.lesson_count" class="resolved">
          {{ validations[file.file_id].report.lesson_count }} занятий найдено
        </span>
        <span v-else-if="validations[file.file_id]" class="attention">Нужно указать область занятий</span>
        <span v-else class="neutral">Будет проверено автоматически</span>
      </div>
      <div class="file-session-actions" @click.stop>
        <label class="file-action" :class="{disabled:fileMutationBusy}">
          {{ mutatingFileId === file.file_id ? 'Заменяем…' : 'Заменить' }}
          <input hidden type="file" accept=".xlsx,.xlsm" :disabled="fileMutationBusy" @change="replaceSessionFile(file.file_id,$event)">
        </label>
        <button type="button" class="file-action remove" :disabled="fileMutationBusy" @click.stop="removeSessionFile(file)">Убрать</button>
      </div>`);

    const validateButton = document.querySelector('.settings-section .button-stack .btn-primary');
    if (validateButton) validateButton.textContent = 'Пересчитать этот файл';
    const previewButton = document.querySelector('.settings-section .button-stack .btn-secondary');
    if (previewButton) previewButton.textContent = 'Обновить рабочий лист';

    const bottomNote = document.querySelector('.bottom-note');
    if (bottomNote) {
        bottomNote.textContent = 'Результат создаётся из пригодных данных. Спорные решения сохраняются в отчёте и остаются доступными для исправления.';
    }
    const bottomPrimary = document.querySelector('.bottom-actions .btn-primary');
    if (bottomPrimary) {
        bottomPrimary.innerHTML = "{{ generateBusy ? 'Формируем…' : 'Сформировать результат' }}";
        bottomPrimary.setAttribute(':disabled', 'generateBusy || fileMutationBusy || !enabledFiles.length');
    }

    const resultTitle = document.querySelector('.result-card .page-title');
    if (resultTitle) resultTitle.textContent = 'Результат сформирован';
    const resultLead = document.querySelector('.result-card .page-lead');
    insertOnce(resultLead, 'afterend', '.result-next-step', `
      <p class="result-next-step">Скачайте готовые файлы или вернитесь к любому исходнику: текущий сеанс и все ручные правки сохранены.</p>`);

    const resultFile = document.querySelector('.result-file');
    insertOnce(resultFile, 'beforeend', '.result-file-action', `
      <button
        v-if="detail.file_id && (detail.status !== 'success' || !detail.used || detail.action_count)"
        type="button"
        class="btn btn-secondary btn-small result-file-action"
        @click="step=2; selectFile(detail.file_id)"
      >Открыть и уточнить</button>`);

    const resultActions = document.querySelector('.result-card > .button-row');
    insertOnce(resultActions, 'afterbegin', '.return-to-editor', `
      <button type="button" class="btn btn-secondary return-to-editor" @click="step=2">Вернуться к проверке</button>`);

    const warningTitle = document.querySelector('.warning-box > strong');
    if (warningTitle) warningTitle.textContent = 'Что система решила автоматически';

    const appRoot = document.querySelector('#app');
    insertOnce(appRoot, 'beforeend', '.teacher-mapping-backdrop', `
      <div
        v-if="teacherMappingOpen"
        class="modal-backdrop teacher-mapping-backdrop"
        role="presentation"
        @click.self="closeTeacherMapping"
      >
        <section class="teacher-mapping-dialog" role="dialog" aria-modal="true" aria-labelledby="teacher-mapping-title">
          <header class="teacher-mapping-header">
            <div>
              <span class="eyebrow">Ручное решение</span>
              <h2 id="teacher-mapping-title">Назначить преподавателей</h2>
              <p>{{ currentMappingFile?.filename }} · назначения действуют для этого файла и сохраняются в истории обработки.</p>
            </div>
            <button type="button" class="modal-close" aria-label="Закрыть" @click="closeTeacherMapping">×</button>
          </header>
          <div class="teacher-mapping-default">
            <b>Без выбора:</b> занятие останется в разделе «Не назначен» и не будет потеряно.
          </div>
          <label class="teacher-mapping-search">
            <span>Найти дисциплину или назначение</span>
            <input v-model.trim="teacherMappingSearch" class="control" type="search" placeholder="Начните вводить название">
          </label>
          <div class="teacher-mapping-list">
            <article v-for="subject in filteredMappingSubjects" :key="subject" class="teacher-mapping-row">
              <div><strong>{{ subject }}</strong><small>Все нераспознанные занятия этой дисциплины в выбранном файле</small></div>
              <select v-model="teacherMappingDraft[subject]" class="control">
                <option value="">Не назначен — безопасное значение</option>
                <option v-for="teacher in teacherMappingOptions" :key="teacher.id" :value="teacher.short_name">
                  {{ teacher.full_name || teacher.short_name }}{{ teacher.position ? ' · ' + teacher.position : '' }}
                </option>
              </select>
            </article>
            <p v-if="!filteredMappingSubjects.length" class="teacher-mapping-empty">По запросу ничего не найдено.</p>
          </div>
          <footer class="teacher-mapping-footer">
            <span>После применения файл будет пересчитан. Остальные книги и их ручные правки не изменятся.</span>
            <div>
              <button type="button" class="btn btn-secondary" :disabled="teacherMappingBusy" @click="closeTeacherMapping">Отмена</button>
              <button type="button" class="btn btn-primary" :disabled="teacherMappingBusy" @click="saveTeacherMapping">
                {{ teacherMappingBusy ? 'Пересчитываем…' : 'Применить назначения' }}
              </button>
            </div>
          </footer>
        </section>
      </div>`);

    const toastStack = document.querySelector('.toast-stack');
    toastStack?.setAttribute('aria-live', 'polite');
    toastStack?.setAttribute('aria-relevant', 'additions');
}

/**
 * Добавляет только общесистемные клавиатурные действия и фокусировку. Все
 * предметные операции по-прежнему выполняются Vue-состоянием приложения.
 */
export function installOperatorFlowRuntime() {
    const root = document.querySelector('#app');
    if (!root || root.dataset.operatorRuntime === '1') return;
    root.dataset.operatorRuntime = '1';

    document.addEventListener('keydown', event => {
        const modifier = event.metaKey || event.ctrlKey;
        const target = event.target;
        const editing = target instanceof HTMLInputElement
            || target instanceof HTMLTextAreaElement
            || target instanceof HTMLSelectElement
            || target?.isContentEditable;

        if (modifier && event.key.toLowerCase() === 'o' && !editing) {
            const input = document.querySelector('#session-add-files')
                || document.querySelector('#schedule-files');
            if (input && !input.disabled) {
                event.preventDefault();
                input.click();
            }
            return;
        }

        if (modifier && event.key === 'Enter' && !editing) {
            const button = document.querySelector('.operator-generate:not(:disabled), .bottom-actions .btn-primary:not(:disabled)');
            if (button) {
                event.preventDefault();
                button.click();
            }
            return;
        }

        if (event.key === 'Escape' && !editing) {
            const close = document.querySelector(
                '.teacher-mapping-backdrop .modal-close, '
                + '.template-save-backdrop .template-save-actions .btn-secondary, '
                + '.operations-backdrop .modal-close, '
                + '.modal-backdrop .modal-close'
            );
            close?.click();
        }
    });

    const observer = new MutationObserver(records => {
        for (const record of records) {
            for (const node of record.addedNodes) {
                if (!(node instanceof HTMLElement)) continue;
                const heading = node.matches('.result-card')
                    ? node.querySelector('h1')
                    : node.querySelector?.('.result-card h1');
                if (heading) {
                    heading.setAttribute('tabindex', '-1');
                    requestAnimationFrame(() => heading.focus({ preventScroll: false }));
                    return;
                }
            }
        }
    });
    observer.observe(root, { childList: true, subtree: true });
}
