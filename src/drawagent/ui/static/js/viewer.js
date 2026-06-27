/**
 * Viewer — fullscreen image viewer with keyboard navigation.
 * Reference: webui_v6.html viewer pattern.
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

    _render() {
        const img = document.getElementById('viewerImage');
        const index = document.getElementById('viewerIndex');
        const seed = document.getElementById('viewerSeed');

        if (img) img.src = this.images[this.currentIndex];
        if (index) index.textContent = `${this.currentIndex + 1}/${this.images.length}`;
        if (seed) seed.textContent = '';
    },
};

// Keyboard controls
document.addEventListener('keydown', (e) => {
    if (!Viewer.isOpen) return;
    switch (e.key) {
        case 'Escape': Viewer.close(); break;
        case 'ArrowLeft': Viewer.prev(); break;
        case 'ArrowRight': Viewer.next(); break;
    }
});
