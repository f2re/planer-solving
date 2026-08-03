// Pure helpers for normalizing and presenting editable schedule layouts.

export const copyLayout = value => JSON.parse(JSON.stringify(value));
export const numericLayoutValue = value => {
    if (value === '' || value === null || value === undefined) return null;
    const parsed = Number(value);
    return Number.isFinite(parsed) ? Math.trunc(parsed) : null;
};
export const integerList = value => {
    const source = Array.isArray(value)
        ? value
        : String(value ?? '').split(/[;,\s]+/);
    const result = [];
    for (const item of source) {
        const parsed = numericLayoutValue(item);
        if (parsed !== null && !result.includes(parsed)) result.push(parsed);
    }
    return result;
};

export const normalizeScheduleLayout = layout => {
    const value = copyLayout(layout || {});
    [
        'months_row',
        'grid_end_row',
        'teacher_row_offset',
        'legend_start_row',
        'legend_end_row',
        'legend_data_start_row',
        'legend_code_col',
        'legend_subject_col',
        'legend_lecturer_col',
        'legend_other_col'
    ].forEach(key => { value[key] = numericLayoutValue(value[key]); });
    [
        'weeks_row',
        'first_week_col',
        'last_week_col',
        'week_col_step',
        'week_data_col_offset',
        'grid_start_row',
        'day_block_rows',
        'pairs_per_day',
        'pair_row_stride',
        'date_row_offset',
        'code_row_offset',
        'subject_row_offset',
        'room_row_offset',
        'legend_data_start_offset'
    ].forEach(key => { value[key] = Number(value[key] || 0); });
    [
        'week_columns',
        'week_data_columns',
        'week_numbers',
        'day_start_rows',
        'pair_row_offsets'
    ].forEach(key => { value[key] = integerList(value[key]); });
    value.day_names = Array.isArray(value.day_names)
        ? value.day_names.map(item => String(item).trim()).filter(Boolean)
        : String(value.day_names || '').split(',').map(item => item.trim()).filter(Boolean);
    value.allow_week_zero = Boolean(value.allow_week_zero);
    value.teacher_role_fallback = value.teacher_role_fallback === 'any' ? 'any' : 'strict';
    return value;
};

export const columnLetter = number => {
    let value = Number(number);
    let label = '';
    if (!Number.isFinite(value) || value < 1) return '—';
    while (value > 0) {
        value -= 1;
        label = String.fromCharCode(65 + value % 26) + label;
        value = Math.floor(value / 26);
    }
    return label;
};
export const confidenceLabel = confidence => {
    const value = Math.round((confidence || 0) * 100);
    return `${value}% · ${value >= 75 ? 'высокая' : value >= 55 ? 'средняя' : 'низкая'}`;
};
export const confidenceClass = confidence =>
    (confidence || 0) >= 0.75
        ? 'confidence-good'
        : (confidence || 0) >= 0.55
            ? 'confidence-medium'
            : 'confidence-low';

export function buildPreviewBounds(file, layout, region) {
    if (!file || !layout) return null;
    const maxRow = Number(file.analysis?.max_row || 1);
    const maxColumn = Number(file.analysis?.max_column || 1);
    if (region === 'legend') {
        const columns = [
            layout.legend_code_col,
            layout.legend_subject_col,
            layout.legend_lecturer_col,
            layout.legend_other_col
        ].map(numericLayoutValue).filter(Boolean);
        const start = numericLayoutValue(layout.legend_start_row)
            || Number(file.analysis?.legend_preview?.row_start || 1);
        const end = numericLayoutValue(layout.legend_end_row)
            || Number(file.analysis?.legend_preview?.row_end || start);
        return {
            row_start: Math.max(1, start - 2),
            row_end: Math.min(maxRow, end + 2),
            col_start: Math.max(1, Math.min(...(columns.length ? columns : [1])) - 1),
            col_end: Math.min(maxColumn, Math.max(...(columns.length ? columns : [12])) + 2)
        };
    }
    const weekColumns = integerList(layout.week_columns);
    const dataColumns = integerList(layout.week_data_columns);
    const columns = [...weekColumns, ...dataColumns];
    const firstColumn = columns.length ? Math.min(...columns) : Number(layout.first_week_col || 1);
    const lastColumn = columns.length ? Math.max(...columns) : Number(layout.last_week_col || 1);
    const weeksRow = Number(layout.weeks_row || 1);
    const dayRows = integerList(layout.day_start_rows);
    const start = dayRows.length ? Math.min(...dayRows) : Number(layout.grid_start_row || weeksRow + 1);
    const end = numericLayoutValue(layout.grid_end_row)
        || Math.min(maxRow, start + Number(layout.day_block_rows || 13) * (layout.day_names?.length || 6));
    return {
        row_start: Math.max(1, Math.min(weeksRow, start) - 2),
        row_end: Math.min(maxRow, end + 2),
        col_start: Math.max(1, firstColumn - 4),
        col_end: Math.min(maxColumn, lastColumn + 2)
    };
}

function arithmeticColumns(layout) {
    const first = Number(layout.first_week_col || 1);
    const last = Number(layout.last_week_col || first);
    const step = Math.max(1, Number(layout.week_col_step || 1));
    return Array.from(
        { length: Math.max(0, Math.floor((last - first) / step) + 1) },
        (_, index) => first + index * step
    );
}

export function scheduleCellClass(layout, row, cell) {
    if (!layout) return {};
    const rowNumber = Number(row.index);
    const column = Number(cell.column);
    const headerColumns = integerList(layout.week_columns);
    const weekHeaders = new Set(headerColumns.length ? headerColumns : arithmeticColumns(layout));
    const explicitData = integerList(layout.week_data_columns);
    const dataColumns = new Set(
        explicitData.length
            ? explicitData
            : [...weekHeaders].map(value => value + Number(layout.week_data_col_offset || 0))
    );
    const explicitDays = integerList(layout.day_start_rows);
    const dayRows = explicitDays.length
        ? explicitDays
        : (layout.day_names || []).map((_, index) =>
            Number(layout.grid_start_row) + index * Number(layout.day_block_rows || 13)
        );
    const explicitPairs = integerList(layout.pair_row_offsets);
    const pairOffsets = explicitPairs.length
        ? explicitPairs
        : Array.from(
            { length: Number(layout.pairs_per_day || 4) },
            (_, index) => index * Number(layout.pair_row_stride || 3)
        );
    const pairBases = dayRows.flatMap(day => pairOffsets.map(offset => day + offset));
    const isGridColumn = dataColumns.has(column);
    const gridStart = Number(layout.grid_start_row || 1);
    const gridEnd = Number(layout.grid_end_row || 999999);
    const legendStart = Number(layout.legend_start_row || 0);
    const legendEnd = Number(layout.legend_end_row || 0);
    const legendData = Number(layout.legend_data_start_row || 0);
    return {
        'cell-merged': cell.merged,
        'cell-week': rowNumber === Number(layout.weeks_row) && weekHeaders.has(column),
        'cell-week-data': rowNumber === Number(layout.weeks_row) && dataColumns.has(column),
        'cell-grid': rowNumber >= gridStart && rowNumber <= gridEnd && isGridColumn,
        'cell-day-start': dayRows.includes(rowNumber) && isGridColumn,
        'cell-code-row': pairBases.some(base => rowNumber === base + Number(layout.code_row_offset || 0)) && isGridColumn,
        'cell-subject-row': pairBases.some(base => rowNumber === base + Number(layout.subject_row_offset || 0)) && isGridColumn,
        'cell-room-row': pairBases.some(base => rowNumber === base + Number(layout.room_row_offset || 0)) && isGridColumn,
        'cell-legend': Boolean(legendStart && rowNumber >= legendStart && rowNumber <= (legendEnd || 999999)),
        'cell-legend-data': Boolean(legendData && rowNumber >= legendData && rowNumber <= (legendEnd || 999999))
    };
}
