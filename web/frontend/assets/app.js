for (const href of [
    'assets/workspaces.css',
    'assets/interaction.css',
    'assets/platform.css',
    'assets/platform-overrides.css',
    'assets/sample-layout.css',
    'assets/workspace-editor.css'
]) {
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = href;
    document.head.appendChild(link);
}

Promise.all([
    import('/assets/ui-runtime-fixes.js'),
    import('/assets/planner-app.js')
])
    .then(([runtime, application]) => {
        runtime.installPasswordInputPolicy();
        application.mount();
        runtime.installPasswordInputPolicy();
    })
    .catch(error => {
        console.error(error);
        document.body.insertAdjacentHTML(
            'beforeend',
            '<div style="padding:20px;color:#b42318">Не удалось запустить интерфейс. Откройте консоль браузера.</div>'
        );
    });
