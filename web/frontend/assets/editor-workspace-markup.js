import { installUnifiedOperationsMarkup } from './unified-operations.js';

export function installEditorWorkspaceMarkup() {
    if (!document.querySelector('link[data-workflow-audit-style]')) {
        const link = document.createElement('link');
        link.rel = 'stylesheet';
        link.href = '/assets/workflow-audit.css';
        link.dataset.workflowAuditStyle = '1';
        document.head.appendChild(link);
    }
    const grid = document.querySelector('.workflow-grid');
    if (!grid || document.querySelector('.sheet-command-bar')) return;

    const filesPanel = grid.querySelector('aside.panel:not(.settings-panel)');
    const canvasPanel = grid.querySelector('section.panel');
    const settingsPanel = grid.querySelector('aside.settings-panel');
    filesPanel?.classList.add('editor-files-panel');
    canvasPanel?.classList.add('editor-canvas-panel');
    settingsPanel?.classList.add('editor-settings-panel');

    if (filesPanel) {
        filesPanel.setAttribute('v-show', 'filesPanelVisible || !sheetWorkspaceOpen');
        filesPanel.setAttribute('v-bind:style', 'dockPanelStyle("files")');
        filesPanel.querySelector('.panel-header')?.insertAdjacentHTML(
            'afterbegin',
            '<button v-if="sheetWorkspaceOpen" class="dock-handle" type="button" title="Перетащить панель" @pointerdown="beginDockDrag(\'files\',$event)">⠿</button>'
        );
    }
    if (settingsPanel) {
        settingsPanel.setAttribute('v-show', 'settingsPanelVisible || !sheetWorkspaceOpen');
        settingsPanel.setAttribute('v-bind:style', 'dockPanelStyle("settings")');
        settingsPanel.querySelector('.panel-header')?.insertAdjacentHTML(
            'afterbegin',
            '<button v-if="sheetWorkspaceOpen" class="dock-handle" type="button" title="Перетащить панель" @pointerdown="beginDockDrag(\'settings\',$event)">⠿</button>'
        );
    }

    const previewToolbar = canvasPanel?.querySelector('.preview-toolbar');
    previewToolbar?.insertAdjacentHTML('afterend', `
      <div class="sheet-command-bar" :class="{fullscreen:sheetWorkspaceOpen}">
        <button v-if="!sheetWorkspaceOpen" type="button" class="btn btn-primary btn-small" @click="enterSheetWorkspace(false)">Развернуть рабочий лист</button>
        <template v-else>
          <button type="button" class="sheet-tool" :class="{active:filesPanelVisible}" @click="filesPanelVisible=!filesPanelVisible" title="Файлы">☰ <span>Файлы</span></button>
          <button type="button" class="sheet-tool" :class="{active:settingsPanelVisible}" @click="settingsPanelVisible=!settingsPanelVisible" title="Параметры">⚙ <span>Параметры</span></button>
          <button type="button" class="sheet-tool" :class="{active:editorControlsVisible}" @click="editorControlsVisible=!editorControlsVisible" title="Инструменты разметки">⌗ <span>Разметка</span></button>
          <span class="sheet-toolbar-separator"></span>
          <button type="button" class="sheet-tool icon-only" @click="zoomOutSheet" title="Уменьшить">−</button>
          <button type="button" class="sheet-zoom-value" @click="fitSheetToScreen" title="Подогнать под экран">{{ Math.round(sheetZoom*100) }}%</button>
          <button type="button" class="sheet-tool icon-only" @click="zoomInSheet" title="Увеличить">+</button>
          <button type="button" class="sheet-tool" @click="fitSheetToScreen" title="Подогнать лист">⤢ <span>По экрану</span></button>
          <button type="button" class="sheet-tool" @click="resetWorkspaceView" title="Сбросить сохранённое положение панелей и масштаб">↺ <span>Сбросить вид</span></button>
          <span class="sheet-toolbar-separator"></span>
          <button type="button" class="sheet-tool" :class="{active:liveRecalc}" @click="liveRecalc=!liveRecalc" title="Автоматический пересчёт">↻ <span>Авто</span></button>
          <button type="button" class="sheet-tool" @click="recalculateNow" :disabled="recalcState==='working'">✓ <span>Пересчитать</span></button>
          <button
            type="button"
            class="sheet-tool icon-only sheet-history-undo"
            :disabled="!canUndoEditor || applyingHistory"
            :title="canUndoEditor ? 'Отменить изменение · Ctrl/Cmd+Z' : 'Нет изменений для отмены'"
            aria-label="Отменить изменение"
            @click="undoEditorChange"
          >↶</button>
          <button
            type="button"
            class="sheet-tool icon-only sheet-history-redo"
            :disabled="!canRedoEditor || applyingHistory"
            :title="canRedoEditor ? 'Вернуть изменение · Ctrl/Cmd+Shift+Z или Ctrl+Y' : 'Нет изменений для возврата'"
            aria-label="Вернуть изменение"
            @click="redoEditorChange"
          >↷</button>
          <span class="sheet-file-save-state" :class="{dirty:layoutDirty}">
            {{ layoutDirty ? 'Изменения файла — в черновике' : 'Разметка файла сохранена' }}
          </span>
          <button type="button" class="sheet-tool save" @click="requestTemplateSave" title="Сохранить текущую разметку как глобальный шаблон для будущих файлов">◆ <span>Шаблон</span></button>
          <button type="button" class="sheet-tool generate" @click="generateFromEditor" :disabled="generating" title="Проверить все файлы и сформировать расписание">
            ▶ <span>{{ generating ? 'Формируем…' : 'Сформировать' }}</span>
          </button>
          <span class="sheet-recalc-status" :class="recalcState">{{ recalcLabel }}</span>
          <button type="button" class="sheet-tool exit" @click="leaveSheetWorkspace" title="Вернуться к обычному виду, не закрывая сеанс">× <span>К обычному виду</span></button>
        </template>
      </div>`);

    const previewWrap = canvasPanel?.querySelector('.preview-wrap');
    if (previewWrap) {
        previewWrap.setAttribute('v-bind:class', '{ "sheet-workspace-canvas": sheetWorkspaceOpen }');
        previewWrap.setAttribute('v-on:wheel.ctrl.prevent', 'zoomSheetWheel');
    }
    const table = previewWrap?.querySelector('.preview-table');
    if (table) table.setAttribute('v-bind:style', '{ zoom: sheetZoom }');

    const corner = table?.querySelector('thead th.row-number');
    if (corner) {
        corner.setAttribute('v-on:click.stop', 'selectWholeSheet');
        corner.setAttribute('title', 'Выбрать видимую область листа');
        corner.classList.add('sheet-select-corner');
    }
    const columnHeader = table?.querySelector('thead th[v-for]');
    if (columnHeader) {
        columnHeader.setAttribute('v-on:click.stop', 'selectSheetColumn(column.index,$event)');
        columnHeader.setAttribute('v-bind:class', '{ "sheet-header-selected": isSheetColumnSelected(column.index) }');
        columnHeader.setAttribute('title', 'Щелчок — выбрать столбец; Shift — диапазон столбцов');
        columnHeader.setAttribute('tabindex', '0');
    }
    const rowHeader = table?.querySelector('tbody th.row-number');
    if (rowHeader) {
        rowHeader.setAttribute('v-on:click.stop', 'selectSheetRow(row.index,$event)');
        rowHeader.setAttribute('v-bind:class', '{ "sheet-header-selected": isSheetRowSelected(row.index) }');
        rowHeader.setAttribute('title', 'Щелчок — выбрать строку; Shift — диапазон строк');
        rowHeader.setAttribute('tabindex', '0');
    }

    const rangeEditor = document.querySelector('.range-editor');
    const exactEditor = document.querySelector('.exact-layout-editor');
    rangeEditor?.setAttribute('v-show', 'editorControlsVisible || !sheetWorkspaceOpen');
    if (exactEditor) {
        const details = document.createElement('details');
        details.className = 'expert-layout-details';
        details.setAttribute('v-show', 'editorControlsVisible || !sheetWorkspaceOpen');
        details.innerHTML = '<summary><span>Точные координаты</span><small>Экспертный режим — открывайте только для нестандартной таблицы</small></summary>';
        exactEditor.parentNode?.insertBefore(details, exactEditor);
        details.appendChild(exactEditor);
    }

    const resultActions = document.querySelector('.result-actions');
    resultActions?.insertAdjacentHTML('afterbegin', `
      <button type="button" class="btn btn-primary" @click="returnToCorrections">
        ← Вернуться к исправлениям
      </button>
      <button v-if="result.run_id" type="button" class="btn btn-secondary" @click="openCurrentRunHistory">
        История этого формирования
      </button>
    `);

    const warningList = document.querySelector('.result-card .warning-list');
    warningList?.insertAdjacentHTML('beforebegin', `
      <section v-if="result.issue_groups?.length" class="issue-group-list" aria-label="Замечания по смыслу">
        <details
          v-for="group in result.issue_groups"
          :key="group.id"
          class="issue-group"
          :class="[group.category, group.severity]"
          :open="group.requires_action"
        >
          <summary>
            <span>{{ group.label }}</span>
            <small>{{ group.summary }}</small>
          </summary>
          <article v-for="item in group.items" :key="item.code + item.message" class="issue-group-item">
            <b>{{ item.message }}</b>
            <p>{{ item.default_decision }}</p>
            <small>{{ item.impact }}</small>
          </article>
        </details>
      </section>
    `);

    const app = document.querySelector('#app');
    app?.insertAdjacentHTML('beforeend', `
      <div v-if="templateSaveOpen" class="template-save-backdrop" @click.self="cancelTemplateSave">
        <section class="template-save-dialog card" role="dialog" aria-modal="true" aria-label="Сохранение шаблона">
          <div class="template-save-icon">◆</div>
          <div>
            <h3>Сохранить глобальный шаблон?</h3>
            <p>Текущая разметка файла уже сохранена в серверном черновике. Шаблон нужен только для автоматического применения к будущим похожим книгам.</p>
          </div>
          <label>Название шаблона<input class="control" v-model.trim="smartTemplateName" @keydown.enter.prevent="saveEditorTemplate"></label>
          <label v-if="selectedEditorTemplate">Действие<select class="control" v-model="templateSaveMode"><option value="update">Обновить «{{ selectedEditorTemplate.name }}»</option><option value="new">Сохранить новым шаблоном</option></select></label>
          <div class="template-save-actions">
            <button type="button" class="btn btn-primary" @click="saveEditorTemplate" :disabled="templateSaving || !smartTemplateName">{{ templateSaving ? 'Сохраняем…' : 'Сохранить шаблон' }}</button>
            <button type="button" class="btn btn-secondary" @click="cancelTemplateSave">Отмена</button>
          </div>
        </section>
      </div>`);

    document.querySelectorAll('.auth-form input[type="password"], .user-form input[type="password"]').forEach(input => {
        input.removeAttribute('required');
        input.removeAttribute('minlength');
        input.setAttribute('placeholder', 'Можно оставить пустым');
    });
    const userPasswordLabel = [...document.querySelectorAll('.user-form label')]
        .find(label => label.querySelector('input[type="password"]'));
    if (userPasswordLabel?.firstChild) {
        userPasswordLabel.firstChild.nodeValue = 'Пароль — любая длина, можно пустой';
    }
    const userActions = document.querySelector('.user-form .button-row');
    userActions?.insertAdjacentHTML(
        'beforeend',
        '<button v-if="userForm.id" type="button" class="btn btn-secondary" @click="clearUserPassword">Сбросить пароль</button>'
    );

    installUnifiedOperationsMarkup();
}
