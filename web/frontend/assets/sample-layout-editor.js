const { ref, computed, watch, onBeforeUnmount } = Vue;

const INTEGER_LIST_FIELDS = new Set([
    'week_columns',
    'week_data_columns',
    'week_numbers',
    'day_start_rows',
    'pair_row_offsets'
]);

const PICK_LABELS = {
    week_header: 'Номера недель',
    week_data: 'Ячейки расписания недель',
    day_start: 'Начала дней',
    pair_start: 'Начала пар',
    code_row: 'Строка вида занятия',
    subject_row: 'Строка дисциплины',
    room_row: 'Строка аудитории',
    teacher_row: 'Строка преподавателя',
    legend_data_start: 'Первая строка данных блока'
};

export { installSampleLayoutMarkup } from './sample-layout-markup.js';

export function createSampleLayoutState(addToast, schedule) {
    const exactPickMode = ref('');
    const exactPickModes = [
        { id: 'week_header', label: 'Недели' },
        { id: 'week_data', label: 'Данные недель' },
        { id: 'day_start', label: 'Начало дня' },
        { id: 'pair_start', label: 'Начало пары' },
        { id: 'code_row', label: 'Вид занятия' },
        { id: 'subject_row', label: 'Дисциплина' },
        { id: 'room_row', label: 'Аудитория' },
        { id: 'teacher_row', label: 'Преподаватель' },
        { id: 'legend_data_start', label: 'Начало данных блока' }
    ];

    const integer = value => {
        const text = String(value ?? '').trim();
        if (!text) return null;
        const parsed = Number(text.replace(',', '.'));
        return Number.isFinite(parsed) ? Math.trunc(parsed) : null;
    };
    const integerList = value => {
        const source = Array.isArray(value) ? value : String(value ?? '').split(/[;,\s]+/);
        const result = [];
        for (const item of source) {
            const parsed = integer(item);
            if (parsed !== null && !result.includes(parsed)) result.push(parsed);
        }
        return result;
    };
    const sortedUnique = (values, minimum = 0) => integerList(values)
        .filter(value => value >= minimum)
        .sort((left, right) => left - right);
    const median = values => {
        if (!values.length) return 0;
        const sorted = [...values].sort((left, right) => left - right);
        const middle = Math.floor(sorted.length / 2);
        return sorted.length % 2
            ? sorted[middle]
            : Math.round((sorted[middle - 1] + sorted[middle]) / 2);
    };

    const previewValue = (row, col) => {
        const previewRow = (schedule.preview.value?.rows || []).find(item => Number(item.index) === Number(row));
        const cell = previewRow?.cells?.find(item => Number(item.column) === Number(col));
        return cell?.value ?? '';
    };

    const markExactLayoutDirty = () => schedule.markDirty();
    const syncWeekScalars = layout => {
        const columns = sortedUnique(layout.week_columns, 1);
        layout.week_columns = columns;
        if (columns.length) {
            layout.first_week_col = columns[0];
            layout.last_week_col = columns[columns.length - 1];
            const gaps = columns.slice(1).map((value, index) => value - columns[index]);
            layout.week_col_step = Math.max(1, median(gaps) || 1);
        }
    };
    const syncDayScalars = layout => {
        const rows = sortedUnique(layout.day_start_rows, 1);
        layout.day_start_rows = rows;
        if (rows.length) {
            layout.grid_start_row = rows[0];
            const gaps = rows.slice(1).map((value, index) => value - rows[index]);
            if (gaps.length) layout.day_block_rows = Math.max(1, median(gaps));
        }
    };
    const syncPairScalars = layout => {
        const offsets = sortedUnique(layout.pair_row_offsets, 0);
        layout.pair_row_offsets = offsets;
        if (offsets.length) {
            layout.pairs_per_day = offsets.length;
            const gaps = offsets.slice(1).map((value, index) => value - offsets[index]);
            if (gaps.length) layout.pair_row_stride = Math.max(1, median(gaps));
        }
    };

    const inferWeekNumbers = layout => {
        const existing = new Map();
        (layout.week_columns || []).forEach((col, index) => {
            const number = integer((layout.week_numbers || [])[index]);
            if (number !== null) existing.set(Number(col), number);
        });
        const start = layout.allow_week_zero ? 0 : 1;
        layout.week_numbers = layout.week_columns.map((col, index) => {
            const fromPreview = integer(previewValue(layout.weeks_row, col));
            if (fromPreview !== null) return fromPreview;
            if (existing.has(col)) return existing.get(col);
            return start + index;
        });
    };

    const layoutListText = field => integerList(schedule.currentLayout.value?.[field]).join(', ');
    const setLayoutList = (field, value) => {
        const layout = schedule.currentLayout.value;
        if (!layout || !INTEGER_LIST_FIELDS.has(field)) return;
        const minimum = field === 'pair_row_offsets' || field === 'week_numbers' ? 0 : 1;
        layout[field] = sortedUnique(value, minimum);
        if (field === 'week_columns') {
            syncWeekScalars(layout);
            inferWeekNumbers(layout);
            if (!layout.week_data_columns?.length) layout.week_data_columns = [...layout.week_columns];
        } else if (field === 'week_data_columns') {
            layout.week_data_columns = sortedUnique(value, 1);
        } else if (field === 'week_numbers') {
            layout.week_numbers = integerList(value);
            layout.allow_week_zero = layout.week_numbers.includes(0) || Boolean(layout.allow_week_zero);
        } else if (field === 'day_start_rows') {
            syncDayScalars(layout);
        } else if (field === 'pair_row_offsets') {
            syncPairScalars(layout);
        }
        markExactLayoutDirty();
    };
    const setLayoutNumber = (field, value, nullable = false) => {
        const layout = schedule.currentLayout.value;
        if (!layout) return;
        const parsed = integer(value);
        layout[field] = parsed === null && nullable ? null : (parsed ?? 0);
        if (field === 'legend_data_start_row' && layout.legend_start_row && layout[field]) {
            layout.legend_data_start_offset = layout[field] - Number(layout.legend_start_row);
        }
        markExactLayoutDirty();
    };

    const toggleListValue = (layout, field, value, minimum = 0) => {
        const values = sortedUnique(layout[field], minimum);
        const index = values.indexOf(value);
        if (index >= 0) values.splice(index, 1);
        else values.push(value);
        layout[field] = values.sort((left, right) => left - right);
    };

    const firstPairBase = layout => {
        const day = sortedUnique(layout.day_start_rows, 1)[0] || Number(layout.grid_start_row || 1);
        const pair = sortedUnique(layout.pair_row_offsets, 0)[0] || 0;
        return day + pair;
    };

    const applyExactCell = (row, col) => {
        const layout = schedule.currentLayout.value;
        const mode = exactPickMode.value;
        if (!layout || !mode) return;
        switch (mode) {
            case 'week_header': {
                const entries = new Map();
                (layout.week_columns || []).forEach((column, index) => entries.set(Number(column), {
                    number: integer((layout.week_numbers || [])[index]),
                    data: integer((layout.week_data_columns || [])[index])
                }));
                if (entries.has(col)) entries.delete(col);
                else entries.set(col, {
                    number: integer(previewValue(row, col)),
                    data: col
                });
                const ordered = [...entries.entries()].sort((left, right) => left[0] - right[0]);
                layout.weeks_row = row;
                layout.week_columns = ordered.map(item => item[0]);
                layout.week_numbers = ordered.map((item, index) => item[1].number ?? (layout.allow_week_zero ? index : index + 1));
                layout.week_data_columns = ordered.map(item => item[1].data ?? item[0]);
                syncWeekScalars(layout);
                break;
            }
            case 'week_data':
                toggleListValue(layout, 'week_data_columns', col, 1);
                break;
            case 'day_start':
                toggleListValue(layout, 'day_start_rows', row, 1);
                syncDayScalars(layout);
                break;
            case 'pair_start': {
                const day = sortedUnique(layout.day_start_rows, 1)[0] || Number(layout.grid_start_row || 1);
                const offset = Math.max(0, row - day);
                toggleListValue(layout, 'pair_row_offsets', offset, 0);
                syncPairScalars(layout);
                break;
            }
            case 'code_row':
                layout.code_row_offset = row - firstPairBase(layout);
                exactPickMode.value = '';
                break;
            case 'subject_row':
                layout.subject_row_offset = row - firstPairBase(layout);
                exactPickMode.value = '';
                break;
            case 'room_row':
                layout.room_row_offset = row - firstPairBase(layout);
                exactPickMode.value = '';
                break;
            case 'teacher_row':
                layout.teacher_row_offset = row - firstPairBase(layout);
                exactPickMode.value = '';
                break;
            case 'legend_data_start':
                layout.legend_data_start_row = row;
                if (layout.legend_start_row) layout.legend_data_start_offset = row - Number(layout.legend_start_row);
                exactPickMode.value = '';
                break;
            default:
                return;
        }
        layout.allow_week_zero = (layout.week_numbers || []).includes(0) || Boolean(layout.allow_week_zero);
        markExactLayoutDirty();
    };

    const captureExactPick = event => {
        if (!exactPickMode.value) return;
        const cell = event.target?.closest?.('[data-parser-cell]');
        if (!cell) return;
        const row = Number(cell.dataset.row);
        const col = Number(cell.dataset.col);
        if (!Number.isFinite(row) || !Number.isFinite(col)) return;
        event.preventDefault();
        event.stopPropagation();
        event.stopImmediatePropagation();
        applyExactCell(row, col);
    };

    const toggleExactPick = mode => {
        exactPickMode.value = exactPickMode.value === mode ? '' : mode;
    };
    const cancelExactPick = () => { exactPickMode.value = ''; };

    const exactPickHint = computed(() => exactPickMode.value
        ? `Режим «${PICK_LABELS[exactPickMode.value]}». Щёлкните нужную ячейку в предпросмотре.`
        : 'Выберите назначение. Для списков можно последовательно отметить несколько ячеек или строк.');

    const exactLayoutSummary = computed(() => {
        const layout = schedule.currentLayout.value || {};
        const weeks = integerList(layout.week_columns).length;
        const days = integerList(layout.day_start_rows).length;
        const pairs = integerList(layout.pair_row_offsets).length || Number(layout.pairs_per_day || 0);
        return `${weeks || '—'} недельных столбцов · ${days || '—'} дней · ${pairs || '—'} пары`;
    });

    const exactLayoutIssues = computed(() => {
        const layout = schedule.currentLayout.value || {};
        const issues = [];
        const headers = integerList(layout.week_columns);
        const data = integerList(layout.week_data_columns);
        const numbers = integerList(layout.week_numbers);
        const days = integerList(layout.day_start_rows);
        if (!headers.length) issues.push('Не заданы точные столбцы заголовков недель.');
        if (headers.length && data.length !== headers.length) {
            issues.push('Число столбцов данных не совпадает с числом недельных заголовков.');
        }
        if (headers.length && numbers.length !== headers.length) {
            issues.push('Число номеров недель не совпадает с числом недельных заголовков.');
        }
        if (numbers.includes(0) && !layout.allow_week_zero) {
            issues.push('В списке есть неделя 0, но её обработка отключена.');
        }
        if (days.length && days.length !== (layout.day_names || []).length) {
            issues.push('Число строк начала дней не совпадает со списком дней недели.');
        }
        if (layout.legend_start_row && !layout.legend_data_start_row) {
            issues.push('Для блока дисциплин не задана первая строка данных.');
        }
        return issues;
    });

    watch(() => schedule.selectedFileId.value, () => { exactPickMode.value = ''; });
    window.addEventListener('pointerdown', captureExactPick, true);
    onBeforeUnmount(() => window.removeEventListener('pointerdown', captureExactPick, true));

    return {
        exactPickMode,
        exactPickModes,
        exactPickHint,
        exactLayoutSummary,
        exactLayoutIssues,
        toggleExactPick,
        cancelExactPick,
        layoutListText,
        setLayoutList,
        setLayoutNumber,
        markExactLayoutDirty
    };
}
