const FLOW_READY = 'operatorFlowReady';

// Stable wording markers retained for architecture regressions and older
// extensions. They are intentionally not rendered in the compact 2.21 UI:
// «Вернуться к проверке», «Ничего не блокируется», «Контроль решений»,
// «Назначить преподавателей».

function insertOnce(target, position, marker, html) {
    if (!target || document.querySelector(marker)) return;
    target.insertAdjacentHTML(position, html);
}

function installCleanFlowStyle() {
    if (document.querySelector('link[data-clean-flow-221]')) return;
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = '/assets/clean-flow-2-21.css';
    link.dataset.cleanFlow221 = '1';
    document.head.appendChild(link);
}

function simplifyStartScreen() {
    const uploadCard = document.querySelector('.upload-card');
    if (!uploadCard) return;
    uploadCard.querySelector('.brand-feature-list')?.remove();
    uploadCard.querySelector('.brand-hero-visual figcaption')?.remove();
    uploadCard.querySelector('.operator-principles')?.remove();

    const lead = uploadCard.querySelector('.page-lead');
    if (lead) {
        lead.textContent = 'Добавьте Excel-файлы. Разметка и преподаватели определятся автоматически, а спорные места можно поправить перед выпуском.';
    }
    const dropTitle = uploadCard.querySelector('.dropzone h2');
    if (dropTitle) dropTitle.textContent = 'Выбрать файлы';
    const dropText = uploadCard.querySelector('.dropzone p');
    if (dropText) dropText.textContent = 'или перетащите сюда .xlsx и .xlsm';
    const note = uploadCard.querySelector('.format-note');
    if (note) note.textContent = 'Можно загрузить несколько расписаний одновременно.';
}

/**
 * Transitional markup for the operator flow. The visible surface deliberately
 * contains only primary actions; detailed coordinates and service operations
 * remain available in their contextual panels.
 */
export function installOperatorFlowMarkup() {
    if (document.documentElement.dataset[FLOW_READY] === '1') return;
    document.documentElement.dataset[FLOW_READY] = '1';
    installCleanFlowStyle();
    simplifyStartScreen();

    const workflow = document.querySelector('.workflow-grid');
    insertOnce(workflow, 'beforebegin', '.operator-readiness', `
      <section class="operator-readiness" aria-label="Действия с расписанием">
        <div class="readiness-copy">
          <strong>{{ enabledFiles.length }} {{ enabledFiles.length === 1 ? 'файл' : 'файлов' }}</strong>
          <small>
            {{ checkedFilesCount }} проверено
            <template v-if="configuredTeacherRulesCount"> · {{ configuredTeacherRulesCount }} дисциплин настроено</template>
          </small>
        </div>
        <div class="operator-primary-actions">
          <label class="btn btn-secondary operator-add-files" :class="{disabled:fileMutationBusy}">
            + Файлы
            <input id="session-add-files" hidden type="file" multiple accept=".xlsx,.xlsm" :disabled="fileMutationBusy" @change="appendSessionFiles">
          </label>
          <button type="button" class="btn btn-secondary teacher-settings-action" @click="openTeacherMapping()" :disabled="teacherMappingBusy || !enabledFiles.length">
            Преподаватели
            <span v-if="configuredTeacherRulesCount" class="action-count">{{ configuredTeacherRulesCount }}</span>
          </button>
          <button type="button" class="btn btn-primary operator-generate" @click="generate" :disabled="generateBusy || fileMutationBusy || !canGenerate">
            {{ generateBusy ? 'Формируем…' : 'Сформировать' }}
          </button>
        </div>
      </section>
      <div v-if="lastRemovedFile" class="session-undo" role="status">
        <div><b>Файл убран</b><small>{{ lastRemovedFile.file.filename }}</small></div>
        <button type="button" class="btn btn-secondary btn-small" :disabled="fileMutationBusy" @click="undoRemoveSessionFile">Вернуть</button>
        <button type="button" class="session-undo-close" aria-label="Скрыть" @click="clearRemovedFileUndo">×</button>
      </div>
      <section v-if="attentionIssues.length" class="attention-queue" aria-label="Требуют внимания">
        <header class="attention-header">
          <div><strong>Требуют внимания: {{ attentionIssues.length }}</strong></div>
          <button type="button" class="btn btn-secondary btn-small" :disabled="validateBusy || !enabledFiles.length" @click="validateAll">
            {{ validateBusy ? 'Проверяем…' : 'Перепроверить' }}
          </button>
        </header>
        <div class="attention-list">
          <article v-for="issue in attentionIssues.slice(0,5)" :key="issue.file_id + ':' + issue.code + ':' + issue.message" class="attention-item" :class="issue.severity">
            <span class="attention-dot"></span>
            <div class="attention-copy">
              <div class="attention-meta"><b>{{ issue.filename }}</b><span>{{ issue.scope === 'teacher' ? 'Преподаватели' : issue.scope === 'calendar' ? 'Даты' : issue.scope === 'range' ? 'Разметка' : issue.scope === 'sheet' ? 'Лист' : 'Файл' }}</span></div>
              <strong>{{ issue.message }}</strong>
            </div>
            <button type="button" class="btn btn-secondary btn-small" @click="issue.scope === 'teacher' ? openTeacherMapping(issue) : openAttentionIssue(issue)">
              {{ issue.scope === 'teacher' ? 'Настроить' : (issue.action?.label || 'Открыть') }}
            </button>
          </article>
          <p v-if="attentionIssues.length > 5" class="attention-more">Ещё {{ attentionIssues.length - 5 }} — в файлах и итоговом отчёте.</p>
        </div>
      </section>`);

    const groupInput = document.querySelector('.file-item .group-input');
    insertOnce(groupInput, 'afterend', '.file-resolution-state', `
      <div class="file-resolution-state">
        <span v-if="validations[file.file_id]?.report?.lesson_count" class="resolved">
          {{ validations[file.file_id].report.lesson_count }} занятий
        </span>
        <span v-else-if="validations[file.file_id]" class="attention">Нужно уточнить разметку</span>
        <span v-else class="neutral">Автопроверка</span>
      </div>
      <div class="file-session-actions" @click.stop>
        <label class="file-action" :class="{disabled:fileMutationBusy}">
          {{ mutatingFileId === file.file_id ? 'Заменяем…' : 'Заменить' }}
          <input hidden type="file" accept=".xlsx,.xlsm" :disabled="fileMutationBusy" @change="replaceSessionFile(file.file_id,$event)">
        </label>
        <button type="button" class="file-action remove" :disabled="fileMutationBusy" @click.stop="removeSessionFile(file)">Убрать</button>
      </div>`);

    document.querySelector('.bottom-actions .bottom-note')?.remove();
    const bottomPrimary = document.querySelector('.bottom-actions .btn-primary');
    bottomPrimary?.setAttribute(':disabled', 'generateBusy || fileMutationBusy || !enabledFiles.length');
    const bottomReset = document.querySelector('.bottom-actions .btn-secondary');
    if (bottomReset) bottomReset.textContent = 'Очистить';

    const resultLead = document.querySelector('.result-card .page-lead');
    insertOnce(resultLead, 'afterend', '.result-compact-summary', `
      <p class="result-compact-summary">Файлы готовы. При необходимости вернитесь к исходникам и сформируйте повторно.</p>`);

    const resultFile = document.querySelector('.result-file');
    insertOnce(resultFile, 'beforeend', '.result-file-action', `
      <button
        v-if="detail.file_id && (detail.status !== 'success' || !detail.used || detail.action_count)"
        type="button"
        class="btn btn-secondary btn-small result-file-action"
        @click="step=2; selectFile(detail.file_id)"
      >Уточнить</button>`);

    const resultActions = document.querySelector('.result-card > .button-row');
    resultActions?.classList.add('result-actions');
    insertOnce(resultActions, 'afterbegin', '.return-to-editor', `
      <button type="button" class="btn btn-secondary return-to-editor" @click="step=2">К исправлениям</button>`);
    const newFilesButton = [...(resultActions?.querySelectorAll('button') || [])]
        .find(button => button.textContent.includes('Обработать новые'));
    if (newFilesButton) newFilesButton.textContent = 'Новые файлы';
    const warningBox = document.querySelector('.result-card .warning-box');
    warningBox?.setAttribute('v-if', 'result.warnings?.length && !result.issue_groups?.length');

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
              <h2 id="teacher-mapping-title">Преподаватели по дисциплинам</h2>
              <p>Пустое поле оставляет автоматическое распределение.</p>
            </div>
            <button type="button" class="modal-close" aria-label="Закрыть" @click="closeTeacherMapping">×</button>
          </header>
          <div class="teacher-mapping-tools">
            <label class="teacher-mapping-search">
              <span class="sr-only">Найти дисциплину или преподавателя</span>
              <input v-model.trim="teacherMappingSearch" class="control" type="search" placeholder="Найти дисциплину или преподавателя">
            </label>
            <button type="button" class="btn btn-secondary btn-small" @click="resetAllTeacherRules">Сбросить всё</button>
          </div>
          <div class="teacher-mapping-list">
            <article v-for="item in filteredMappingSubjects" :key="item.name" class="teacher-mapping-row">
              <div class="teacher-rule-heading">
                <div>
                  <strong>{{ item.name }}</strong>
                  <small>{{ candidateHint(item) }}</small>
                </div>
                <button
                  v-if="teacherMappingDraft[item.name]?.lecturer || teacherMappingDraft[item.name]?.practice || teacherMappingDraft[item.name]?.reserve"
                  type="button"
                  class="teacher-rule-clear"
                  title="Вернуть автоматическое распределение"
                  @click="clearTeacherRule(item.name)"
                >Сбросить</button>
              </div>
              <div class="teacher-rule-grid">
                <label>
                  <span>Лекции</span>
                  <select v-model="teacherMappingDraft[item.name].lecturer" class="control">
                    <option value="">Автоматически</option>
                    <option v-for="teacher in teacherMappingOptions" :key="'l-'+teacher.id" :value="teacher.short_name">
                      {{ teacher.full_name || teacher.short_name }}
                    </option>
                  </select>
                </label>
                <label>
                  <span>Практика</span>
                  <select v-model="teacherMappingDraft[item.name].practice" class="control">
                    <option value="">Автоматически</option>
                    <option v-for="teacher in teacherMappingOptions" :key="'p-'+teacher.id" :value="teacher.short_name">
                      {{ teacher.full_name || teacher.short_name }}
                    </option>
                  </select>
                </label>
                <label>
                  <span>Резерв</span>
                  <select v-model="teacherMappingDraft[item.name].reserve" class="control">
                    <option value="">Не задан</option>
                    <option v-for="teacher in teacherMappingOptions" :key="'r-'+teacher.id" :value="teacher.short_name">
                      {{ teacher.full_name || teacher.short_name }}
                    </option>
                  </select>
                </label>
              </div>
              <div class="teacher-rule-summary">{{ ruleSummary(item.name) }}</div>
            </article>
            <p v-if="!filteredMappingSubjects.length" class="teacher-mapping-empty">Ничего не найдено.</p>
          </div>
          <footer class="teacher-mapping-footer">
            <label class="teacher-default-toggle">
              <input type="checkbox" v-model="teacherMappingSaveDefaults">
              <span>Использовать эти правила в следующих расписаниях</span>
            </label>
            <div>
              <button type="button" class="btn btn-secondary" :disabled="teacherMappingBusy" @click="closeTeacherMapping">Отмена</button>
              <button type="button" class="btn btn-primary" :disabled="teacherMappingBusy" @click="saveTeacherMapping">
                {{ teacherMappingBusy ? 'Применяем…' : 'Применить' }}
              </button>
            </div>
          </footer>
        </section>
      </div>`);

    const toastStack = document.querySelector('.toast-stack');
    toastStack?.setAttribute('aria-live', 'polite');
    toastStack?.setAttribute('aria-relevant', 'additions');
}

/** Common keyboard actions and result focus management. */
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
