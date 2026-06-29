/**
 * API module — HTTP + WebSocket communication.
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

        const url = `${this.baseUrl()}${path}`;
        const logBody = body ? JSON.parse(JSON.stringify(body)) : null;
        if (logBody && logBody.data && logBody.data.apiKey) logBody.data = { ...logBody.data, apiKey: '***' };
        console.debug('[API]', method, path, logBody ? JSON.stringify(logBody).slice(0, 200) : '');
        const resp = await fetch(url, opts);
        console.debug('[API]', resp.status, method, path);
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

    async updateConfig(config) {
        return this.request('PUT', '/api/config', config);
    },

    imageUrl(filename) {
        return `${this.baseUrl()}/api/images/${filename}`;
    },
};

const WSClient = {
    ws: null,
    sessionId: null,
    reconnectAttempts: 0,
    maxReconnectAttempts: 5,
    reconnectDelay: 1000,

    connect(sessionId) {
        this.sessionId = sessionId;
        const base = AppState.settings.serverUrl.replace(/^http/, 'ws');
        const url = `${base}/ws/sessions/${sessionId}`;
        this.ws = new WebSocket(url);

        this.ws.onmessage = (event) => {
            try {
                const msg = JSON.parse(event.data);
                console.debug('[WS]', msg.type, msg);
                EventRouter.dispatch(msg);
            } catch (e) {
                console.error('WS parse error:', e);
            }
        };

        this.ws.onopen = () => {
            console.debug('[WS] connected, session:', sessionId);
            this.reconnectAttempts = 0;
            this.reconnectDelay = 1000;
        };

        this.ws.onclose = () => {
            console.debug('[WS] disconnected, session:', this.sessionId);
            this._tryReconnect();
        };

        this.ws.onerror = (e) => {
            console.error('WebSocket error:', e);
        };
    },

    _tryReconnect() {
        if (!this.sessionId) return;
        if (this.reconnectAttempts >= this.maxReconnectAttempts) {
            console.debug('[WS] max reconnect attempts reached');
            return;
        }
        this.reconnectAttempts++;
        const delay = this.reconnectDelay * Math.pow(2, this.reconnectAttempts - 1);
        console.debug('[WS] reconnecting in', delay, 'ms (attempt', this.reconnectAttempts, ')');
        setTimeout(() => {
            if (this.sessionId) this.connect(this.sessionId);
        }, delay);
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
        this.reconnectAttempts = this.maxReconnectAttempts;
        if (this.ws) this.ws.close();
        this.ws = null;
    },
};
