/**
 * AppState — global application state management.
 * Reference: webui_v6.html AppState pattern + opencode EventV2.
 */
const AppState = {
    currentSessionId: null,
    sessions: {},
    messages: [],

    isLoading: false,
    loopStatus: null,       // null | "running" | "completed"
    currentIteration: 0,
    maxIterations: 7,

    settings: {
        serverUrl: 'http://127.0.0.1:8000',
        generationParams: {
            width: 1024, height: 1024,
            numImages: 2, steps: 8, guidance: 3.5, seed: -1,
        },
        maxIterations: 7,
        autoAccept: false,
        showIntermediate: true,
    },

    viewer: {
        isOpen: false,
        currentIndex: 0,
        images: [],
    },

    init() {
        const saved = localStorage.getItem('drawagent_settings');
        if (saved) {
            try {
                const parsed = JSON.parse(saved);
                Object.assign(this.settings, parsed);
            } catch (e) { /* ignore */ }
        }
        this.settings.serverUrl = this.settings.serverUrl.replace(/\/+$/, '');
    },

    saveSettings() {
        localStorage.setItem('drawagent_settings', JSON.stringify(this.settings));
    },
};
