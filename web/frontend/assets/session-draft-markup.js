export function installSessionDraftMarkup() {
    const app = document.querySelector('#app');
    if (app && !document.getElementById('analysis-file-replacement')) {
        app.insertAdjacentHTML('beforeend', `
          <input
            id="analysis-file-replacement"
            hidden
            type="file"
            accept=".xlsx,.xlsm,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.ms-excel.sheet.macroEnabled.12"
            @change="replaceAnalysisFile"
          >`);
    }

    const fileItem = document.querySelector('.file-list .file-item');
    if (fileItem && !fileItem.querySelector('.replace-session-file')) {
        fileItem.insertAdjacentHTML('beforeend', `
          <button
            type="button"
            class="btn btn-secondary btn-small replace-session-file"
            :class="{urgent:!file.analysis}"
            :disabled="replacementBusy"
            @click.stop="startFileReplacement(file.file_id)"
            :title="file.analysis ? 'Заменить только этот Excel, сохранив остальные файлы и правки' : 'Выбрать исправную копию этого файла'"
          >{{ replacementBusy && replacementFileId === file.file_id ? 'Заменяем…' : (file.analysis ? 'Заменить' : 'Выбрать другой') }}</button>`);
    }

    const bottomNote = document.querySelector('.bottom-actions .bottom-note');
    if (bottomNote && !document.querySelector('.analysis-draft-status')) {
        bottomNote.insertAdjacentHTML('beforeend', `
          <span v-if="sessionId" class="analysis-draft-status" :class="draftState" :title="draftError || 'Файлы и правки хранятся на сервере 24 часа'">
            <span class="draft-status-dot"></span>{{ draftStateLabel }}
          </span>`);
    }

    const resultCard = document.querySelector('.result-card');
    if (!resultCard || document.querySelector('.result-corrections-panel')) return;

    const title = resultCard.querySelector('.result-hero .page-title');
    if (title) {
        title.textContent = "{{ result.filename?.startsWith('schedule_recovery_') ? 'Разбор завершён' : 'Расписание сформировано' }}";
    }
    const icon = resultCard.querySelector('.result-icon');
    if (icon) {
        icon.textContent = "{{ result.status === 'success' ? '✓' : '!' }}";
        icon.setAttribute('v-bind:class', "{warning:result.status!=='success'}");
    }

    const resultFile = resultCard.querySelector('.result-file');
    if (resultFile) {
        resultFile.insertAdjacentHTML('beforeend', `
          <button
            v-if="detail.status !== 'success' || detail.used === false || detail.warning_count"
            type="button"
            class="btn btn-secondary btn-small result-file-fix"
            @click="openResultFile(detail)"
          >Открыть и исправить</button>`);
    }

    const buttons = resultCard.querySelector('.button-row');
    if (buttons) {
        buttons.insertAdjacentHTML('afterbegin', `
          <button type="button" class="btn btn-secondary" @click="returnToCorrections()">
            Вернуться к файлам и правкам
          </button>`);
        buttons.insertAdjacentHTML('beforebegin', `
          <section v-if="resultCorrections.length || resultProblemFiles.length || result.warnings?.length" class="result-corrections-panel">
            <div class="result-corrections-head">
              <div>
                <strong>Результат можно уточнить</strong>
                <span>Формирование не закрывает сеанс: исходники, разметка и ручные даты сохранены.</span>
              </div>
              <span class="analysis-draft-status" :class="draftState"><span class="draft-status-dot"></span>{{ draftStateLabel }}</span>
            </div>
            <div v-if="resultProblemFiles.length" class="result-problem-list">
              <button
                v-for="detail in resultProblemFiles"
                :key="'problem-' + (detail.file_id || detail.filename)"
                type="button"
                class="result-problem-item"
                @click="openResultFile(detail)"
              >
                <span><b>{{ detail.filename }}</b><small>{{ detail.message }}</small></span>
                <span>Исправить →</span>
              </button>
            </div>
            <details v-if="result.warnings?.length" class="result-correction-details result-warning-details" open>
              <summary>Предупреждения результата: {{ result.warnings.length }}</summary>
              <div class="result-warning-list">
                <article v-for="(warning,index) in result.warnings" :key="'warning-' + index">
                  <span class="result-warning-symbol">!</span>
                  <span>{{ warning }}</span>
                </article>
              </div>
            </details>
            <details v-if="resultCorrections.length" class="result-correction-details">
              <summary>Автоматические и ручные коррекции: {{ resultCorrections.length }}</summary>
              <div class="result-correction-list">
                <article v-for="(item,index) in resultCorrections" :key="'correction-' + index">
                  <b>{{ item.file || item.slot || item.field || 'Календарь' }}</b>
                  <span>{{ item.reason || item.message || 'Применено восстановление данных.' }}</span>
                  <small v-if="item.before !== undefined || item.after !== undefined">{{ item.before ?? '—' }} → {{ item.after ?? item.resolved_value ?? '—' }}</small>
                </article>
              </div>
            </details>
          </section>`);
    }
}
