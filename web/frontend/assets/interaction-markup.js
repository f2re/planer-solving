export function installInteractionMarkup() {
    const formatNote = document.querySelector('.format-note');
    if (formatNote) {
        formatNote.textContent = 'Количество и размер расписаний приложением не ограничиваются. Файлы передаются на сервер потоково.';
    }

    const uploadBusyBox = document.querySelector('.dropzone [v-else]');
    if (uploadBusyBox && !document.querySelector('.upload-stream-progress')) {
        uploadBusyBox.insertAdjacentHTML('beforeend', `
          <div v-if="uploadProgress.total" class="upload-stream-progress" aria-live="polite">
            <div class="upload-stream-track"><span :style="{width: uploadProgress.percent + '%'}"></span></div>
            <span>{{ uploadProgress.percent }}% · {{ formatBytes(uploadProgress.loaded) }} из {{ formatBytes(uploadProgress.total) }}</span>
          </div>`);
    }

    const profileNote = document.querySelector('.settings-section .section-note');
    if (profileNote) {
        profileNote.textContent = 'Шаблоны хранятся в активном пространстве на сервере и автоматически проверяются на каждом новом файле.';
    }

    const previewToolbar = document.querySelector('.preview-toolbar');
    if (previewToolbar && !document.querySelector('.range-editor')) {
        previewToolbar.insertAdjacentHTML('afterend', `
          <div v-if="currentLayout" class="range-editor" aria-label="Интерактивная разметка таблицы">
            <div class="range-editor-main">
              <div class="range-mode-group" role="toolbar" aria-label="Что выделять">
                <button type="button" class="range-mode" :class="{active:selectionMode==='grid'}" @click="setSelectionMode('grid')">Сетка занятий</button>
                <button type="button" class="range-mode" :class="{active:selectionMode==='weeks'}" @click="setSelectionMode('weeks')">Строка недель</button>
                <button type="button" class="range-mode" :class="{active:selectionMode==='months'}" @click="setSelectionMode('months')">Строка месяцев</button>
                <button type="button" class="range-mode" :class="{active:selectionMode==='legend'}" @click="setSelectionMode('legend')">Блок дисциплин</button>
              </div>
              <select class="control range-field-select" :value="selectionMode" @change="setSelectionMode($event.target.value)" aria-label="Выбрать отдельный столбец блока">
                <option value="grid">Сетка занятий</option>
                <option value="weeks">Строка и столбцы недель</option>
                <option value="months">Строка месяцев</option>
                <option value="legend">Весь блок дисциплин</option>
                <option value="legend_code">Столбец обозначения</option>
                <option value="legend_subject">Столбец дисциплины</option>
                <option value="legend_lecturer">Столбец лектора</option>
                <option value="legend_other">Столбец остальных преподавателей</option>
              </select>
            </div>
            <div class="range-editor-status" aria-live="polite">
              <span class="range-status-dot"></span>
              <span>{{ selectionHint }}</span>
            </div>
            <div class="button-row range-editor-actions">
              <button type="button" class="btn btn-secondary btn-small" @click="undoInteractiveChange" :disabled="!canUndoInteractiveChange">Отменить изменение</button>
              <button type="button" class="btn btn-secondary btn-small" @click="clearRangeSelection" :disabled="!selectedRange">Снять выделение</button>
            </div>
          </div>`);
    }

    const previewCell = document.querySelector('.preview-table tbody td');
    if (previewCell && !previewCell.hasAttribute('data-parser-cell')) {
        previewCell.setAttribute('data-parser-cell', 'true');
        previewCell.setAttribute(':data-row', 'row.index');
        previewCell.setAttribute(':data-col', 'cell.column');
        previewCell.setAttribute(':class', '[cellClass(row, cell), interactiveCellClass(row, cell)]');
        previewCell.setAttribute('@pointerdown', 'beginRangeSelection(row.index, cell.column, $event)');
        previewCell.setAttribute('@keydown.enter.prevent', 'selectSingleCell(row.index, cell.column)');
        previewCell.setAttribute('@keydown.space.prevent', 'selectSingleCell(row.index, cell.column)');
        previewCell.setAttribute(':aria-selected', 'isCellSelected(row.index, cell.column)');
        previewCell.setAttribute('tabindex', '0');
        previewCell.setAttribute('role', 'gridcell');
    }

    const settings = document.querySelector('.settings-scroll');
    if (settings && !document.querySelector('.template-match-section')) {
        settings.insertAdjacentHTML('afterbegin', `
          <section v-if="currentFile?.analysis" class="settings-section template-match-section">
            <div class="template-match-heading">
              <div>
                <h3>Автоподбор разметки</h3>
                <p class="section-note">Каждый шаблон запускается на текущем файле. Побеждает вариант, который извлекает больше достоверных занятий и преподавателей при меньшем числе ошибок.</p>
              </div>
              <button type="button" class="btn btn-secondary btn-small" @click="rematchTemplates" :disabled="templateMatchBusy">Проверить снова</button>
            </div>
            <div v-if="currentFile.matching" class="match-loading" aria-live="polite">
              <span class="spinner"></span>
              <span>Проверяем все шаблоны пространства…</span>
            </div>
            <div v-else-if="currentFile.template_match" class="match-card" :class="currentFile.template_match.usable ? 'usable' : 'unusable'">
              <div class="match-card-title">
                <div>
                  <span class="match-source">{{ currentFile.template_match.source === 'template' ? 'Подобран шаблон' : 'Автоматическая разметка' }}</span>
                  <strong>{{ currentFile.template_match.name }}</strong>
                </div>
                <span class="match-quality">{{ currentFile.template_match.quality_percent }}%</span>
              </div>
              <p>{{ templateMatchDescription(currentFile.template_match) }}</p>
              <div class="match-metrics">
                <span><b>{{ currentFile.template_match.metrics?.unique_lessons || 0 }}</b> занятий</span>
                <span><b>{{ currentFile.template_match.metrics?.mapped_lessons || 0 }}</b> назначено</span>
                <span><b>{{ currentFile.template_match.metrics?.active_weeks || 0 }}</b> недель</span>
              </div>
              <label class="match-candidate-select">
                <span>Другой результат проверки</span>
                <select class="control" :value="candidateKey(currentFile.template_match)" @change="applyMatchCandidate($event.target.value)">
                  <option v-for="candidate in (currentFile.template_candidates || [])" :key="candidate.candidate_key" :value="candidate.candidate_key">
                    {{ candidate.name }} · {{ candidate.quality_percent }}% · {{ candidate.metrics?.unique_lessons || 0 }} занятий
                  </option>
                </select>
              </label>
            </div>
            <div v-else class="match-empty">Шаблоны будут проверены сразу после загрузки файла.</div>
            <div v-if="templateMatchBusy" class="match-progress" aria-live="polite">
              Проверено файлов: {{ templateMatchProgress.done }} из {{ templateMatchProgress.total }}
            </div>
          </section>`);
    }

    const groupInput = document.querySelector('.file-item .group-input');
    if (groupInput && !document.querySelector('.file-template-match')) {
        groupInput.insertAdjacentHTML('beforebegin', `
          <div v-if="file.matching" class="file-template-match matching">Подбираем разметку…</div>
          <div v-else-if="file.template_match" class="file-template-match">
            {{ file.template_match.source === 'template' ? 'Шаблон' : 'Авто' }}: {{ file.template_match.name }} · {{ file.template_match.quality_percent }}%
          </div>`);
    }
}
