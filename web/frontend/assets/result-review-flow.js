const RESULT_REVIEW_READY = 'resultReviewReady';
const RESULT_REVIEW_RUNTIME_READY = 'resultReviewRuntimeReady';
const BRAND_ASSETS = {
    start: '/assets/brand/hero-schedule.png',
    result: '/assets/brand/organized-flow.png'
};

function ensureStylesheet() {
    if (document.querySelector('link[data-result-review-style]')) return;
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = '/assets/result-review-flow.css';
    link.dataset.resultReviewStyle = '1';
    document.head.appendChild(link);
}

function replaceVueClick(node, expression) {
    if (!node) return;
    const shorthand = [...node.attributes]
        .find(attribute => attribute.name === '@click');
    if (shorthand) node.removeAttributeNode(shorthand);
    node.setAttribute('v-on:click', expression);
}

function ensureIllustration(card, anchor, className, source, alt, width, height) {
    if (!card || !anchor) return false;
    let figure = card.querySelector(`.${className}`);
    if (!figure) {
        figure = document.createElement('figure');
        figure.className = className;
        anchor.insertAdjacentElement('afterend', figure);
    }

    let image = figure.querySelector('img');
    if (!image) {
        image = document.createElement('img');
        figure.appendChild(image);
    }
    image.src = source;
    image.alt = alt;
    image.width = width;
    image.height = height;
    image.decoding = 'async';
    return true;
}

function decorateStartScreen(root = document) {
    const uploadCard = root.matches?.('.upload-card')
        ? root
        : root.querySelector?.('.upload-card');
    if (!uploadCard) return false;
    const header = uploadCard.querySelector('.upload-header');
    return ensureIllustration(
        uploadCard,
        header,
        'brand-hero-visual',
        BRAND_ASSETS.start,
        'Рабочее пространство «Борис по парам» с расписанием',
        600,
        338
    );
}

function decorateResultScreen(root = document) {
    const resultCard = root.matches?.('.result-card')
        ? root
        : root.querySelector?.('.result-card');
    if (!resultCard) return false;
    const hero = resultCard.querySelector('.result-hero');
    return ensureIllustration(
        resultCard,
        hero,
        'result-brand-illustration',
        BRAND_ASSETS.result,
        'Сформированное и проверенное расписание',
        560,
        350
    );
}

function decorateVisibleScreens(root = document) {
    decorateStartScreen(root);
    decorateResultScreen(root);
}

export function installResultReviewMarkup() {
    if (document.documentElement.dataset[RESULT_REVIEW_READY] === '1') return;
    document.documentElement.dataset[RESULT_REVIEW_READY] = '1';

    const returnButton = document.querySelector('.return-to-editor');
    if (returnButton) {
        replaceVueClick(returnButton, 'returnToCorrections()');
        returnButton.textContent = 'Исправить и сформировать заново';
    }

    const fileAction = document.querySelector('.result-file-action');
    if (fileAction) {
        replaceVueClick(
            fileAction,
            'returnToCorrections().then(() => selectFile(detail.file_id))'
        );
    }

    const summary = document.querySelector('.result-compact-summary');
    if (summary) {
        summary.textContent = (
            'Готовые файлы можно скачать сразу. Если нужно что-то изменить, '
            + 'вернитесь к исправлениям — исходники и все настройки сохранятся.'
        );
    }
}

export function installResultReviewRuntime() {
    const root = document.querySelector('#app');
    if (!root || root.dataset[RESULT_REVIEW_RUNTIME_READY] === '1') return;
    root.dataset[RESULT_REVIEW_RUNTIME_READY] = '1';
    ensureStylesheet();
    decorateVisibleScreens(root);

    const observer = new MutationObserver(records => {
        for (const record of records) {
            for (const node of record.addedNodes) {
                if (!(node instanceof HTMLElement)) continue;
                decorateVisibleScreens(node);
            }
        }
    });
    observer.observe(root, { childList: true, subtree: true });
    window.__plannerResultReviewObserver = observer;
}
