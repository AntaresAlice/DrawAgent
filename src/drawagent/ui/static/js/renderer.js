/**
 * Renderer — UI rendering: messages, images, iteration cards, inspection panels.
 */
const Renderer = {
    /** Add a message bubble */
    addMessage(role, content) {
        const container = document.getElementById('messagesContainer');
        const welcome = document.getElementById('welcomeScreen');
        if (welcome) welcome.style.display = 'none';

        const div = document.createElement('div');
        div.className = `message ${role}`;

        const avatarIcon = role === 'user' ? 'fa-user' : 'fa-robot';
        div.innerHTML = `
            <div class="message-avatar"><i class="fa-solid ${avatarIcon}"></i></div>
            <div class="message-content">${this._formatContent(content)}</div>
        `;

        container.appendChild(div);
        this._scrollToBottom();
        return div;
    },

    /** Add a system message (info, status) */
    addSystemMessage(text) {
        const container = document.getElementById('messagesContainer');
        const welcome = document.getElementById('welcomeScreen');
        if (welcome) welcome.style.display = 'none';

        const div = document.createElement('div');
        div.className = 'message agent';
        div.innerHTML = `
            <div class="message-avatar"><i class="fa-solid fa-circle-info"></i></div>
            <div class="message-content" style="font-size:13px;color:var(--text-secondary);">${text}</div>
        `;
        container.appendChild(div);
        this._scrollToBottom();
    },

    /** Add an iteration card */
    addIterationCard(number, images, inspections, decision) {
        const container = document.getElementById('messagesContainer');
        const welcome = document.getElementById('welcomeScreen');
        if (welcome) welcome.style.display = 'none';

        const card = document.createElement('div');
        card.className = 'iteration-card';

        const passed = decision && decision.passed;
        const statusClass = passed ? 'pass' : 'fail';
        const statusIcon = passed ? 'fa-circle-check' : 'fa-circle-exclamation';
        const statusText = passed ? 'Quality passed' : 'Issues found';

        card.innerHTML = `
            <div class="iteration-header" onclick="this.parentElement.querySelector('.iteration-body').classList.toggle('collapsed')">
                <span class="iteration-badge">Iteration ${number}</span>
                <span class="iteration-status ${statusClass}">
                    <i class="fa-solid ${statusIcon}"></i> ${statusText}
                </span>
                <span style="flex:1;"></span>
                <i class="fa-solid fa-chevron-down" style="color:var(--text-secondary);font-size:12px;"></i>
            </div>
            <div class="iteration-body">
                ${images && images.length ? `
                <div class="iteration-images">
                    ${images.map((img, i) => `
                        <img class="iteration-image" src="${API.imageUrl(img.filename || img.path.split('/').pop())}"
                             alt="Generated image ${i+1}" title="Seed: ${img.seed}"
                             onclick="Viewer.open(${JSON.stringify(images.map(im => API.imageUrl(im.filename || im.path.split('/').pop())).filter(Boolean))}, ${i})">
                    `).join('')}
                </div>` : ''}
                ${inspections && inspections.length ? inspections.map(i => `
                    <div class="inspection-item ${i.passed ? 'pass' : 'fail'}">
                        <span class="status-icon"><i class="fa-solid ${i.passed ? 'fa-circle-check' : 'fa-circle-xmark'}"></i></span>
                        <div>
                            <strong>${i.task_name || 'Inspection'}</strong>
                            <div style="color:var(--text-secondary);margin-top:2px;">${(i.observation || '').slice(0, 200)}</div>
                        </div>
                    </div>
                `).join('') : ''}
                ${decision ? `
                <div class="decision-banner ${decision.passed ? 'pass' : 'fail'}">
                    <i class="fa-solid ${decision.passed ? 'fa-circle-check' : 'fa-circle-exclamation'}"></i>
                    <span>${decision.reasoning || (decision.passed ? 'Passed' : 'Needs improvement')}</span>
                </div>` : ''}
            </div>
        `;

        container.appendChild(card);
        this._scrollToBottom();
        return card;
    },

    /** Show loading indicator */
    showLoading(text = 'Generating...') {
        const container = document.getElementById('messagesContainer');
        const welcome = document.getElementById('welcomeScreen');
        if (welcome) welcome.style.display = 'none';

        const div = document.createElement('div');
        div.className = 'message agent';
        div.id = 'loadingIndicator';
        div.innerHTML = `
            <div class="message-avatar"><i class="fa-solid fa-robot"></i></div>
            <div class="message-content">
                <div class="loading-spinner">
                    <span style="margin-right:8px;">${text}</span>
                    <span class="dot"></span><span class="dot"></span><span class="dot"></span>
                </div>
            </div>
        `;
        container.appendChild(div);
        this._scrollToBottom();
        return div;
    },

    removeLoading() {
        const el = document.getElementById('loadingIndicator');
        if (el) el.remove();
    },

    /** Show a toast notification */
    showToast(text, type = 'info') {
        const toast = document.createElement('div');
        toast.className = `toast ${type}`;
        toast.textContent = text;
        document.body.appendChild(toast);
        setTimeout(() => toast.remove(), 3000);
    },

    /** Set loading state */
    setLoading(loading) {
        AppState.isLoading = loading;
        const btn = document.getElementById('sendButton');
        const bar = document.getElementById('interruptBar');
        const status = document.getElementById('chatStatus');

        if (btn) btn.disabled = loading;
        if (bar) bar.style.display = loading ? 'flex' : 'none';
        if (status) {
            status.textContent = loading ? 'Generating...' : 'Ready';
            status.classList.toggle('loading', loading);
        }
    },

    /** Set iteration progress */
    setProgress(current, max) {
        AppState.currentIteration = current;
        AppState.maxIterations = max;
        const status = document.getElementById('chatStatus');
        if (status) status.textContent = `Iteration ${current}/${max}`;
    },

    /** Render session list in sidebar */
    renderSessions(sessions) {
        const list = document.getElementById('conversationsList');
        if (!list) return;
        list.innerHTML = sessions.map(s => `
            <div class="session-item ${s.id === AppState.currentSessionId ? 'active' : ''}"
                 onclick="AppActions.selectSession('${s.id}')">
                <span class="session-icon"><i class="fa-solid fa-message"></i></span>
                <div class="session-info">
                    <div class="session-title">${s.user_request || 'New Session'}</div>
                    <div class="session-date">${s.created_at ? new Date(s.created_at).toLocaleDateString() : ''}</div>
                </div>
                <button class="session-delete" onclick="event.stopPropagation(); AppActions.deleteSession('${s.id}')">
                    <i class="fa-solid fa-trash"></i>
                </button>
            </div>
        `).join('');
    },

    clearMessages() {
        const container = document.getElementById('messagesContainer');
        container.innerHTML = '';
        const welcome = document.createElement('div');
        welcome.className = 'welcome-screen';
        welcome.id = 'welcomeScreen';
        welcome.innerHTML = document.querySelector('.welcome-screen')?.innerHTML || '<h1>DrawAgent</h1>';
        container.appendChild(welcome);
    },

    _formatContent(content) {
        if (typeof content !== 'string') return String(content);
        // Escape HTML, then handle basic markdown
        return content
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/`([^`]+)`/g, '<code style="background:var(--bg);padding:2px 6px;border-radius:4px;font-size:13px;">$1</code>')
            .replace(/\n/g, '<br>');
    },

    _scrollToBottom() {
        const container = document.getElementById('messagesContainer');
        if (container) {
            setTimeout(() => { container.scrollTop = container.scrollHeight; }, 50);
        }
    }
};
