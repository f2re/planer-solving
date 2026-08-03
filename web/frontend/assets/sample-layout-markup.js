export function installSampleLayoutMarkup() {
    const rangeEditor = document.querySelector('.range-editor');
    if (!rangeEditor || document.querySelector('.exact-layout-editor')) return;
    rangeEditor.insertAdjacentHTML('afterend', `
      <details v-if="currentLayout" class="exact-layout-editor">
        <summary>
          <span>Точная структура файла</span>
          <small>{{ exactLayoutSummary }}</small>
        </summary>

        <div class="exact-layout-body">
          <section class="exact-pick-section" aria-label="Назначение ячеек таблицы">
            <div class="exact-section-heading">
              <div>
                <h4>Назначить по таблице</h4>
                <p>Выберите назначение, затем щёлкайте нужные ячейки. Повторный щелчок удаляет координату из списка.</p>
              </div>
              <button v-if="exactPickMode" type="button" class="btn btn-secondary btn-small" @click="cancelExactPick">Завершить</button>
            </div>
            <div class="exact-pick-toolbar" role="toolbar" aria-label="Назначение координат">
              <button v-for="mode in exactPickModes" :key="mode.id" type="button"
                class="exact-pick-button" :class="{active:exactPickMode===mode.id}"
                @click="toggleExactPick(mode.id)">{{ mode.label }}</button>
            </div>
            <p class="exact-pick-hint" :class="{active:exactPickMode}">{{ exactPickHint }}</p>
          </section>

          <section class="exact-fields-section">
            <div class="exact-section-heading">
              <div>
                <h4>Координаты и смещения</h4>
                <p>Значения перечисляются через запятую. Нумерация строк и столбцов соответствует Excel и начинается с 1.</p>
              </div>
            </div>
            <div class="exact-fields-grid">
              <label>
                <span>Столбцы заголовков недель</span>
                <input class="control" :value="layoutListText('week_columns')"
                  @change="setLayoutList('week_columns', $event.target.value)" placeholder="4, 5, 6, …">
              </label>
              <label>
                <span>Столбцы данных недель</span>
                <input class="control" :value="layoutListText('week_data_columns')"
                  @change="setLayoutList('week_data_columns', $event.target.value)" placeholder="4, 5, 6, …">
              </label>
              <label>
                <span>Номера недель</span>
                <input class="control" :value="layoutListText('week_numbers')"
                  @change="setLayoutList('week_numbers', $event.target.value)" placeholder="0, 1, 2, …">
              </label>
              <label>
                <span>Строки начала дней</span>
                <input class="control" :value="layoutListText('day_start_rows')"
                  @change="setLayoutList('day_start_rows', $event.target.value)" placeholder="8, 21, 34, …">
              </label>
              <label>
                <span>Смещения начала пар</span>
                <input class="control" :value="layoutListText('pair_row_offsets')"
                  @change="setLayoutList('pair_row_offsets', $event.target.value)" placeholder="0, 3, 6, 9">
              </label>
              <label>
                <span>Первая строка данных блока</span>
                <input class="control" type="number" min="1" :value="currentLayout.legend_data_start_row || ''"
                  @change="setLayoutNumber('legend_data_start_row', $event.target.value, true)">
              </label>
              <label>
                <span>Смещение строки вида занятия</span>
                <input class="control" type="number" :value="currentLayout.code_row_offset"
                  @change="setLayoutNumber('code_row_offset', $event.target.value)">
              </label>
              <label>
                <span>Смещение строки дисциплины</span>
                <input class="control" type="number" :value="currentLayout.subject_row_offset"
                  @change="setLayoutNumber('subject_row_offset', $event.target.value)">
              </label>
              <label>
                <span>Смещение строки аудитории</span>
                <input class="control" type="number" :value="currentLayout.room_row_offset"
                  @change="setLayoutNumber('room_row_offset', $event.target.value)">
              </label>
              <label>
                <span>Смещение строки преподавателя</span>
                <input class="control" type="number" :value="currentLayout.teacher_row_offset ?? ''"
                  @change="setLayoutNumber('teacher_row_offset', $event.target.value, true)">
              </label>
              <label>
                <span>Роли преподавателей</span>
                <select class="control" v-model="currentLayout.teacher_role_fallback" @change="markExactLayoutDirty">
                  <option value="strict">Строго: лектор отдельно</option>
                  <option value="any">Разрешить подстановку</option>
                </select>
              </label>
              <label class="exact-checkbox">
                <input type="checkbox" v-model="currentLayout.allow_week_zero" @change="markExactLayoutDirty">
                <span>Разрешить неделю 0</span>
              </label>
            </div>
          </section>

          <div v-if="exactLayoutIssues.length" class="exact-layout-issues" aria-live="polite">
            <strong>Проверьте структуру</strong>
            <span v-for="issue in exactLayoutIssues" :key="issue">{{ issue }}</span>
          </div>
        </div>
      </details>`);
}
