/**
 * Renderer — UI rendering: messages, images, iteration cards, inspection panels.
 */
const Renderer = {
    addMessage(role, content) {
        const container = document.getElementById('messagesContainer');
        const welcome = document.getElementById('welcomeScreen');
        if (welcome) welcome.style.display = 'none';

        const div = document.createElement('div');
        div.className = `message ${role}`;

        const avatarIcon = role === 'user' ? 'fa-user' : 'fa-robot';
        div.innerHTML = `<div class="message-avatar"><i class="fa-solid ${avatarIcon}"></i></div><div class="message-content">${this._formatContent(content)}</div>`;

        container.appendChild(div);
        this._scrollToBottom();
        return div;
    },

    addSystemMessage(text) {
        const container = document.getElementById('messagesContainer');
        const welcome = document.getElementById('welcomeScreen');
        if (welcome) welcome.style.display = 'none';

        const div = document.createElement('div');
        div.className = 'message agent';
        div.innerHTML = `<div class="message-avatar"><i class="fa-solid fa-circle-info"></i></div><div class="message-content" style="font-size:13px;color:var(--text-secondary);">${text}</div>`;
        container.appendChild(div);
        this._scrollToBottom();
    },

    addIterationCard(number, images, inspections, decision) {
        const container = document.getElementById('messagesContainer');
        const welcome = document.getElementById('welcomeScreen');
        if (welcome) welcome.style.display = 'none';

        const card = document.createElement('div');
        card.className = 'iteration-card';

        const passed = decision && decision.passed;
        const statusClass = passed ? 'pass' : 'fail';
        const statusIcon = passed ? 'fa-circle-check' : 'fa-circle-exclamation';
        const statusText = _t(passed ? 'qualityPassed' : 'issuesFound');

        card.innerHTML = `<div class="iteration-header" onclick="this.parentElement.querySelector('.iteration-body').classList.toggle('collapsed')">
                <span class="iteration-badge">${_t('iterationBadge', { number })}</span>
                <span class="iteration-status ${statusClass}"><i class="fa-solid ${statusIcon}"></i> ${statusText}</span>
                <span style="flex:1;"></span>
                <i class="fa-solid fa-chevron-down" style="color:var(--text-secondary);font-size:12px;"></i>
            </div>
            <div class="iteration-body">
                ${images && images.length ? `<div class="iteration-images">${images.map((img, i) => `<img class="iteration-image" src="${API.imageUrl(img.filename || img.path.split('/').pop())}" alt="${img.filename || 'image'}" title="${_t('seedLabel')}: ${img.seed}" onclick="Viewer.open(${JSON.stringify(images.map(im => API.imageUrl(im.filename || im.path.split('/').pop())).filter(Boolean))}, ${i})">`).join('')}</div>` : ''}
                ${inspections && inspections.length ? inspections.map(i => `<div class="inspection-item ${i.passed ? 'pass' : 'fail'}"><span class="status-icon"><i class="fa-solid ${i.passed ? 'fa-circle-check' : 'fa-circle-xmark'}"></i></span><div><strong>${i.task_name || 'Inspection'}</strong><div style="color:var(--text-secondary);margin-top:2px;">${(i.observation || '').slice(0, 200)}</div></div></div>`).join('') : ''}
                ${decision ? `<div class="decision-banner ${decision.passed ? 'pass' : 'fail'}"><i class="fa-solid ${decision.passed ? 'fa-circle-check' : 'fa-circle-exclamation'}"></i><span>${decision.reasoning || _t(decision.passed ? 'decisionPassed' : 'decisionNeedsImprovement')}</span></div>` : ''}
            </div>`;

        container.appendChild(card);
        this._scrollToBottom();
        return card;
    },

    /* Render the welcome screen */
    renderWelcome() {
        const container = document.getElementById('messagesContainer');
        container.innerHTML = `<div class="welcome-screen" id="welcomeScreen">
            <div class="welcome-icon"><i class="fa-solid fa-wand-magic-sparkles"></i></div>
            <h1>${_t('welcome')}</h1>
            <p>${_t('welcomeDesc')}</p>
            <div class="welcome-suggestions">
                <button class="suggestion-chip">${_t('welcomeSuggest1')}</button>
                <button class="suggestion-chip">${_t('welcomeSuggest2')}</button>
                <button class="suggestion-chip">${_t('welcomeSuggest3')}</button>
                <button class="suggestion-chip">${_t('welcomeSuggest4')}</button>
            </div>
        </div>`;
    },

    showLoading(text = null) {
        const container = document.getElementById('messagesContainer');
        const welcome = document.getElementById('welcomeScreen');
        if (welcome) welcome.style.display = 'none';

        const div = document.createElement('div');
        div.className = 'message agent';
        div.id = 'loadingIndicator';
        div.innerHTML = `<div class="message-avatar"><i class="fa-solid fa-robot"></i></div><div class="message-content"><div class="loading-spinner"><span style="margin-right:8px;">${text || _t('agentThinking')}</span><span class="dot"></span><span class="dot"></span><span class="dot"></span></div></div>`;
        container.appendChild(div);
        this._scrollToBottom();
        return div;
    },

    removeLoading() {
        const el = document.getElementById('loadingIndicator');
        if (el) el.remove();
    },

    showToast(text, type = 'info') {
        const toast = document.createElement('div');
        toast.className = `toast ${type}`;
        toast.textContent = text;
        document.body.appendChild(toast);
        setTimeout(() => toast.remove(), 3000);
    },

    setLoading(loading) {
        AppState.isLoading = loading;
        const btn = document.getElementById('sendButton');
        const bar = document.getElementById('interruptBar');
        const status = document.getElementById('chatStatus');

        if (btn) btn.disabled = loading;
        if (bar) bar.style.display = loading ? 'flex' : 'none';
        if (status) {
            status.textContent = loading ? _t('generating') : _t('ready');
            status.classList.toggle('loading', loading);
        }
    },

    setProgress(current, max) {
        AppState.currentIteration = current;
        AppState.maxIterations = max;
        const status = document.getElementById('chatStatus');
        if (status) status.textContent = _t('iterationProgress', { current, max });
    },

    renderSessions(sessions) {
        const list = document.getElementById('conversationsList');
        if (!list) return;
        list.innerHTML = sessions.map(s =>
            `<div class="session-item ${s.id === AppState.currentSessionId ? 'active' : ''}" onclick="AppActions.selectSession('${s.id}')">
                <span class="session-icon"><i class="fa-solid fa-message"></i></span>
                <div class="session-info">
                    <div class="session-title">${s.user_request || _t('newSessionTitle')}</div>
                    <div class="session-date">${s.created_at ? new Date(s.created_at).toLocaleDateString() : ''}</div>
                </div>
                <button class="session-delete" onclick="event.stopPropagation(); AppActions.deleteSession('${s.id}')" title="${_t('sessionDelete')}">
                    <i class="fa-solid fa-trash"></i>
                </button>
            </div>`
        ).join('');
    },

    clearMessages() {
        this.renderWelcome();
        // re-bind suggestion chips
        document.querySelectorAll('.suggestion-chip').forEach(chip => {
            chip.addEventListener('click', () => {
                document.getElementById('promptInput').value = chip.textContent;
                AppActions.sendMessage();
            });
        });
    },

    /** Refresh all i18n text in static DOM elements. All operations are null-safe. */
    refreshI18n() {
        const $ = (id) => document.getElementById(id);
        const $$ = (sel) => document.querySelector(sel);

        const setText = (el, text) => { if (el) el.textContent = text; };
        const setTitle = (el, text) => { if (el) el.title = text; };
        const setPlaceholder = (el, text) => { if (el) el.placeholder = text; };

        // Lang toggle badge
        const langToggle = $('langToggle');
        if (langToggle) langToggle.setAttribute('data-lang', I18n.getLang() === 'zh-CN' ? '中' : 'EN');

        // Sidebar buttons
        const nsb = $('newSessionBtn');
        if (nsb) { const sp = nsb.querySelector('span'); if (sp) setText(sp, _t('newSession')); }
        const sb = $('settingsBtn');
        if (sb) { const sp = sb.querySelector('span'); if (sp) setText(sp, _t('parameters')); }

        // Chat header
        setTitle($('clearChatBtn'), _t('clearChatTitle'));

        // Input area
        setPlaceholder($('promptInput'), _t('inputPlaceholder'));
        setTitle($('sendButton'), _t('sendTitle'));

        // Interrupt bar
        const ibar = $('interruptBar');
        if (ibar) {
            const label = ibar.querySelector('.interrupt-label');
            if (label) setText(label, _t('interruptLabel'));
        }
        // Interrupt buttons — update text node after icon (childNodes[2])
        [$('acceptBtn'), $('steerBtn'), $('pauseBtn')].forEach(btn => {
            if (!btn) return;
            const key = btn.id === 'acceptBtn' ? 'acceptBtn' : btn.id === 'steerBtn' ? 'steerBtn' : 'pauseBtn';
            const titleKey = btn.id === 'acceptBtn' ? 'acceptTitle' : btn.id === 'steerBtn' ? 'steerTitle' : 'pauseTitle';
            setTitle(btn, _t(titleKey));
            // Update text after icon: <i>..</i> text
            const txt = btn.childNodes;
            for (let i = 0; i < txt.length; i++) {
                if (txt[i].nodeType === 3 && txt[i].textContent.trim()) {
                    txt[i].textContent = ' ' + _t(key);
                    break;
                }
            }
        });

        // Settings panel header
        const sh3 = $$('.settings-header h3');
        setText(sh3, _t('settingsTitle'));

        // Section titles
        const sections = document.querySelectorAll('.section-title');
        const sectionKeys = ['sectionImage', 'sectionQuality', 'sectionAgent', 'sectionModel'];
        sections.forEach((sec, i) => {
            if (i < sectionKeys.length && sec.childNodes.length > 1) {
                sec.childNodes[1].textContent = ' ' + _t(sectionKeys[i]);
            }
        });

        // Slider labels — update first span in each label
        [
            ['widthSlider', 'labelWidth'],
            ['heightSlider', 'labelHeight'],
            ['countSlider', 'labelCount'],
            ['stepsSlider', 'labelSteps'],
            ['guidanceSlider', 'labelGuidance'],
            ['seedInput', 'labelSeed'],
            ['maxIterSlider', 'labelMaxIter'],
            ['modelProvider', 'labelProvider'],
            ['modelName', 'labelModel'],
            ['modelApiBase', 'labelApiBase'],
            ['modelApiKey', 'labelApiKey'],
            ['modelTemperature', 'labelTemperature'],
        ].forEach(([forId, key]) => {
            const el = document.querySelector(`[for="${forId}"] span:first-child`);
            if (el) setText(el, _t(key));
        });

        // Checkbox labels
        const updateCheckboxLabel = (forId, key) => {
            const label = document.querySelector(`[for="${forId}"]`);
            if (label && label.parentElement) {
                const nodes = label.parentElement.childNodes;
                for (const n of nodes) {
                    if (n.nodeType === 3 && n.textContent.trim()) { n.textContent = _t(key); break; }
                    if (n.nodeType === 1 && n.tagName === 'LABEL') {
                        const labels = n.childNodes;
                        for (const ln of labels) {
                            if (ln.nodeType === 3 && ln.textContent.trim()) { ln.textContent = _t(key); break; }
                        }
                        break;
                    }
                }
            }
        };
        updateCheckboxLabel('autoAcceptCb', 'labelAutoAccept');
        updateCheckboxLabel('showIntermediateCb', 'labelShowIntermediate');

        // Action buttons
        setText($('applySettingsBtn'), _t('apply'));
        setText($('resetSettingsBtn'), _t('reset'));

        // Status bar
        const status = $('chatStatus');
        if (status && !AppState.isLoading) setText(status, _t('ready'));

        // Welcome screen
        const ws = $('welcomeScreen');
        if (ws) {
            const h1 = ws.querySelector('h1'); if (h1) setText(h1, _t('welcome'));
            const p = ws.querySelector('p'); if (p) setText(p, _t('welcomeDesc'));
        }

        updateSettingsUI();
    },

    _formatContent(content) {
        if (typeof content !== 'string') return String(content);
        return content
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/`([^`]+)`/g, '<code style="background:var(--bg);padding:2px 6px;border-radius:4px;font-size:13px;">$1</code>')
            .replace(/\n/g, '<br>');
    },

    _scrollToBottom() {
        const container = document.getElementById('messagesContainer');
        if (container) setTimeout(() => { container.scrollTop = container.scrollHeight; }, 50);
    }
};
