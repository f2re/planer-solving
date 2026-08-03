export function installPlatformEnhancements() {
    const runHero = document.querySelector('.run-hero');
    if (runHero && !runHero.querySelector('.repeat-run-button')) {
        runHero.insertAdjacentHTML(
            'beforeend',
            '<button v-if="canOperate" type="button" class="btn btn-primary btn-small repeat-run-button" @click="repeatRun(selectedRun)">Повторить с прежними настройками</button>'
        );
    }

    const dropzone = document.querySelector('.import-dropzone');
    const input = dropzone?.querySelector('input[type=file]');
    if (dropzone && input) {
        dropzone.addEventListener('dragover', event => {
            event.preventDefault();
            dropzone.classList.add('dragging');
        });
        dropzone.addEventListener('dragleave', () => {
            dropzone.classList.remove('dragging');
        });
        dropzone.addEventListener('drop', event => {
            event.preventDefault();
            dropzone.classList.remove('dragging');
            const files = event.dataTransfer?.files;
            if (!files?.length) return;
            try {
                input.files = files;
            } catch (_) {
                return;
            }
            input.dispatchEvent(new Event('change', { bubbles: true }));
        });
    }
}
