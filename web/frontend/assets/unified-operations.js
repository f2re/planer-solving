const INSTALL_MARK = 'plannerUnifiedOperationsInstalled';
const RUNTIME_MARK = 'plannerUnifiedOperationsRuntime';
const LEGACY_TABS = ['teachers', 'templates', 'spaces'];

function directive(node, name, value) {
    if (node) node.setAttribute(name, value);
}

function managerTabFromModal(modal) {
    const buttons = [...(modal?.querySelectorAll('.manager-tabs button') || [])];
    const index = buttons.findIndex(button => button.classList.contains('active'));
    return LEGACY_TABS[index >= 0 ? index : 0];
}

function managerTabButton(section, tab) {
    const index = LEGACY_TABS.indexOf(tab);
    return section?.querySelectorAll('.manager-tabs button')?.[index >= 0 ? index : 0] || null;
}

/**
 * Переносит каталог преподавателей, шаблонов и пространств в уже существующий
 * Центр операций. Старое модальное окно остаётся только совместимым входом для
 * прежних вызовов openManager() и после монтирования автоматически
 * перенаправляется в единый центр.
 */
export function installUnifiedOperationsMarkup() {
    const root = document.documentElement;
    if (root.dataset[INSTALL_MARK] === '1') return;

    const workspaceButton = document.querySelector('.workspace-switcher button');
    const legacyModal = document.querySelector('.workspace-modal');
    const operationsNav = document.querySelector('.operations-nav');
    const operationsScroll = document.querySelector('.operations-scroll');
    const operationsHeader = document.querySelector('.operations-header');
    if (!workspaceButton || !legacyModal || !operationsNav || !operationsScroll || !operationsHeader) {
        return;
    }
    root.dataset[INSTALL_MARK] = '1';

    workspaceButton.textContent = 'Данные';
    workspaceButton.classList.add('workspace-data-button');
    workspaceButton.setAttribute('title', 'Преподаватели, шаблоны и параметры пространства');
    directive(
        workspaceButton,
        '@click',
        "operationsOpen=true; operationsTab='workspace'; managerTab='teachers'"
    );

    const operationsButton = document.querySelector('.operations-button');
    if (operationsButton) operationsButton.textContent = 'Центр операций';

    const navButton = document.createElement('button');
    navButton.type = 'button';
    navButton.className = 'operations-workspace-nav';
    directive(navButton, 'v-if', 'canOperate');
    directive(navButton, ':class', "{active:operationsTab==='workspace'}");
    directive(
        navButton,
        '@click',
        "operationsTab='workspace'; managerTab='teachers'"
    );
    navButton.innerHTML = '<span>⚙</span><div><b>Данные</b><small>Преподаватели и пространства</small></div>';
    operationsNav.insertBefore(navButton, operationsNav.querySelector('.operations-user'));

    const title = operationsHeader.querySelector('h2');
    const description = operationsHeader.querySelector('p');
    if (title) {
        title.textContent = "{{ operationsTab === 'workspace' ? 'Данные пространства' : activeOperationTab?.name }}";
    }
    if (description) {
        description.textContent = "{{ operationsTab === 'workspace' ? 'Преподаватели, шаблоны и параметры активного пространства.' : activeOperationTab?.description }}";
    }

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

    const tabs = legacyModal.querySelector('.manager-tabs')?.cloneNode(true);
    const content = legacyModal.querySelector('.modal-content')?.cloneNode(true);
    if (!tabs || !content) return;
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
    operationsScroll.appendChild(section);

    const legacyBackdrop = legacyModal.closest('.modal-backdrop');
    legacyBackdrop?.classList.add('legacy-workspace-manager');
}

/**
 * Старые внутренние вызовы openManager() могут сохраняться в сценариях
 * импорта. Наблюдатель закрывает прежнее окно до показа и открывает тот же
 * раздел внутри Центра операций, поэтому оператор всегда видит одно рабочее
 * пространство.
 */
export function installUnifiedOperationsRuntime() {
    const app = document.querySelector('#app');
    if (!app || app.dataset[RUNTIME_MARK] === '1') return;
    app.dataset[RUNTIME_MARK] = '1';

    let redirecting = false;

    const openUnifiedTab = tab => {
        document.querySelector('.workspace-data-button')?.click();
        window.requestAnimationFrame(() => {
            const section = document.querySelector('.operations-workspace-section');
            managerTabButton(section, tab)?.click();
        });
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
        window.setTimeout(() => { redirecting = false; }, 120);
    };

    const observer = new MutationObserver(() => {
        window.requestAnimationFrame(redirectLegacyModal);
    });
    observer.observe(app, { childList: true, subtree: true });

    window.addEventListener('planner:open-workspace-data', event => {
        openUnifiedTab(event.detail?.tab || 'teachers');
    });
}
