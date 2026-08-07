const BRAND_ASSETS = {
    icon: '/assets/brand/app-icon-128.webp',
    hero: '/assets/brand/hero-schedule.webp',
    result: '/assets/brand/organized-flow.webp'
};

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
                    width="1672"
                    height="941"
                    alt="Интерфейс «Борис по парам»: рабочее пространство с расписанием"
                    decoding="async"
                    fetchpriority="high"
                >
            </figure>`);
    }

    const dropIcon = uploadCard.querySelector('.drop-icon');
    if (dropIcon && !dropIcon.querySelector('img')) {
        dropIcon.innerHTML = `<img src="${BRAND_ASSETS.icon}" width="72" height="72" alt="" aria-hidden="true">`;
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
                width="1448"
                height="1086"
                alt="Готовое организованное расписание"
                decoding="async"
            >
        </figure>`);
    return true;
}

function observeBrandScreens(root) {
    if (window.__plannerBrandScreenObserver) return;
    const observer = new MutationObserver(records => {
        for (const record of records) {
            for (const node of record.addedNodes) {
                if (!(node instanceof HTMLElement)) continue;
                decorateStartCard(node);
                decorateResultCard(node);
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
    ensureLink('preload', BRAND_ASSETS.hero, { as: 'image', type: 'image/webp', fetchpriority: 'high' });
    ensureLink('preload', BRAND_ASSETS.result, { as: 'image', type: 'image/webp' });
}

export function installBrandMarkup() {
    const root = document.querySelector('#app');
    if (!root || root.dataset.plannerBrandMarkup === 'ready') return;
    root.dataset.plannerBrandMarkup = 'ready';
    document.body.classList.add('planner-branded');

    const topbar = root.querySelector('.topbar');
    const brand = topbar?.querySelector('.brand');
    if (brand) {
        brand.innerHTML = `
            <span class="brand-mark brand-mark-image" aria-hidden="true">
                <img src="${BRAND_ASSETS.icon}" width="44" height="44" alt="">
            </span>
            <span class="brand-copy">
                <span class="brand-title">Борис по парам</span>
                <span class="brand-subtitle">Работа с расписаниями</span>
            </span>`;
    }
    const version = topbar?.querySelector('.version');
    if (version) version.textContent = 'Рабочее место оператора';

    decorateStartCard(root);
    decorateResultCard(root);
    observeBrandScreens(root);

    // Vue монтируется сразу после этого вызова и заменяет узлы внутри #app.
    // Повтор после текущего стека гарантирует, что стартовая иллюстрация и
    // декоративная иконка добавятся уже в фактически смонтированный DOM.
    queueMicrotask(() => decorateStartCard(root));

    const shell = root.querySelector('.shell');
    shell?.classList.add('brand-shell');
}
