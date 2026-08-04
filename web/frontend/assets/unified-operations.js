const INSTALL_MARK = 'plannerUnifiedOperationsInstalled';
const RUNTIME_MARK = 'plannerUnifiedOperationsRuntime';
const LEGACY_TABS = ['teachers', 'templates', 'spaces'];

function directive(node, name, value) {
    if (node) node.setAttribute(name, value);
}

function reportFailure(stage, error) {
    console.warn(`[planner] unified operations ${stage} was disabled`, error);
    try {
        if (typeof CustomEvent === 'function' && typeof window.dispatchEvent === 'function') {
            window.dispatchEvent(new CustomEvent('planner:optional-module-failure', {
                detail: {
                    module: 'unified-operations',
                    stage,
                    message: String(error?.message || error || 'unknown error')
                }
            }));
        }
    } catch (_) {
        // Diagnostics must never become a second startup failure.
    }
}

function managerTabFromModal(modal) {
    const buttons = Array.from(modal?.querySelectorAll('.manager-tabs button') || []);
    const index = buttons.findIndex(button => button.classList.contains('active'));
    return LEGACY_TABS[index >= 0 ? index : 0];
}

function managerTabButton(section, tab) {
    const buttons = section ? section.querySelectorAll('.manager-tabs button') : [];
    const index = LEGACY_TABS.indexOf(tab);
    return buttons[index >= 0 ? index : 0] || null;
}

/**
 * Переносит каталог преподавателей, шаблонов и пространств в уже существующий
 * Центр операций. Все обязательные узлы сначала проверяются и клонируются в
 * памяти. Поэтому неполная или устаревшая разметка не остаётся наполовину
 * изменённой и не мешает запуску основного интерфейса.
 */
export function installUnifiedOperationsMarkup() {
    const root = document.documentElement;
    if (root.dataset[INSTALL_MARK] === '1') return true;

    try {
        const workspaceButton = document.querySelector('.workspace-switcher button');
        const legacyModal = document.querySelector('.workspace-modal');
        const operationsNav = document.querySelector('.operations-nav');
        const operationsScroll = document.querySelector('.operations-scroll');
        const operationsHeader = document.querySelector('.operations-header');
        const tabsSource = legacyModal?.querySelector('.manager-tabs');
        const contentSource = legacyModal?.querySelector('.modal-content');

        if (
            !workspaceButton || !legacyModal || !operationsNav ||
            !operationsScroll || !operationsHeader || !tabsSource || !contentSource
        ) {
            return false;
        }

        const navButton = document.createElement('button');
        navButton.type = 'button';
        navButton.className = 'operations-workspace-nav';
        directive(navButton, 'v-if', 'canOperate');
        directive(navButton, ':class', "{active:operationsTab==='workspace'}");
        directive(navButton, '@click', "operationsTab='workspace'; managerTab='teachers'");
        navButton.innerHTML = '<span>⚙</span><div><b>Данные</b><small>Преподаватели и пространства</small></div>';

        const section = document.createElement('section');
        section.className = 'operations-section operations-workspace-section';
        directive(section, 'v-else-if', "operationsTab==='workspace'");

        const intro = document.createElement('div');
        intro.className = 'operations-workspace-intro';
        intro.innerHTML = [
            '<div><b>Единый каталог пространства</b>',
            '<small>Изменения сразу применяются к текущему пространству. Исходные файлы и ручная разметка активного сеанса сохраняются.</small></div>',
            '<button type="button" class="btn btn-secondary btn-small" @click="openOperations(\'import\', managerTab === \'templates\' ? \'templates\' : \'teachers\')">Мастер импорта</button>'
        ].join('');
        section.appendChild(intro);

        const tabs = tabsSource.cloneNode(true);
        const content = contentSource.cloneNode(true);
        tabs.classList.add('operations-workspace-tabs');
        content.classList.add('operations-workspace-content');
        const clonedTabButtons = tabs.querySelectorAll('button');
        if (clonedTabButtons[2]) {
            directive(
                clonedTabButtons[2],
                '@click',
                "managerTab='spaces'; editWorkspace(activeWorkspace)"
            );
        }
        section.append(tabs, content);

        // Изменение живой DOM выполняется только после полной подготовки.
        workspaceButton.textContent = 'Данные';
        workspaceButton.classList.add('workspace-data-button');
        workspaceButton.setAttribute(
            'title',
            'Преподаватели, шаблоны и параметры пространства'
        );
        directive(
            workspaceButton,
            '@click',
            "operationsOpen=true; operationsTab='workspace'; managerTab='teachers'"
        );

        const operationsButton = document.querySelector('.operations-button');
        if (operationsButton) operationsButton.textContent = 'Центр операций';

        operationsNav.insertBefore(
            navButton,
            operationsNav.querySelector('.operations-user')
        );
        operationsScroll.appendChild(section);

        const title = operationsHeader.querySelector('h2');
        const description = operationsHeader.querySelector('p');
        if (title) {
            title.textContent = "{{ operationsTab === 'workspace' ? 'Данные пространства' : activeOperationTab?.name }}";
        }
        if (description) {
            description.textContent = "{{ operationsTab === 'workspace' ? 'Преподаватели, шаблоны и параметры активного пространства.' : activeOperationTab?.description }}";
        }

        legacyModal.closest('.modal-backdrop')?.classList.add('legacy-workspace-manager');
        root.dataset[INSTALL_MARK] = '1';
        return true;
    } catch (error) {
        reportFailure('markup', error);
        return false;
    }
}

/**
 * Старые внутренние вызовы openManager() перенаправляются в единый центр.
 * Наблюдатель считается необязательным улучшением и никогда не должен
 * препятствовать загрузке страницы.
 */
export function installUnifiedOperationsRuntime() {
    const app = document.querySelector('#app');
    if (!app || app.dataset[RUNTIME_MARK] === '1') return null;

    try {
        let redirecting = false;
        let resetTimer = null;

        const openUnifiedTab = tab => {
            const button = document.querySelector('.workspace-data-button');
            if (!button) return false;
            button.click();
            window.requestAnimationFrame(() => {
                const section = document.querySelector('.operations-workspace-section');
                managerTabButton(section, tab)?.click();
            });
            return true;
        };

        const redirectLegacyModal = () => {
            if (redirecting) return;
            const backdrop = document.querySelector('.legacy-workspace-manager');
            const modal = backdrop?.querySelector('.workspace-modal');
            if (!backdrop || !modal) return;

            redirecting = true;
            const tab = managerTabFromModal(modal);
            modal.querySelector('.modal-close')?.click();
            window.requestAnimationFrame(() => openUnifiedTab(tab));
            window.clearTimeout(resetTimer);
            resetTimer = window.setTimeout(() => {
                redirecting = false;
            }, 120);
        };

        const observer = new MutationObserver(() => {
            window.requestAnimationFrame(() => {
                try {
                    redirectLegacyModal();
                } catch (error) {
                    reportFailure('redirect', error);
                }
            });
        });
        observer.observe(app, { childList: true, subtree: true });

        const openHandler = event => {
            try {
                openUnifiedTab(event.detail?.tab || 'teachers');
            } catch (error) {
                reportFailure('event', error);
            }
        };
        window.addEventListener('planner:open-workspace-data', openHandler);
        app.dataset[RUNTIME_MARK] = '1';

        return () => {
            observer.disconnect();
            window.clearTimeout(resetTimer);
            window.removeEventListener('planner:open-workspace-data', openHandler);
            delete app.dataset[RUNTIME_MARK];
        };
    } catch (error) {
        reportFailure('runtime', error);
        return null;
    }
}
