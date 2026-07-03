/**
 * AppState — global application state management.
 * Reference: webui_v6.html AppState pattern + opencode EventV2.
 */
const AppState = {
    currentSessionId: null,
    sessions: {},
    messages: [],
    _phase: null,

    isLoading: false,
    loopStatus: null,
    currentIteration: 0,
    maxIterations: 7,
    _lastUserPrompt: '',

    settings: {
        serverUrl: '',  // auto-detected from window.location.origin on init
        lang: 'zh-CN',
        generationParams: {
            width: 960, height: 1280,
            numImages: 2, steps: 30, guidance: 7.0, seed: -1, cfgTruncation: 0.6,
        },
        maxIterations: 7,
        autoAccept: false,
        showIntermediate: true,
        systemConfig: {
            agentA: {
                provider: 'openai', model: 'gpt-4o',
                apiBase: 'https://api.openai.com/v1',
                apiKey: '', temperature: 0.7,
            },
            agentB: {
                type: 'http', model: 'z-image',
                apiBase: 'http://localhost:8000',
                endpoint: '/api/generate', mcpCommand: '',
                mcpToolName: 'generate_image', mcpUrl: '',
                mcpKeepAlive: true, modelHints: '',
            },
            agentC: {
                provider: 'openai', model: 'gpt-4o',
                apiBase: 'https://api.openai.com/v1',
                apiKey: '', temperature: 0.3,
            },
        },
    },

    favorites: new Set(),

    viewer: {
        isOpen: false,
        currentIndex: 0,
        images: [],
        metadata: [],
    },

    init() {
        // Load persistent settings (without API keys) from localStorage
        const saved = localStorage.getItem('drawagent_settings');
        if (saved) {
            try {
                const parsed = JSON.parse(saved);
                this.settings.generationParams = { ...this.settings.generationParams, ...(parsed.generationParams || {}) };
                if (parsed.maxIterations) this.settings.maxIterations = parsed.maxIterations;
                if (parsed.autoAccept !== undefined) this.settings.autoAccept = parsed.autoAccept;
                if (parsed.showIntermediate !== undefined) this.settings.showIntermediate = parsed.showIntermediate;
                if (parsed.systemConfig) {
                    this.settings.systemConfig.agentA = { ...this.settings.systemConfig.agentA, ...(parsed.systemConfig.agentA || {}) };
                    this.settings.systemConfig.agentB = { ...this.settings.systemConfig.agentB, ...(parsed.systemConfig.agentB || {}) };
                    this.settings.systemConfig.agentC = { ...this.settings.systemConfig.agentC, ...(parsed.systemConfig.agentC || {}) };
                    // Don't load API keys from localStorage
                    delete this.settings.systemConfig.agentA.apiKey;
                }
            } catch (e) { /* ignore */ }
        }
        // Load API keys from sessionStorage (cleared when browser closes)
        const apiKeyA = sessionStorage.getItem('drawagent_apikey_a');
        const apiKeyC = sessionStorage.getItem('drawagent_apikey_c');
        if (apiKeyA) this.settings.systemConfig.agentA.apiKey = apiKeyA;
        if (apiKeyC) this.settings.systemConfig.agentC.apiKey = apiKeyC;

        this.settings.serverUrl = window.location.origin;

        // Restore favorites
        const fav = sessionStorage.getItem('drawagent_favorites');
        if (fav) {
            try { this.favorites = new Set(JSON.parse(fav)); } catch (e) {}
        }
    },

    saveSettings() {
        // Save everything except API keys to localStorage
        const toSave = JSON.parse(JSON.stringify(this.settings));
        if (toSave.systemConfig) {
            if (toSave.systemConfig.agentA) delete toSave.systemConfig.agentA.apiKey;
            if (toSave.systemConfig.agentC) delete toSave.systemConfig.agentC.apiKey;
        }
        localStorage.setItem('drawagent_settings', JSON.stringify(toSave));
        // Store API keys in sessionStorage only
        if (this.settings.systemConfig.agentA.apiKey) {
            sessionStorage.setItem('drawagent_apikey_a', this.settings.systemConfig.agentA.apiKey);
        }
        if (this.settings.systemConfig.agentC.apiKey) {
            sessionStorage.setItem('drawagent_apikey_c', this.settings.systemConfig.agentC.apiKey);
        }
    },

    saveFavorites() {
        sessionStorage.setItem('drawagent_favorites', JSON.stringify([...this.favorites]));
    },

    toggleFavorite(path) {
        if (this.favorites.has(path)) {
            this.favorites.delete(path);
        } else {
            this.favorites.add(path);
        }
        this.saveFavorites();
    },
};

/** shorthand for I18n.t */
const _t = (key, params) => I18n.t(key, params);
