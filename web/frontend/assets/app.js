(() => {
    const bootKey = '__plannerSolvingBoot';
    if (window[bootKey]?.started) return;

    const boot = window[bootKey] = {
        started: true,
        mounted: false,
        startedAt: Date.now(),
        error: null,
        optionalFailures: []
    };

    for (const href of [
        '/assets/workspaces.css',
        '/assets/interaction.css',
        '/assets/parser-recovery.css',
        '/assets/platform.css',
        '/assets/platform-overrides.css',
        '/assets/sample-layout.css',
        '/assets/workspace-editor.css',
        '/assets/operator-flow.css',
        '/assets/session-file-actions.css',
        '/assets/session-draft.css',
        '/assets/history-ux.css',
        '/assets/unified-operations.css',
        '/assets/brand-refresh.css',
        '/assets/failure-recovery.css'
    ]) {
        if (document.querySelector(`link[data-planner-style="${href}"]`)) continue;
        const link = document.createElement('link');
        link.rel = 'stylesheet';
        link.href = href;
        link.dataset.plannerStyle = href;
        document.head.appendChild(link);
    }

    function errorText(error) {
        if (!error) return 'Неизвестная ошибка запуска.';
        return String(error.stack || error.message || error);
    }

    function showStartupFailure(error) {
        if (boot.mounted || document.getElementById('planner-startup-error')) return;
        boot.error = errorText(error);
        console.error('[planner] startup failed', error);
        const box = document.createElement('section');
        box.id = 'planner-startup-error';
        box.setAttribute('role', 'alert');
        box.style.cssText = [
            'position:fixed', 'inset:16px', 'z-index:100000', 'overflow:auto',
            'padding:24px', 'background:#fff', 'color:#7a271a',
            'border:2px solid #f04438', 'border-radius:14px',
            'font:14px/1.45 system-ui,sans-serif', 'box-shadow:0 18px 50px rgba(0,0,0,.22)'
        ].join(';');
        const title = document.createElement('h1');
        title.textContent = 'Интерфейс не запустился';
        title.style.margin = '0 0 10px';
        const hint = document.createElement('p');
        hint.textContent = 'Обновите страницу без кэша. Если ошибка повторяется, выполните planner-solving-doctor и приложите его отчёт.';
        const pre = document.createElement('pre');
        pre.textContent = boot.error;
        pre.style.cssText = 'white-space:pre-wrap;background:#fff4ed;padding:12px;border-radius:8px;max-height:45vh;overflow:auto';
        const reload = document.createElement('button');
        reload.type = 'button';
        reload.textContent = 'Перезагрузить страницу';
        reload.style.cssText = 'padding:10px 16px;border:0;border-radius:8px;background:#b42318;color:#fff;cursor:pointer';
        reload.addEventListener('click', () => window.location.reload());
        box.append(title, hint, pre, reload);
        document.body.appendChild(box);
    }

    function optionalModule(result, label) {
        if (result.status === 'fulfilled') return result.value || {};
        boot.optionalFailures.push({ label, error: errorText(result.reason) });
        console.warn(`[planner] ${label} was not loaded`, result.reason);
        return {};
    }

    function runOptional(label, callback) {
        if (typeof callback !== 'function') return undefined;
        try {
            return callback();
        } catch (error) {
            boot.optionalFailures.push({ label, error: errorText(error) });
            console.warn(`[planner] ${label} failed and was disabled`, error);
            return undefined;
        }
    }

    function markMounted() {
        boot.mounted = true;
        boot.mountedAt = Date.now();
        window.clearTimeout(watchdog);
        document.getElementById('planner-startup-error')?.remove();
    }

    window.addEventListener('error', event => {
        if (!boot.mounted) showStartupFailure(event.error || event.message);
    });
    window.addEventListener('unhandledrejection', event => {
        if (!boot.mounted) showStartupFailure(event.reason);
    });

    const watchdog = window.setTimeout(() => {
        if (!boot.mounted) {
            showStartupFailure(new Error('Превышено время запуска интерфейса. Проверьте JavaScript-файлы и кэш браузера.'));
        }
    }, 10000);

    Promise.allSettled([
        import('/assets/brand-refresh.js'),
        import('/assets/operator-flow.js'),
        import('/assets/planner-app.js'),
        import('/assets/session-draft-runtime.js'),
        import('/assets/unified-operations.js'),
        import('/assets/failure-recovery.js'),
        import('/assets/fetch-recovery.js'),
        import('/assets/result-review-flow.js')
    ])
        .then(results => {
            const brand = optionalModule(results[0], 'visual identity');
            const operatorFlow = optionalModule(results[1], 'operator flow enhancements');
            const applicationResult = results[2];
            const draftRuntime = optionalModule(results[3], 'server draft runtime');
            const unifiedOperations = optionalModule(results[4], 'unified operations center');
            const failureRecovery = optionalModule(results[5], 'failure recovery center');
            const fetchRecovery = optionalModule(results[6], 'fetch recovery interceptor');
            const resultReview = optionalModule(results[7], 'result review flow');

            if (applicationResult.status !== 'fulfilled') throw applicationResult.reason;
            const application = applicationResult.value;
            if (typeof application.mount !== 'function') {
                throw new TypeError('Модуль planner-app.js не экспортирует функцию mount().');
            }

            // Эти расширения меняют только статическую разметку и перехватчики.
            // Их отказ не должен блокировать основное Vue-приложение.
            runOptional('brand metadata', () => brand.installBrandMetadata?.());
            runOptional('brand markup', () => brand.installBrandMarkup?.());
            runOptional('operator flow markup', () => operatorFlow.installOperatorFlowMarkup?.());
            runOptional('result review markup', () => resultReview.installResultReviewMarkup?.());
            runOptional('failure recovery', () => failureRecovery.installFailureRecovery?.());
            runOptional('fetch recovery', () => fetchRecovery.installFetchRecovery?.());

            // Единственный критический этап клиентского запуска — монтирование
            // основного приложения. Сразу после него страница считается рабочей.
            application.mount();
            markMounted();

            // Все последующие модули являются улучшениями. Ошибка в одном из них,
            // включая unified-operations.js, записывается в диагностику, но не
            // скрывает уже смонтированное рабочее место оператора.
            runOptional('operator flow runtime', () => operatorFlow.installOperatorFlowRuntime?.());
            runOptional('result review runtime', () => resultReview.installResultReviewRuntime?.());
            runOptional('server draft runtime', () => draftRuntime.installSessionDraftRuntime?.());
            runOptional('unified operations runtime', () => unifiedOperations.installUnifiedOperationsRuntime?.());

            import('/assets/ui-runtime-fixes.js')
                .then(runtime => runOptional(
                    'password input policy',
                    () => runtime.installPasswordInputPolicy?.()
                ))
                .catch(error => {
                    boot.optionalFailures.push({
                        label: 'password input policy',
                        error: errorText(error)
                    });
                    console.warn('[planner] password policy was not loaded', error);
                });
        })
        .catch(showStartupFailure);
})();
