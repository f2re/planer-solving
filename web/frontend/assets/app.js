for (const href of ['assets/workspaces.css', 'assets/interaction.css', 'assets/platform.css']) {
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = href;
    document.head.appendChild(link);
}

import('/assets/planner-app.js')
    .then(module => module.mount())
    .catch(error => {
        console.error(error);
        document.body.insertAdjacentHTML(
            'beforeend',
            '<div style="padding:20px;color:#b42318">Не удалось запустить интерфейс. Откройте консоль браузера.</div>'
        );
    });
