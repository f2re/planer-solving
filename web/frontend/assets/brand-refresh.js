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

function featureIcon(kind) {
    const paths = {
        files: '<path d="M6 3.5h7l4 4V20.5H6z"/><path d="M13 3.5v4h4M9 12h5M9 15.5h5"/>',
        sparkle: '<path d="M12 2.8l1.8 5.4 5.4 1.8-5.4 1.8-1.8 5.4-1.8-5.4L4.8 10l5.4-1.8z"/><path d="M18.2 15.7l.8 2.3 2.2.8-2.2.8-.8 2.2-.8-2.2-2.3-.8 2.3-.8z"/>',
        edit: '<path d="M4.5 19.5l4.2-1 9.9-9.9-3.2-3.2-9.9 9.9z"/><path d="M13.8 7l3.2 3.2M4.5 19.5h15"/>'
    };
    return `<svg viewBox="0 0 24 24" aria-hidden="true">${paths[kind]}</svg>`;
}

export function installBrandMetadata() {
    if (document.documentElement.dataset.plannerBrandMetadata === 'ready') return;
    document.documentElement.dataset.plannerBrandMetadata = 'ready';

    document.title = 'Planner Solving — интеллектуальный разбор расписаний';
    ensureMeta('meta[name="description"]', {
        name: 'description',
        content: 'Planner Solving разбирает разнородные расписания Excel, исправляет структуру и формирует сводный и недельный результат.'
    });
    ensureMeta('meta[name="theme-color"]', { name: 'theme-color', content: '#315efb' });
    ensureMeta('meta[name="color-scheme"]', { name: 'color-scheme', content: 'light' });
    ensureMeta('meta[name="application-name"]', { name: 'application-name', content: 'Planner Solving' });
    ensureMeta('meta[name="apple-mobile-web-app-capable"]', { name: 'apple-mobile-web-app-capable', content: 'yes' });
    ensureMeta('meta[name="apple-mobile-web-app-title"]', { name: 'apple-mobile-web-app-title', content: 'Planner Solving' });
    ensureMeta('meta[property="og:title"]', { property: 'og:title', content: 'Planner Solving — интеллектуальный разбор расписаний' });
    ensureMeta('meta[property="og:description"]', {
        property: 'og:description',
        content: 'Из разнородных Excel-файлов — в проверенное сводное расписание с локальными исправлениями оператора.'
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
                <span class="brand-title">Planner Solving</span>
                <span class="brand-subtitle">Расписание без ручной переделки Excel</span>
            </span>`;
    }
    const version = topbar?.querySelector('.version');
    if (version) version.textContent = 'Интеллектуальное рабочее место оператора';

    const uploadCard = root.querySelector('.upload-card');
    const uploadHeader = uploadCard?.querySelector('.upload-header');
    if (uploadHeader && !uploadHeader.querySelector('.brand-kicker')) {
        uploadHeader.insertAdjacentHTML('afterbegin', `
            <div class="brand-kicker">
                <span class="brand-kicker-mark">✦</span>
                Неблокирующий разбор расписаний
            </div>`);
        uploadHeader.insertAdjacentHTML('beforeend', `
            <div class="brand-feature-list" aria-label="Ключевые возможности">
                <span>${featureIcon('files')}Несколько форматов Excel</span>
                <span>${featureIcon('sparkle')}Авторазбор и восстановление</span>
                <span>${featureIcon('edit')}Правки прямо в интерфейсе</span>
            </div>`);
    }
    if (uploadHeader && !uploadCard.querySelector('.brand-hero-visual')) {
        uploadHeader.insertAdjacentHTML('afterend', `
            <figure class="brand-hero-visual">
                <img
                    src="${BRAND_ASSETS.hero}"
                    width="1672"
                    height="941"
                    alt="Интерфейс Planner Solving: исходные таблицы преобразуются в организованное расписание"
                    decoding="async"
                    fetchpriority="high"
                >
                <figcaption>
                    <span class="brand-hero-status" aria-hidden="true">✓</span>
                    <span><strong>От исходных книг к готовому результату</strong><small>Все изображения и интерфейс доступны полностью офлайн.</small></span>
                </figcaption>
            </figure>`);
    }

    const dropIcon = uploadCard?.querySelector('.drop-icon');
    if (dropIcon) {
        dropIcon.innerHTML = `<img src="${BRAND_ASSETS.icon}" width="72" height="72" alt="" aria-hidden="true">`;
    }

    const resultCard = root.querySelector('.result-card');
    const resultHero = resultCard?.querySelector('.result-hero');
    if (resultHero && !resultCard.querySelector('.result-brand-illustration')) {
        resultHero.insertAdjacentHTML('afterend', `
            <figure class="result-brand-illustration">
                <img
                    src="${BRAND_ASSETS.result}"
                    width="1448"
                    height="1086"
                    alt="Разрозненные данные превращаются в организованное календарное расписание"
                    loading="lazy"
                    decoding="async"
                >
            </figure>`);
    }

    const shell = root.querySelector('.shell');
    shell?.classList.add('brand-shell');
}
