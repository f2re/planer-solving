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
