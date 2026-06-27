/**
 * API module — HTTP + WebSocket communication.
 * Reference: webui_v6.html API pattern with DrawAgent event flow.
 */
const API = {
    baseUrl() {
        return AppState.settings.serverUrl;
    },

    async request(method, path, body = null) {
        const opts = {
            method,
            headers: { 'Content-Type': 'application/json' },
        };
        if (body) opts.body = JSON.stringify(body);

        const resp = await fetch(`${this.baseUrl()}${path}`, opts);
        if (!resp.ok) {
            const err = await resp.text();
            throw new Error(`API ${method} ${path}: ${resp.status} — ${err}`);
        }
        return resp.json();
    },

    async createSession(userRequest = '') {
        const data = await this.request('POST', '/api/sessions', {
            user_request: userRequest,
            max_iterations: AppState.settings.maxIterations,
        });
        AppState.currentSessionId = data.session_id;
        AppState.messages = [];
        AppState.currentIteration = 0;
        AppState.loopStatus = null;
        return data;
    },

    async sendMessage(text) {
        const sid = AppState.currentSessionId;
        if (!sid) throw new Error('No active session');
        return this.request('POST', `/api/sessions/${sid}/message`, { text });
    },

    async sendInterrupt(action, data = {}) {
        const sid = AppState.currentSessionId;
        if (!sid) return;
        return this.request('POST', `/api/sessions/${sid}/interrupt`, { action, data });
    },

    async getHistory() {
        const sid = AppState.currentSessionId;
        if (!sid) throw new Error('No active session');
        return this.request('GET', `/api/sessions/${sid}/history`);
    },

    async listSessions() {
        return this.request('GET', '/api/sessions');
    },

    async deleteSession(sid) {
        await this.request('DELETE', `/api/sessions/${sid}`);
        if (AppState.currentSessionId === sid) {
            AppState.currentSessionId = null;
            AppState.messages = [];
        }
    },

    async getStatus() {
        return this.request('GET', '/api/status');
    },

    imageUrl(filename) {
        return `${this.baseUrl()}/api/images/${filename}`;
    },
};

const WSClient = {
    ws: null,
    sessionId: null,

    connect(sessionId) {
        this.sessionId = sessionId;
        const base = AppState.settings.serverUrl.replace(/^http/, 'ws');
        const url = `${base}/ws/sessions/${sessionId}`;
        this.ws = new WebSocket(url);

        this.ws.onmessage = (event) => {
            try {
                const msg = JSON.parse(event.data);
                EventRouter.dispatch(msg);
            } catch (e) {
                console.error('WS parse error:', e);
            }
        };

        this.ws.onopen = () => { console.log('WebSocket connected'); };
        this.ws.onclose = () => { console.log('WebSocket disconnected'); };
        this.ws.onerror = (e) => { console.error('WebSocket error:', e); };
    },

    send(data) {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify(data));
        }
    },

    sendInterrupt(action, data = {}) {
        this.send({ type: 'interrupt', action, data });
    },

    disconnect() {
        if (this.ws) this.ws.close();
        this.ws = null;
    },
};
