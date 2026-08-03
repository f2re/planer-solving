let passwordObserver = null;

const PASSWORD_SELECTOR = '.auth-form input[type="password"], .user-form input[type="password"]';
const PASSWORD_PLACEHOLDER = 'Можно оставить пустым';
const PASSWORD_DESCRIPTION = 'Ограничений по длине пароля нет';

function relaxPasswordInput(input) {
    if (!input || typeof input.matches !== 'function' || !input.matches(PASSWORD_SELECTOR)) return;

    // Удаляем только реально существующие ограничения. Нельзя присваивать
    // свойству minLength нулевое значение: оно снова создаёт одноимённый
    // атрибут и при наблюдении запускает бесконечный цикл MutationObserver.
    for (const attribute of ['required', 'minlength', ':required', 'v-bind:required']) {
        if (input.hasAttribute(attribute)) input.removeAttribute(attribute);
    }
    if (input.getAttribute('placeholder') !== PASSWORD_PLACEHOLDER) {
        input.setAttribute('placeholder', PASSWORD_PLACEHOLDER);
    }
    if (input.getAttribute('aria-description') !== PASSWORD_DESCRIPTION) {
        input.setAttribute('aria-description', PASSWORD_DESCRIPTION);
    }
}

function relaxPasswordInputs(root = document) {
    if (!root) return;
    if (typeof root.matches === 'function') relaxPasswordInput(root);
    if (typeof root.querySelectorAll === 'function') {
        root.querySelectorAll(PASSWORD_SELECTOR).forEach(relaxPasswordInput);
    }
}

export function installPasswordInputPolicy() {
    relaxPasswordInputs(document);
    if (passwordObserver) return () => passwordObserver?.disconnect();

    passwordObserver = new MutationObserver(records => {
        for (const record of records) {
            if (record.type === 'attributes') {
                relaxPasswordInput(record.target);
                continue;
            }
            for (const node of record.addedNodes || []) relaxPasswordInputs(node);
        }
    });
    passwordObserver.observe(document.documentElement, {
        subtree: true,
        childList: true,
        attributes: true,
        attributeFilter: ['required', 'minlength']
    });
    return () => {
        passwordObserver?.disconnect();
        passwordObserver = null;
    };
}

export function applyEditorRuntimeFixes(editor, schedule, interaction, platform, addToast) {
    let rowAnchor = null;

    editor.selectSheetRow = (row, event = {}) => {
        const current = Number(row);
        const start = event.shiftKey && rowAnchor !== null ? rowAnchor : current;
        if (!event.shiftKey) rowAnchor = current;
        const preview = schedule.preview.value;
        const layout = schedule.currentLayout.value;
        if (!preview || !layout) return;
        const selected = {
            rowStart: Math.min(start, current),
            rowEnd: Math.max(start, current),
            colStart: Number(preview.col_start || 1),
            colEnd: Number(preview.col_end || 1)
        };
        interaction.selectedRange.value = selected;
        switch (interaction.selectionMode.value) {
            case 'weeks':
                layout.weeks_row = selected.rowStart;
                break;
            case 'months':
                layout.months_row = selected.rowStart;
                break;
            case 'legend':
                layout.legend_start_row = selected.rowStart;
                layout.legend_end_row = selected.rowEnd;
                break;
            default:
                layout.grid_start_row = selected.rowStart;
                layout.grid_end_row = selected.rowEnd;
        }
        schedule.markDirty();
    };

    const originalClearPassword = editor.clearUserPassword;
    editor.clearUserPassword = async () => {
        const user = platform.userForm;
        if (!user?.id) return;
        if (!confirm(`Сбросить пароль пользователя «${user.display_name || user.username}» на пустой?`)) return;
        try {
            await axios.post(`/api/admin/users/${user.id}/reset-password`, { password: '' });
            platform.userForm.password = '';
            if (user.id === platform.currentUser.value?.id) {
                platform.operationsOpen.value = false;
                await platform.initAuth();
                addToast(
                    'Пароль сброшен',
                    'Пароль стал пустым. Текущий сеанс закрыт; войдите снова только с логином.',
                    'success'
                );
                return;
            }
            platform.platformUsers.value = (await axios.get('/api/admin/users')).data.users;
            addToast('Пароль сброшен', 'Теперь пользователь может войти с пустым паролем.', 'success');
        } catch (error) {
            if (typeof originalClearPassword === 'function' && error.response?.status === 404) {
                return originalClearPassword();
            }
            addToast('Сброс пароля', error.response?.data?.detail || 'Пароль не сброшен.', 'error');
        }
    };
}
