let installed = false;
let originalFetch = null;

function requestUrl(input) {
    if (typeof input === 'string') return input;
    if (input instanceof URL) return input.toString();
    return String(input?.url || '');
}

function isPlannerApi(url) {
    try {
        const parsed = new URL(url, window.location.href);
        return parsed.origin === window.location.origin && parsed.pathname.startsWith('/api/');
    } catch (_) {
        return false;
    }
}

export function installFetchRecovery() {
    if (installed || typeof window.fetch !== 'function') return;
    installed = true;
    originalFetch = window.fetch.bind(window);
    window.fetch = async (...args) => {
        const response = await originalFetch(...args);
        const url = requestUrl(args[0]);
        if (!response.ok && isPlannerApi(url)) {
            try {
                const payload = await response.clone().json();
                if (payload?.recovery) {
                    window.dispatchEvent(new CustomEvent('planner:failure', {
                        detail: {
                            ...payload,
                            status: response.status,
                            requestConfig: null,
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
