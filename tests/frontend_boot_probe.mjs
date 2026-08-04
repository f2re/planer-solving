import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';

const sourcePath = resolve('web/frontend/assets/app.js');
const original = await readFile(sourcePath, 'utf8');
const source = original.replace(
    /import\((['"])(\/assets\/[^'"]+)\1\)/g,
    '__plannerImport($1$2$1)'
);

let mounted = 0;
let startupError = null;
const warnings = [];
const listeners = new Map();

function element(tagName = 'div') {
    return {
        tagName: tagName.toUpperCase(),
        id: '',
        type: '',
        rel: '',
        href: '',
        textContent: '',
        style: {},
        dataset: {},
        children: [],
        setAttribute() {},
        addEventListener() {},
        append(...nodes) { this.children.push(...nodes); },
        remove() {
            if (this.id === 'planner-startup-error') startupError = null;
        }
    };
}

globalThis.document = {
    querySelector() { return null; },
    createElement: element,
    getElementById(id) {
        return id === 'planner-startup-error' ? startupError : null;
    },
    head: { appendChild() {} },
    body: {
        appendChild(node) {
            if (node.id === 'planner-startup-error') startupError = node;
        }
    }
};

globalThis.window = {
    addEventListener(type, handler) { listeners.set(type, handler); },
    removeEventListener(type) { listeners.delete(type); },
    setTimeout() { return 1; },
    clearTimeout() {},
    location: { reload() {} }
};

globalThis.console = {
    ...console,
    warn(...args) { warnings.push(args.map(String).join(' ')); },
    error() {}
};

const modules = new Map([
    ['/assets/brand-refresh.js', {
        installBrandMetadata() {},
        installBrandMarkup() {}
    }],
    ['/assets/operator-flow.js', {
        installOperatorFlowMarkup() {},
        installOperatorFlowRuntime() { throw new Error('operator runtime probe'); }
    }],
    ['/assets/planner-app.js', {
        mount() { mounted += 1; }
    }],
    ['/assets/session-draft-runtime.js', {
        installSessionDraftRuntime() { throw new Error('draft runtime probe'); }
    }],
    ['/assets/unified-operations.js', {
        installUnifiedOperationsRuntime() { throw new Error('unified runtime probe'); }
    }],
    ['/assets/failure-recovery.js', { installFailureRecovery() {} }],
    ['/assets/fetch-recovery.js', { installFetchRecovery() {} }],
    ['/assets/ui-runtime-fixes.js', { installPasswordInputPolicy() {} }]
]);

function __plannerImport(path) {
    if (!modules.has(path)) return Promise.reject(new Error(`unexpected import: ${path}`));
    return Promise.resolve(modules.get(path));
}

new Function('__plannerImport', source)(__plannerImport);
await new Promise(resolveWait => setTimeout(resolveWait, 30));

assert.equal(mounted, 1, 'the critical Vue application must mount once');
assert.equal(window.__plannerSolvingBoot.mounted, true, 'boot must be marked mounted before optional runtimes');
assert.equal(startupError, null, 'optional runtime failures must not display the fatal startup screen');
assert.ok(
    window.__plannerSolvingBoot.optionalFailures.some(item => item.label === 'unified operations runtime'),
    'unified operations failure must be retained for diagnostics'
);
assert.ok(
    warnings.some(message => message.includes('unified operations runtime failed and was disabled')),
    'optional failure must be logged'
);

console.log('frontend boot probe: ok');
