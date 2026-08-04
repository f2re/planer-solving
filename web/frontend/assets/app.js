(() => {
    const bootKey = '__plannerSolvingBoot';
    if (window[bootKey]?.started) return;

    const boot = window[bootKey] = {
        started: true,
        mounted: false,
        startedAt: Date.now(),
        error: null
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
        import('/assets/fetch-recovery.js')
    ])
        .then(results => {
            const brandResult = results[0];
            const operatorFlowResult = results[1];
            const applicationResult = results[2];
            const draftRuntimeResult = results[3];
            const unifiedOperationsResult = results[4];
            const failureRecoveryResult = results[5];
            const fetchRecoveryResult = results[6];
            if (applicationResult.status !== 'fulfilled') throw applicationResult.reason;

            const brand = brandResult.status === 'fulfilled' ? brandResult.value : {};
            if (brandResult.status !== 'fulfilled') {
                console.warn('[planner] visual identity was not loaded', brandResult.reason);
            }

            const operatorFlow = operatorFlowResult.status === 'fulfilled'
                ? operatorFlowResult.value
                : {};
            if (operatorFlowResult.status !== 'fulfilled') {
                console.warn('[planner] operator flow enhancements were not loaded', operatorFlowResult.reason);
            }

            const draftRuntime = draftRuntimeResult.status === 'fulfilled'
                ? draftRuntimeResult.value
                : {};
            if (draftRuntimeResult.status !== 'fulfilled') {
                console.warn('[planner] server draft runtime was not loaded', draftRuntimeResult.reason);
            }

            const unifiedOperations = unifiedOperationsResult.status === 'fulfilled'
                ? unifiedOperationsResult.value
                : {};
            if (unifiedOperationsResult.status !== 'fulfilled') {
                console.warn('[planner] unified operations center was not loaded', unifiedOperationsResult.reason);
            }

            const failureRecovery = failureRecoveryResult.status === 'fulfilled'
                ? failureRecoveryResult.value
                : {};
            if (failureRecoveryResult.status !== 'fulfilled') {
                console.warn('[planner] failure recovery center was not loaded', failureRecoveryResult.reason);
            }

            const fetchRecovery = fetchRecoveryResult.status === 'fulfilled'
                ? fetchRecoveryResult.value
                : {};
            if (fetchRecoveryResult.status !== 'fulfilled') {
                console.warn('[planner] fetch recovery interceptor was not loaded', fetchRecoveryResult.reason);
            }

            // Static brand markup is installed before Vue takes ownership of
            // the document. This avoids post-mount DOM churn and keeps startup
            // deterministic even when optional visual assets are unavailable.
            brand.installBrandMetadata?.();
            brand.installBrandMarkup?.();
            operatorFlow.installOperatorFlowMarkup?.();

            const application = applicationResult.value;
            if (typeof application.mount !== 'function') {
                throw new TypeError('Модуль planner-app.js не экспортирует функцию mount().');
            }
            application.mount();
            failureRecovery.installFailureRecovery?.();
            fetchRecovery.installFetchRecovery?.();
            operatorFlow.installOperatorFlowRuntime?.();
            draftRuntime.installSessionDraftRuntime?.();
            unifiedOperations.installUnifiedOperationsRuntime?.();

            boot.mounted = true;
            boot.mountedAt = Date.now();
            window.clearTimeout(watchdog);
            document.getElementById('planner-startup-error')?.remove();

            // Политика пустых паролей не должна задерживать основной интерфейс.
            // Даже если вспомогательный модуль повреждён, Vue уже смонтирован.
            import('/assets/ui-runtime-fixes.js')
                .then(runtime => runtime.installPasswordInputPolicy?.())
                .catch(error => console.warn('[planner] password policy was not installed', error));
        })
        .catch(showStartupFailure);
})();
