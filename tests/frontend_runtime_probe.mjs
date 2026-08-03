import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const sourcePath = resolve('web/frontend/assets/ui-runtime-fixes.js');
const source = await readFile(sourcePath, 'utf8');
const pending = [];
let activeObserver = null;
let observerCount = 0;

function scheduleMutation(target, attributeName) {
    if (!activeObserver || !activeObserver.options?.attributes) return;
    if (activeObserver.options.attributeFilter && !activeObserver.options.attributeFilter.includes(attributeName)) return;
    pending.push(() => activeObserver.callback([{ type: 'attributes', target, attributeName }]));
}

class MockPasswordInput {
    constructor() {
        this.attributes = new Map([
            ['required', ''],
            ['minlength', '10']
        ]);
    }
    matches(selector) {
        return selector.includes('input[type="password"]');
    }
    querySelectorAll() {
        return [];
    }
    hasAttribute(name) {
        return this.attributes.has(name);
    }
    getAttribute(name) {
        return this.attributes.has(name) ? this.attributes.get(name) : null;
    }
    setAttribute(name, value) {
        const normalized = String(value);
        if (this.attributes.get(name) === normalized) return;
        this.attributes.set(name, normalized);
        scheduleMutation(this, name);
    }
    removeAttribute(name) {
        if (!this.attributes.delete(name)) return;
        scheduleMutation(this, name);
    }
    set minLength(value) {
        this.setAttribute('minlength', String(value));
    }
    get minLength() {
        return Number(this.getAttribute('minlength') ?? -1);
    }
    set required(value) {
        if (value) this.setAttribute('required', '');
        else this.removeAttribute('required');
    }
}

class MockMutationObserver {
    constructor(callback) {
        this.callback = callback;
        this.options = null;
        observerCount += 1;
    }
    observe(_root, options) {
        this.options = options;
        activeObserver = this;
    }
    disconnect() {
        if (activeObserver === this) activeObserver = null;
    }
}

const input = new MockPasswordInput();
const documentElement = {
    querySelectorAll() {
        return [input];
    }
};
globalThis.document = {
    documentElement,
    querySelectorAll() {
        return [input];
    }
};
globalThis.MutationObserver = MockMutationObserver;
globalThis.window = { setTimeout, clearTimeout };
globalThis.queueMicrotask = callback => pending.push(callback);

const moduleUrl = `data:text/javascript;base64,${Buffer.from(source).toString('base64')}`;
const runtime = await import(moduleUrl);
const disconnect = runtime.installPasswordInputPolicy();

assert.equal(input.hasAttribute('required'), false, 'required must be removed');
assert.equal(input.hasAttribute('minlength'), false, 'minlength must be removed');
assert.equal(input.getAttribute('placeholder'), 'Можно оставить пустым');
assert.equal(observerCount, 1, 'only one observer must be installed');

// Reproduce Vue adding a dynamic required/minlength attribute after mount.
input.setAttribute('required', '');
input.setAttribute('minlength', '10');
let iterations = 0;
while (pending.length && iterations < 50) {
    pending.shift()();
    iterations += 1;
}
assert.equal(pending.length, 0, 'MutationObserver queue must stabilize');
assert.ok(iterations < 10, `observer required too many callbacks: ${iterations}`);
assert.equal(input.hasAttribute('required'), false);
assert.equal(input.hasAttribute('minlength'), false);

runtime.installPasswordInputPolicy();
assert.equal(observerCount, 1, 'repeated installation must be idempotent');
disconnect();
console.log('frontend runtime probe: ok');
