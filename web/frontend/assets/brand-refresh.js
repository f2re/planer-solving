const BRAND_ASSETS = {
    icon: '/assets/brand/app-icon-128.png',
    hero: '/assets/brand/hero-schedule.png',
    result: '/assets/brand/organized-flow.png'
};

const UX_STYLESHEET = '/assets/ux-flow-2-26.css';

function ensureMeta(selector, attributes) {
    let node = document.head.querySelector(selector);
    if (!node) {
        node = document.createElement('meta');
        document.head.appendChild(node);
    }
    Object.entries(attributes).forEach(([name, value]) => node.setAttribute(name, value));
    return node;
}

function ensureLink(rel, href, attributes = {}) {
    let node = [...document.head.querySelectorAll(`link[rel="${rel}"]`)]
        .find(item => item.getAttribute('href') === href);
    if (!node) {
        node = document.createElement('link');
        node.rel = rel;
        node.href = href;
        document.head.appendChild(node);
    }
    Object.entries(attributes).forEach(([name, value]) => node.setAttribute(name, value));
    return node;
}

function ensureUxStylesheet(bringToFront = false) {
    const link = ensureLink('stylesheet', UX_STYLESHEET, { 'data-planner-ux': '2.26' });
    // result-review-flow.css is connected after Vue mount. When the result screen
    // first appears, keep the UX hierarchy stylesheet last so its action layout
    // cannot be undone by an older compatibility layer.
    if (bringToFront && link.parentNode === document.head && link !== document.head.lastElementChild) {
        document.head.appendChild(link);
    }
    return link;
}

function decorateChrome(root = document) {
    const topbar = root.matches?.('.topbar') ? root : root.querySelector?.('.topbar');
    const brand = topbar?.querySelector('.brand');
    if (brand && !brand.querySelector('.brand-mark-image')) {
        brand.innerHTML = `
            <span class="brand-mark brand-mark-image" aria-hidden="true">
                <img src="${BRAND_ASSETS.icon}" width="128" height="128" alt="">
            </span>
            <span class="brand-copy">
                <span class="brand-title">Борис по парам</span>
                <span class="brand-subtitle">Работа с расписаниями</span>
            </span>`;
    }
    const version = topbar?.querySelector('.version');
    if (version) version.textContent = 'Рабочее место оператора';
}

function decorateStartCard(root = document) {
    const uploadCard = root.matches?.('.upload-card')
        ? root
        : root.querySelector?.('.upload-card');
    if (!uploadCard) return false;

    const uploadHeader = uploadCard.querySelector('.upload-header');
    uploadHeader?.querySelector('.brand-kicker')?.remove();
    uploadHeader?.querySelector('.brand-feature-list')?.remove();

    if (uploadHeader && !uploadCard.querySelector('.brand-hero-visual')) {
        uploadHeader.insertAdjacentHTML('afterend', `
            <figure class="brand-hero-visual">
                <img
                    src="${BRAND_ASSETS.hero}"
                    width="600"
                    height="338"
                    alt="Интерфейс «Борис по парам»: рабочее пространство с расписанием"
                    decoding="async"
                    fetchpriority="high"
                >
            </figure>`);
    }

    const dropIcon = uploadCard.querySelector('.drop-icon');
    if (dropIcon && !dropIcon.querySelector('img')) {
        dropIcon.innerHTML = `<img src="${BRAND_ASSETS.icon}" width="128" height="128" alt="" aria-hidden="true">`;
    }
    return Boolean(uploadCard.querySelector('.brand-hero-visual'));
}

function decorateResultCard(root = document) {
    const resultCard = root.matches?.('.result-card')
        ? root
        : root.querySelector?.('.result-card');
    if (!resultCard || resultCard.querySelector('.result-brand-illustration')) return false;
    const resultHero = resultCard.querySelector('.result-hero');
    if (!resultHero) return false;
    resultHero.insertAdjacentHTML('afterend', `
        <figure class="result-brand-illustration">
            <img
                src="${BRAND_ASSETS.result}"
                width="560"
                height="350"
                alt="Готовое организованное расписание"
                decoding="async"
            >
        </figure>`);
    return true;
}

function directButtonRow(card) {
    if (!card) return null;
    return [...card.children].find(node => node.classList?.contains('button-row')) || null;
}

function normalizeWorkflowActions(root = document) {
    const bottom = root.matches?.('.bottom-actions')
        ? root
        : root.querySelector?.('.bottom-actions');
    if (!bottom) return false;

    const primary = bottom.querySelector('.btn-primary');
    if (primary) primary.classList.add('bottom-duplicate-primary');

    for (const button of bottom.querySelectorAll('button.btn-secondary')) {
        const label = button.textContent.trim();
        if (label.includes('Проверить') || label.includes('Перепроверить')) {
            button.classList.add('secondary-validate-action');
            button.textContent = 'Перепроверить файлы';
        } else if (label.includes('Начать заново') || label.includes('Очистить')) {
            button.classList.add('session-clear-action');
            button.textContent = 'Очистить сеанс';
        }
    }
    return true;
}

function normalizeResultActions(root = document) {
    const card = root.matches?.('.result-card') ? root : root.querySelector?.('.result-card');
    if (!card) return false;
    ensureUxStylesheet(true);

    const actions = card.querySelector('.result-actions') || directButtonRow(card);
    const hero = card.querySelector('.result-hero');
    if (!actions || !hero) return false;
    actions.classList.add('result-actions', 'result-action-hierarchy');

    for (const anchor of actions.querySelectorAll('a.btn')) {
        if (anchor.classList.contains('btn-primary')) {
            anchor.classList.add('result-download-primary');
            if (anchor.textContent.includes('общее')) anchor.textContent = 'Скачать расписание';
        } else {
            anchor.classList.add('result-download-secondary');
            if (anchor.textContent.includes('недельное')) anchor.textContent = 'Скачать недельное';
        }
    }

    for (const button of actions.querySelectorAll('button')) {
        const label = button.textContent.trim();
        if (button.classList.contains('return-to-editor') || label.includes('Вернуться к исправлениям') || label === 'К исправлениям') {
            button.classList.add('result-back-trigger');
        } else if (label.includes('История')) {
            button.classList.add('result-tertiary-action', 'result-history-action');
            button.textContent = 'История формирования';
        } else if (label.includes('Новые файлы') || label.includes('Обработать новые')) {
            button.classList.add('result-tertiary-action', 'result-new-files-action');
            button.textContent = 'Новые файлы';
        }
    }

    if (!card.querySelector('.result-back-nav')) {
        const back = document.createElement('button');
        back.type = 'button';
        back.className = 'result-back-nav';
        back.textContent = '← К исправлениям';
        back.setAttribute('aria-label', 'Вернуться к исправлениям расписания');
        back.addEventListener('click', () => {
            const triggers = [...card.querySelectorAll('.result-back-trigger')];
            const preferred = triggers.find(node => node.classList.contains('return-to-editor')) || triggers[0];
            preferred?.click();
        });
        hero.insertAdjacentElement('beforebegin', back);
    }
    return true;
}

function decorateVisibleScreens(root = document) {
    decorateChrome(root);
    decorateStartCard(root);
    decorateResultCard(root);
    normalizeWorkflowActions(root);
    normalizeResultActions(root);
}

function observeBrandScreens(root) {
    if (window.__plannerBrandScreenObserver) return;
    const observer = new MutationObserver(records => {
        for (const record of records) {
            for (const node of record.addedNodes) {
                if (!(node instanceof HTMLElement)) continue;
                decorateVisibleScreens(node);
            }
        }
    });
    observer.observe(root, { childList: true, subtree: true });
    window.__plannerBrandScreenObserver = observer;
}

export function installBrandMetadata() {
    if (document.documentElement.dataset.plannerBrandMetadata === 'ready') return;
    document.documentElement.dataset.plannerBrandMetadata = 'ready';

    document.title = 'Борис по парам — разбор расписаний';
    ensureMeta('meta[name="description"]', {
        name: 'description',
        content: 'Борис по парам разбирает расписания Excel и формирует сводный и недельный результат.'
    });
    ensureMeta('meta[name="theme-color"]', { name: 'theme-color', content: '#315efb' });
    ensureMeta('meta[name="color-scheme"]', { name: 'color-scheme', content: 'light' });
    ensureMeta('meta[name="application-name"]', { name: 'application-name', content: 'Борис по парам' });
    ensureMeta('meta[name="apple-mobile-web-app-capable"]', { name: 'apple-mobile-web-app-capable', content: 'yes' });
    ensureMeta('meta[name="apple-mobile-web-app-title"]', { name: 'apple-mobile-web-app-title', content: 'Борис по парам' });
    ensureMeta('meta[property="og:title"]', { property: 'og:title', content: 'Борис по парам — разбор расписаний' });
    ensureMeta('meta[property="og:description"]', {
        property: 'og:description',
        content: 'Из Excel-файлов в проверенное сводное расписание.'
    });
    ensureMeta('meta[property="og:type"]', { property: 'og:type', content: 'website' });
    ensureMeta('meta[property="og:image"]', {
        property: 'og:image',
        content: new URL(BRAND_ASSETS.hero, window.location.origin).href
    });

    ensureLink('icon', '/favicon.svg', { type: 'image/svg+xml' });
    ensureLink('alternate icon', '/favicon.ico', { type: 'image/x-icon' });
    ensureLink('manifest', '/site.webmanifest');
    ensureLink('preload', BRAND_ASSETS.hero, { as: 'image', type: 'image/png', fetchpriority: 'high' });
    ensureLink('preload', BRAND_ASSETS.result, { as: 'image', type: 'image/png' });
    ensureUxStylesheet();
}

export function installBrandMarkup() {
    const root = document.querySelector('#app');
    if (!root || root.dataset.plannerBrandMarkup === 'ready') return;
    root.dataset.plannerBrandMarkup = 'ready';
    document.body.classList.add('planner-branded');

    decorateVisibleScreens(root);
    observeBrandScreens(root);

    // Vue replaces the initial children of #app during mount. Re-run the small
    // idempotent decorators after the current task so branding and UX hierarchy
    // are attached to the actual mounted DOM rather than the discarded template.
    queueMicrotask(() => decorateVisibleScreens(root));

    const shell = root.querySelector('.shell');
    shell?.classList.add('brand-shell');
}
