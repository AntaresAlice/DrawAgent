/**
 * ActivityStream — agentic mode live activity log.
 *
 * Renders LLM text, tool calls, and image results as a streaming activity
 * log with collapsible detail sections. OpenCode-style: compact summary +
 * chevron-rotating expandable details.
 */
const ActivityStream = {
    _container: null,
    _currentTurn: null,
    _currentText: '',
    _toolCallEls: {},

    init() {
        this._container = document.getElementById('messagesContainer');
        if (!this._container) {
            this._container = document.createElement('div');
            this._container.id = 'messagesContainer';
            this._container.className = 'messages-container';
            const main = document.querySelector('.chat-main');
            if (main) main.appendChild(this._container);
        }
    },

    /** Start a new LLM turn */
    onTurnStarted(data) {
        const el = document.createElement('div');
        el.className = 'agentic-turn';
        el.id = 'agentic-turn-' + Date.now();
        el.innerHTML = `
            <div class="agentic-turn-header">
                <span class="agentic-turn-icon"><i class="fa-solid fa-brain"></i></span>
                <span class="agentic-turn-label">Agent is thinking...</span>
            </div>
            <div class="agentic-turn-body" style="display:none;">
                <div class="agentic-text"></div>
                <div class="agentic-tools"></div>
            </div>
        `;
        this._container.appendChild(el);
        this._scroll();
        this._currentTurn = el;
        this._currentText = '';
    },

    /** Append streaming text chunk */
    onTextDelta(data) {
        if (!this._currentTurn) return;
        const header = this._currentTurn.querySelector('.agentic-turn-label');
        const body = this._currentTurn.querySelector('.agentic-turn-body');
        const textEl = this._currentTurn.querySelector('.agentic-text');
        if (body) body.style.display = 'block';
        this._currentText += data.content || '';
        if (header) {
            const preview = this._currentText.slice(0, 80).replace(/\n/g, ' ');
            header.textContent = preview || 'Agent is thinking...';
        }
        if (textEl) {
            textEl.textContent = this._currentText;
        }
        this._scroll();
    },

    /** A tool was called */
    onToolCompleted(data) {
        if (!this._currentTurn) return;
        const header = this._currentTurn.querySelector('.agentic-turn-label');
        const body = this._currentTurn.querySelector('.agentic-turn-body');
        const toolsEl = this._currentTurn.querySelector('.agentic-tools');
        if (body) body.style.display = 'block';

        const toolEl = document.createElement('div');
        toolEl.className = 'agentic-tool-item collapsible';
        const toolName = data.tool_name || 'unknown';
        const isError = data.status === 'error';
        const icon = isError ? '⚠' : (toolName === 'generate_image' ? '🎨' : (toolName === 'inspect_image' ? '🔍' : (toolName === 'finalize' ? '✅' : '🔧')));
        const shortResult = this._formatToolResult(toolName, data);

        toolEl.innerHTML = `
            <div class="agentic-tool-trigger" onclick="ActivityStream._toggleTool(this)">
                <span class="agentic-tool-chevron">▶</span>
                <span class="agentic-tool-icon">${icon}</span>
                <span class="agentic-tool-name">${this._escHtml(toolName)}</span>
                <span class="agentic-tool-summary">${this._escHtml(shortResult)}</span>
            </div>
            <div class="agentic-tool-detail" style="display:none;">
                <pre>${this._escHtml(JSON.stringify(data, null, 2))}</pre>
            </div>
        `;
        toolsEl.appendChild(toolEl);

        if (toolName === 'generate_image' && !isError) {
            if (header) header.textContent = 'Generated image ✓';
            if (data.result && data.result.output) {
                const match = data.result.output.match(/((?:\/|[A-Z]:)[^\s,;]+\.png)/i);
                if (match) {
                    const imgPath = match[1];
                    const filename = imgPath.replace(/\\/g, '/').split('/').pop();
                    const imgEl = document.createElement('div');
                    imgEl.className = 'agentic-image-preview';
                    const allImages = [API.imageUrl(filename)];
                    imgEl.innerHTML = '<img src="' + API.imageUrl(filename) + '" alt="' + this._escHtmlAttr(filename) + '" style="max-width:180px;max-height:240px;border-radius:8px;margin:8px 0;cursor:pointer;" onclick="Viewer.open(' + JSON.stringify(allImages) + ', 0)">';
                    toolsEl.appendChild(imgEl);
                }
            }
        } else if (toolName === 'inspect_image' && !isError) {
            if (header) header.textContent = 'Inspected image ✓';
        } else if (toolName === 'finalize' && !isError) {
            if (header) header.textContent = 'Task finalized';
        }

        this._scroll();
    },

    /** Session finalized */
    onFinalized(data) {
        const el = document.createElement('div');
        el.className = 'agentic-turn finalized';
        el.innerHTML = `
            <div class="agentic-turn-header finalized-header">
                <span class="agentic-turn-icon">✅</span>
                <span class="agentic-turn-label">Task completed</span>
            </div>
            <div class="agentic-turn-body" style="display:block;">
                <div class="agentic-finalize-reason">${this._escHtml(data.reason || '')}</div>
            </div>
        `;
        this._container.appendChild(el);
        this._scroll();
    },

    /** User steer/interrupt accepted */
    onInterruptAccepted(data) {
        const el = document.createElement('div');
        el.className = 'agentic-turn steer';
        el.innerHTML = `
            <div class="agentic-turn-header">
                <span class="agentic-turn-icon">💬</span>
                <span class="agentic-turn-label">User feedback: ${this._escHtml((data.message || '').slice(0, 60))}</span>
            </div>
        `;
        this._container.appendChild(el);
        this._scroll();
    },

    /** Compaction event */
    onCompacted(data) {
        const el = document.createElement('div');
        el.className = 'agentic-turn info';
        el.innerHTML = `
            <div class="agentic-turn-header" style="font-size:12px;color:var(--text-secondary);">
                <span class="agentic-turn-icon">📦</span>
                <span>Context compacted (old turns summarized)</span>
            </div>
        `;
        this._container.appendChild(el);
        this._scroll();
    },

    // --- helpers ---

    _formatToolResult(name, data) {
        if (data.status === 'error') return `Error: ${(data.error || '').slice(0, 60)}`;
        if (name === 'generate_image') {
            const output = data.result?.output || '';
            const match = output.match(/(\d+)\/\d+/);
            if (match) return `${match[1]} image(s) generated`;
            return 'Image generated';
        }
        if (name === 'inspect_image') return 'Inspection complete';
        if (name === 'finalize') return 'Finalized';
        if (name === 'compare_images') return 'Compared';
        return 'Done';
    },

    _toggleTool(trigger) {
        const detail = trigger.nextElementSibling;
        const chevron = trigger.querySelector('.agentic-tool-chevron');
        if (detail.style.display === 'none') {
            detail.style.display = 'block';
            if (chevron) chevron.textContent = '▼';
        } else {
            detail.style.display = 'none';
            if (chevron) chevron.textContent = '▶';
        }
    },

    _escHtml(s) {
        const d = document.createElement('div');
        d.textContent = s;
        return d.innerHTML;
    },

    _escHtmlAttr(s) {
        return (s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    },

    _scroll() {
        if (this._container) {
            this._container.scrollTop = this._container.scrollHeight;
        }
    },

    /** Reset state between sessions */
    reset() {
        this._currentTurn = null;
        this._currentText = '';
        this._toolCallEls = {};
    },
};
