function insertOnce(target, position, marker, html) {
    if (!target || document.querySelector(marker)) return;
    target.insertAdjacentHTML(position, html);
}

export function installHistoryUxMarkup() {
    const listStatus = document.querySelector('.history-list em');
    if (listStatus) listStatus.textContent = '{{ processingStatusLabel(run.status) }}';

    const detailStatus = document.querySelector('.run-hero .status-pill');
    if (detailStatus) detailStatus.textContent = '{{ processingStatusLabel(selectedRun.status) }}';

    const runHero = document.querySelector('.run-hero');
    insertOnce(runHero, 'beforeend', '.run-repeat-action', `
      <div class="run-history-actions">
        <button
          v-if="selectedRun?.report?.session_id === sessionId"
          type="button"
          class="btn btn-primary btn-small run-return-action"
          @click="returnToCorrections"
        >Вернуться к исправлениям</button>
        <button
          v-if="selectedRun"
          type="button"
          class="btn btn-secondary btn-small run-repeat-action"
          @click="repeatRun(selectedRun)"
        >Повторить с теми же решениями</button>
      </div>`);

    const firstHistoryHeading = document.querySelector('.run-details > h4');
    insertOnce(firstHistoryHeading, 'beforebegin', '.history-issue-groups', `
      <section
        v-if="selectedRun?.report?.issue_groups?.length"
        class="history-issue-groups issue-group-list"
        aria-label="Итоги разрешения замечаний"
      >
        <h4>Замечания и решения</h4>
        <details
          v-for="group in selectedRun.report.issue_groups"
          :key="group.id"
          class="issue-group"
          :class="[group.category, group.severity]"
          :open="group.requires_action"
        >
          <summary>
            <span>{{ group.label }}</span>
            <small>{{ group.summary }}</small>
          </summary>
          <article
            v-for="item in group.items"
            :key="item.code + item.message"
            class="issue-group-item"
          >
            <b>{{ item.message }}</b>
            <p>{{ item.default_decision }}</p>
            <small>{{ item.impact }}</small>
          </article>
        </details>
      </section>`);

    const fileRow = document.querySelector('.run-details .detail-list > div');
    insertOnce(fileRow, 'beforeend', '.history-file-decisions', `
      <button
        v-if="historyFileIssues(file).length"
        type="button"
        class="history-file-decisions"
        @click="openHistoryFileDecisions(file)"
      >Решения: {{ historyFileIssues(file).length }}</button>`);

    const app = document.querySelector('#app');
    insertOnce(app, 'beforeend', '.history-decisions-backdrop', `
      <div
        v-if="historyDecisionOpen"
        class="modal-backdrop history-decisions-backdrop"
        role="presentation"
        @click.self="closeHistoryFileDecisions"
      >
        <section class="history-decisions-dialog" role="dialog" aria-modal="true" aria-labelledby="history-decisions-title">
          <header class="history-decisions-header">
            <div>
              <span class="eyebrow">Сохранённый запуск</span>
              <h2 id="history-decisions-title">Решения по файлу</h2>
              <p>{{ selectedHistoryFile?.filename }} · {{ selectedHistoryFile?.group_name }}</p>
            </div>
            <button type="button" class="modal-close" aria-label="Закрыть" @click="closeHistoryFileDecisions">×</button>
          </header>
          <div class="history-decisions-list">
            <article v-for="issue in selectedHistoryIssues" :key="issue.code + ':' + issue.message" class="history-decision" :class="issue.severity">
              <div class="history-decision-meta">
                <span>{{ historyIssueScopeLabel(issue.scope) }}</span>
                <b>{{ historyResolutionLabel(issue.resolution) }}</b>
              </div>
              <h3>{{ issue.message }}</h3>
              <p><strong>По умолчанию:</strong> {{ issue.default_decision || 'Система продолжила обработку безопасным способом.' }}</p>
              <small>{{ issue.impact || 'Решение записано в историю обработки.' }}</small>
              <code v-if="issue.code">{{ issue.code }}</code>
            </article>
            <p v-if="!selectedHistoryIssues.length" class="history-decisions-empty">Для этого файла не сохранено замечаний или ручных решений.</p>
          </div>
          <footer class="history-decisions-footer">
            <span>История неизменяема. Для другого решения повторите запуск с архивными исходниками.</span>
            <button type="button" class="btn btn-primary" @click="closeHistoryFileDecisions">Готово</button>
          </footer>
        </section>
      </div>`);
}
