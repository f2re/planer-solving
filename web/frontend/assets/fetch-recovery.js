let installed = false;
let originalFetch = null;

function requestUrl(input) {
    if (typeof input === 'string') return input;
    if (input instanceof URL) return input.toString();
    return String(input?.url || '');
}

function plannerApiPath(url) {
    try {
        const parsed = new URL(url, window.location.href);
        if (parsed.origin !== window.location.origin || !parsed.pathname.startsWith('/api/')) return '';
        return parsed.pathname;
    } catch (_) {
        return '';
    }
}

function cloneableRequest(input, init = {}) {
    const url = requestUrl(input);
    if (!url || input instanceof Request) return null;
    const body = init.body;
    if (body !== undefined && body !== null && typeof body !== 'string') return null;
    return {
        transport: 'fetch',
        input: url,
        init: {
            method: init.method,
            headers: init.headers,
            body,
            credentials: init.credentials,
            cache: init.cache,
            keepalive: init.keepalive,
        },
    };
}

export function installFetchRecovery() {
    if (installed || typeof window.fetch !== 'function') return;
    installed = true;
    originalFetch = window.fetch.bind(window);
    window.fetch = async (...args) => {
        const response = await originalFetch(...args);
        const url = requestUrl(args[0]);
        const path = plannerApiPath(url);
        // The diagnostics panel renders a local error for this endpoint; opening
        // a second recovery dialog would obscure the original failure.
        if (!response.ok && path && path !== '/api/system/recovery') {
            try {
                const payload = await response.clone().json();
                if (payload?.recovery) {
                    window.dispatchEvent(new CustomEvent('planner:failure', {
                        detail: {
                            ...payload,
                            status: response.status,
                            requestConfig: cloneableRequest(args[0], args[1] || {}),
                        },
                    }));
                }
            } catch (_) {
                // Non-JSON API failures remain handled by their local caller.
            }
        }
        return response;
    };
}

export function uninstallFetchRecovery() {
    if (!installed || !originalFetch) return;
    window.fetch = originalFetch;
    originalFetch = null;
    installed = false;
}
