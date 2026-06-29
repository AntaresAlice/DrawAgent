/**
 * Viewer — fullscreen image viewer with keyboard navigation, download, copy, favorites.
 */
const Viewer = {
    isOpen: false,
    currentIndex: 0,
    images: [],

    open(images, startIndex = 0) {
        this.images = images.filter(Boolean);
        if (!this.images.length) return;
        this.currentIndex = Math.max(0, Math.min(startIndex, this.images.length - 1));
        this.isOpen = true;
        this._render();
        document.getElementById('viewerOverlay').classList.add('active');
        document.body.style.overflow = 'hidden';
    },

    close() {
        this.isOpen = false;
        document.getElementById('viewerOverlay').classList.remove('active');
        document.body.style.overflow = '';
    },

    next() {
        if (!this.images.length) return;
        this.currentIndex = (this.currentIndex + 1) % this.images.length;
        this._render();
    },

    prev() {
        if (!this.images.length) return;
        this.currentIndex = (this.currentIndex - 1 + this.images.length) % this.images.length;
        this._render();
    },

    download() {
        if (!this.images.length) return;
        const url = this.images[this.currentIndex];
        const a = document.createElement('a');
        a.href = url;
        a.download = url.split('/').pop() || 'image.png';
        a.click();
    },

    async copy() {
        if (!this.images.length) return;
        try {
            const img = await fetch(this.images[this.currentIndex]);
            const blob = await img.blob();
            await navigator.clipboard.write([
                new ClipboardItem({ [blob.type]: blob })
            ]);
            Renderer.showToast('已复制到剪贴板', 'success');
        } catch (e) {
            try {
                // Fallback for browsers without ClipboardItem
                const imgEl = document.getElementById('viewerImage');
                const canvas = document.createElement('canvas');
                canvas.width = imgEl.naturalWidth;
                canvas.height = imgEl.naturalHeight;
                const ctx = canvas.getContext('2d');
                ctx.drawImage(imgEl, 0, 0);
                const blob = await new Promise(r => canvas.toBlob(r));
                await navigator.clipboard.write([
                    new ClipboardItem({ [blob.type]: blob })
                ]);
                Renderer.showToast('已复制到剪贴板', 'success');
            } catch (e2) {
                Renderer.showToast('复制失败', 'error');
            }
        }
    },

    _render() {
        const img = document.getElementById('viewerImage');
        const index = document.getElementById('viewerIndex');
        const seed = document.getElementById('viewerSeed');

        if (img) img.src = this.images[this.currentIndex];
        if (index) index.textContent = `${this.currentIndex + 1}/${this.images.length}`;

        const meta = AppState.viewer.metadata[this.currentIndex];
        if (seed && meta) {
            seed.textContent = `${_t('seedLabel')}: ${meta.seed || '-'} | ${meta.width || ''}x${meta.height || ''}`;
        } else if (seed) {
            seed.textContent = `${_t('seedLabel')}: -`;
        }
    },
};

document.addEventListener('keydown', (e) => {
    if (!Viewer.isOpen) return;
    switch (e.key) {
        case 'Escape': Viewer.close(); break;
        case 'ArrowLeft': Viewer.prev(); break;
        case 'ArrowRight': Viewer.next(); break;
        case 's': if (e.ctrlKey || e.metaKey) { e.preventDefault(); Viewer.download(); } break;
        case 'c': if (e.ctrlKey || e.metaKey) { e.preventDefault(); Viewer.copy(); } break;
    }
});
