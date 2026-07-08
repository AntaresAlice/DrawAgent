/**
 * Renderer — UI rendering: messages, images, iteration cards, error cards, compare view.
 */
const Renderer = {
    _lastIterationCard: null,

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

    addClarificationCard(summary, estIterations) {
        const container = document.getElementById('messagesContainer');
        const welcome = document.getElementById('welcomeScreen');
        if (welcome) welcome.style.display = 'none';

        const card = document.createElement('div');
        card.className = 'message agent';
        card.id = 'clarificationCard';
        const escSummary = this._escHtml(summary);
        card.innerHTML = `<div class="message-avatar"><i class="fa-solid fa-robot"></i></div>
            <div class="message-content">
                <div style="margin-bottom:10px;"><strong>需求确认</strong></div>
                <div style="color:var(--text-secondary);margin-bottom:12px;">${escSummary}</div>
                ${estIterations ? `<div style="font-size:12px;color:var(--text-secondary);margin-bottom:10px;">预计 ${estIterations} 轮迭代</div>` : ''}
                <div style="display:flex;gap:8px;">
                    <button class="btn btn-primary" style="flex:0;padding:6px 14px;font-size:12px;" onclick="WSClient.send({type:'clarify_accept'});document.getElementById('clarificationCard')?.remove();">
                        <i class="fa-solid fa-check"></i> 确认开始
                    </button>
                    <button class="btn btn-secondary" style="flex:0;padding:6px 14px;font-size:12px;" onclick="const extra=prompt('补充说明：');if(extra){WSClient.send({type:'clarify_modify',text:extra});document.getElementById('clarificationCard')?.remove();}">
                        <i class="fa-solid fa-pen-to-square"></i> 修改需求
                    </button>
                </div>
            </div>`;
        container.appendChild(card);
        this._scrollToBottom();
    },

    addErrorCard(message, retryPrompt = null) {
        const container = document.getElementById('messagesContainer');
        const welcome = document.getElementById('welcomeScreen');
        if (welcome) welcome.style.display = 'none';

        const retryText = retryPrompt || message;
        const escapedRetry = retryText.replace(/'/g, "\\'").replace(/"/g, '&quot;');
        const escapedMsg = this._escHtml(message);
        const card = document.createElement('div');
        card.className = 'message agent error-card';
        card.innerHTML = `<div class="message-avatar"><i class="fa-solid fa-circle-exclamation" style="color:var(--error);"></i></div>
            <div class="message-content" style="border-color:var(--error);background:rgba(239,68,68,0.05);">
                <div style="margin-bottom:8px;"><i class="fa-solid fa-triangle-exclamation" style="color:var(--error);"></i> <strong>错误</strong></div>
                <div style="color:var(--text-secondary);font-size:13px;margin-bottom:10px;">${escapedMsg}</div>
                <button class="btn btn-primary retry-btn" onclick="AppActions.retryMessage('${escapedRetry}')" style="font-size:12px;padding:6px 14px;flex:0;">
                    <i class="fa-solid fa-rotate-right"></i> 重试
                </button>
            </div>`;
        container.appendChild(card);
        this._scrollToBottom();
    },

    removeErrorCards() {
        document.querySelectorAll('.error-card').forEach(el => el.remove());
    },

    addIterationCard(number, images, inspections, decision) {
        const container = document.getElementById('messagesContainer');
        const welcome = document.getElementById('welcomeScreen');
        if (welcome) welcome.style.display = 'none';

        const card = document.createElement('div');
        card.className = 'iteration-card';
        card.setAttribute('data-iteration', number);
        card.setAttribute('data-prompt', (decision && decision.prompt) || '');
        this._lastIterationCard = card;

        const passed = decision && decision.passed;
        const statusClass = passed ? 'pass' : 'fail';
        const statusIcon = passed ? 'fa-circle-check' : 'fa-circle-exclamation';
        const statusText = _t(passed ? 'qualityPassed' : 'issuesFound');
        const escPrompt = this._escJsStr(decision && decision.prompt || '');

        // Get previous iteration's prompt for diff
        let diffHtml = '';
        if (number > 1 && decision && decision.prompt) {
            const prevCard = document.querySelector(`.iteration-card[data-iteration="${number - 1}"]`);
            const prevPrompt = prevCard ? prevCard.getAttribute('data-prompt') : '';
            if (prevPrompt && prevPrompt !== decision.prompt) {
                diffHtml = `<div class="iteration-prompt-diff">
                    <div class="iteration-prompt-header"><i class="fa-solid fa-code-compare"></i> ${_t('promptDiff')}</div>
                    ${Renderer._renderDiff(prevPrompt, decision.prompt)}
                </div>`;
            }
        }

        card.innerHTML = `<div class="iteration-header" onclick="this.parentElement.querySelector('.iteration-body').classList.toggle('collapsed')">
                <span class="iteration-badge">${_t('iterationBadge', { number })}</span>
                <span class="iteration-status ${statusClass}"><i class="fa-solid ${statusIcon}"></i> ${statusText}</span>
                <span style="flex:1;"></span>
                <button class="iteration-action-btn" title="对比" onclick="event.stopPropagation(); Renderer.openCompareView(${number})">
                    <i class="fa-solid fa-columns"></i>
                </button>
                <i class="fa-solid fa-chevron-down" style="color:var(--text-secondary);font-size:12px;"></i>
            </div>
            <div class="iteration-body">
                ${decision && decision.prompt ? `<div class="iteration-prompt-section">
                    <div class="iteration-prompt-header"><i class="fa-solid fa-pen-to-square"></i> ${_t('promptLabel')}<button class="copy-prompt-btn" onclick="navigator.clipboard.writeText('${escPrompt}');Renderer.showToast('已复制','success');event.stopPropagation();"><i class="fa-solid fa-copy"></i></button></div>
                    <div class="iteration-prompt">${this._formatContent(decision.prompt)}</div>
                </div>` : ''}
                ${diffHtml}
                ${images && images.length ? `<div class="iteration-images">${images.map((img, i) => {
                    const url = API.imageUrl(img.filename || (img.path && img.path.split('/').pop()) || '');
                    const isFav = AppState.favorites.has(url);
                    return `<div class="iteration-image-wrapper">
                        <img class="iteration-image" src="${url}" alt="${img.filename || 'image'}" title="${_t('seedLabel')}: ${img.seed} | ${img.width || ''}x${img.height || ''}" onclick="Viewer.open(${JSON.stringify(images.map(im => API.imageUrl(im.filename || (im.path && im.path.split('/').pop()) || '')).filter(Boolean))}, ${i})">
                        <div class="iteration-image-actions">
                            <a class="image-action-btn" href="${url}" download title="${_t('download')}"><i class="fa-solid fa-download"></i></a>
                            <button class="image-action-btn ${isFav ? 'favorited' : ''}" onclick="event.stopPropagation(); AppState.toggleFavorite('${url}'); this.classList.toggle('favorited');" title="${_t('favorite')}"><i class="fa-${isFav ? 'solid' : 'regular'} fa-star"></i></button>
                            <button class="image-action-btn" onclick="event.stopPropagation(); navigator.clipboard.writeText('${url}'); Renderer.showToast('已复制URL','success');" title="${_t('copyUrl')}"><i class="fa-solid fa-link"></i></button>
                        </div>
                    </div>`;
                }).join('')}</div>` : ''}
                ${inspections && inspections.length ? inspections.map(i => `<div class="inspection-item ${i.passed ? 'pass' : 'fail'}"><span class="status-icon"><i class="fa-solid ${i.passed ? 'fa-circle-check' : 'fa-circle-xmark'}"></i></span><div><strong>${this._escHtml(i.task_name || 'Inspection')}</strong><div style="color:var(--text-secondary);margin-top:2px;">${this._escHtml((i.observation || '').slice(0, 200))}</div></div></div>`).join('') : ''}
                ${decision ? `<div class="decision-banner ${decision.passed ? 'pass' : 'fail'}"><i class="fa-solid ${decision.passed ? 'fa-circle-check' : 'fa-circle-exclamation'}"></i><span>${this._escHtml(decision.reasoning || _t(decision.passed ? 'decisionPassed' : 'decisionNeedsImprovement'))}</span></div>` : ''}
            </div>`;

        container.appendChild(card);
        this._scrollToBottom();
        return card;
    },

    _renderDiff(oldText, newText) {
        const oldLines = oldText.split('\n');
        const newLines = newText.split('\n');
        const maxLen = Math.max(oldLines.length, newLines.length);
        let html = '<div style="font-family:monospace;font-size:12px;line-height:1.5;margin-top:4px;">';
        for (let i = 0; i < maxLen; i++) {
            const oldL = oldLines[i] || '';
            const newL = newLines[i] || '';
            if (oldL === newL) {
                html += `<div style="color:var(--text-secondary);">  ${this._escHtml(newL)}</div>`;
            } else if (!oldL) {
                html += `<div style="background:rgba(16,185,129,0.15);color:var(--success);">+ ${this._escHtml(newL)}</div>`;
            } else if (!newL) {
                html += `<div style="background:rgba(239,68,68,0.15);color:var(--error);">- ${this._escHtml(oldL)}</div>`;
            } else {
                html += `<div style="background:rgba(239,68,68,0.1);color:var(--error);">- ${this._escHtml(oldL)}</div>`;
                html += `<div style="background:rgba(16,185,129,0.1);color:var(--success);">+ ${this._escHtml(newL)}</div>`;
            }
        }
        html += '</div>';
        return html;
    },

    _escHtml(s) { return (s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); },

    _escJsStr(s) {
        return (s || '').replace(/\\/g, '\\\\').replace(/'/g, "\\'").replace(/\n/g, '\\n').replace(/\r/g, '');
    },

    addIterationImages(images, iteration) {
        // Called for incremental updates during generation
        const cards = document.querySelectorAll('.iteration-card');
        if (cards.length > 0) {
            const lastCard = cards[cards.length - 1];
            const body = lastCard.querySelector('.iteration-body');
            if (body && images && images.length) {
                const imagesDiv = body.querySelector('.iteration-images') || (() => {
                    const d = document.createElement('div');
                    d.className = 'iteration-images';
                    body.prepend(d);
                    return d;
                })();
                images.forEach((img, i) => {
                    const url = API.imageUrl(img.filename || (img.path && img.path.split('/').pop()) || '');
                    imagesDiv.insertAdjacentHTML('beforeend', `<div class="iteration-image-wrapper">
                        <img class="iteration-image" src="${url}" alt="${img.filename || 'image'}" onclick="Viewer.open(${JSON.stringify(images.map(im => API.imageUrl(im.filename || (im.path && im.path.split('/').pop()) || '')).filter(Boolean))}, ${i})">
                        <div class="iteration-image-actions">
                            <a class="image-action-btn" href="${url}" download><i class="fa-solid fa-download"></i></a>
                        </div>
                    </div>`);
                });
            }
        }
    },

    addIterationDecision(passed, confidence, reasoning, recommendation) {
        const cards = document.querySelectorAll('.iteration-card');
        if (cards.length > 0) {
            const lastCard = cards[cards.length - 1];
            const body = lastCard.querySelector('.iteration-body');
            const header = lastCard.querySelector('.iteration-header');
            if (header) {
                const status = header.querySelector('.iteration-status');
                if (status) {
                    status.className = `iteration-status ${passed ? 'pass' : 'fail'}`;
                    status.innerHTML = `<i class="fa-solid ${passed ? 'fa-circle-check' : 'fa-circle-exclamation'}"></i> ${_t(passed ? 'qualityPassed' : 'issuesFound')}`;
                }
            }
            if (body) {
                const existingBanner = body.querySelector('.decision-banner');
                if (existingBanner) existingBanner.remove();
                const banner = document.createElement('div');
                banner.className = `decision-banner ${passed ? 'pass' : 'fail'}`;
                const confPct = (confidence * 100).toFixed(0);
                banner.innerHTML = `<i class="fa-solid ${passed ? 'fa-circle-check' : 'fa-circle-exclamation'}"></i><span>${reasoning || _t(passed ? 'decisionPassed' : 'decisionNeedsImprovement')} (${_t('confidence')}: ${confPct}%)</span>`;
                body.appendChild(banner);
            }
        }
    },

    openCompareView(_iteration) {
        const overlay = document.getElementById('compareOverlay');
        const body = document.getElementById('compareBody');
        if (!overlay || !body) return;

        const cards = document.querySelectorAll('.iteration-card');
        if (cards.length < 2) {
            this.showToast('需要至少两轮迭代才能对比', 'info');
            return;
        }

        let html = '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:20px;">';
        cards.forEach((card, idx) => {
            const header = card.querySelector('.iteration-badge');
            const images = card.querySelectorAll('.iteration-image');
            const decision = card.querySelector('.decision-banner');
            const label = header ? header.textContent : `Iteration ${idx + 1}`;

            html += `<div style="background:var(--bg);border-radius:var(--radius-sm);padding:16px;">
                <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;">
                    <strong>${label}</strong>
                    <button class="btn btn-secondary" style="flex:0;font-size:11px;padding:4px 10px;" onclick="AppActions.rollbackTo(${idx})">回退到此</button>
                </div>
                <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:8px;">
                    ${Array.from(images).map(img => `<img src="${img.src}" style="width:120px;height:120px;object-fit:cover;border-radius:4px;" onclick="Viewer.open([${Array.from(images).map(im => `'${im.src}'`).join(',')}], 0)">`).join('')}
                </div>
                ${decision ? `<div style="font-size:12px;color:var(--text-secondary);">${decision.textContent || ''}</div>` : ''}
            </div>`;
        });
        html += '</div>';
        body.innerHTML = html;
        overlay.classList.add('active');
    },

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

        this.removeLoading();
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

    addInspectionProgress(taskName, passed) {
        this.addInspectionToCard(AppState.currentIteration, taskName, { passed });
    },

    setPhase(phase) {
        const status = document.getElementById('chatStatus');
        if (!status) return;
        const phaseKey = phase ? 'phase' + phase.charAt(0).toUpperCase() + phase.slice(1) : null;
        const label = phaseKey ? _t(phaseKey) : '';
        if (phase) {
            status.textContent = `${_t('iterationProgress', { current: AppState.currentIteration, max: AppState.maxIterations })} — ${label}`;
            status.classList.add('loading');
        } else {
            status.textContent = _t('ready');
            status.classList.remove('loading');
        }
    },

    addInspectionPlan(plan) {
        const card = this._getCard(AppState.currentIteration);
        if (!card) return;
        let body = card.querySelector('.iteration-body');
        if (!body) return;
        let section = body.querySelector('.inspection-plan-section');
        if (!section) {
            section = document.createElement('div');
            section.className = 'inspection-plan-section';
            body.appendChild(section);
        }
        const tasks = plan.map(t => `<div class="plan-task"><i class="fa-solid fa-circle"></i> ${this._escHtml(t.name || t.description || '')}</div>`).join('');
        section.innerHTML = `<div class="iteration-prompt-header"><i class="fa-solid fa-clipboard-check"></i> 检查计划 (${plan.length}项)</div><div class="plan-tasks">${tasks}</div>`;
    },

    updateIterationPrompt(iteration, prompt) {
        const card = this._getCard(iteration);
        if (!card) return;
        card.setAttribute('data-prompt', prompt);
        const body = card.querySelector('.iteration-body');
        if (!body) return;
        let section = body.querySelector('.iteration-prompt-section');
        if (!section) {
            section = document.createElement('div');
            section.className = 'iteration-prompt-section';
            body.insertBefore(section, body.firstChild);
        }
        section.innerHTML = `<div class="iteration-prompt-header"><i class="fa-solid fa-pen-to-square"></i> ${_t('promptLabel')}</div><div class="iteration-prompt">${this._formatContent(prompt)}</div>`;
    },

    addInspectionToCard(iteration, taskName, result) {
        const card = this._getCard(iteration);
        if (!card) return;
        const body = card.querySelector('.iteration-body');
        if (!body) return;
        let list = body.querySelector('.inspection-list');
        if (!list) {
            list = document.createElement('div');
            list.className = 'inspection-list';
            body.appendChild(list);
        }
        const existing = list.querySelector(`[data-task="${taskName.replace(/"/g, '')}"]`);
        if (existing) existing.remove();
        const item = document.createElement('div');
        item.className = `inspection-item ${result.passed ? 'pass' : 'fail'}`;
        item.setAttribute('data-task', taskName);
        item.innerHTML = `<span class="status-icon"><i class="fa-solid ${result.passed ? 'fa-circle-check' : 'fa-circle-xmark'}"></i></span><div><strong>${this._escHtml(taskName)}</strong><div style="color:var(--text-secondary);margin-top:2px;">${this._escHtml((result.observation || '').slice(0, 200))}</div></div>`;
        list.appendChild(item);
    },

    addActivityItem(title, subtitle, detail) {
        const card = this._getCard(AppState.currentIteration);
        if (!card) return;
        const body = card.querySelector('.iteration-body');
        if (!body) return;
        let log = body.querySelector('.activity-log');
        if (!log) {
            log = document.createElement('div');
            log.className = 'activity-log';
            body.insertBefore(log, body.firstChild);
        }
        const item = document.createElement('div');
        item.className = 'activity-item';
        const header = document.createElement('div');
        header.className = 'activity-header';
        header.innerHTML = `<span class="activity-title">${title}</span><span class="activity-subtitle">${subtitle || ''}</span><i class="fa-solid fa-chevron-down activity-chevron"></i>`;
        header.addEventListener('click', () => {
            item.classList.toggle('expanded');
        });
        item.appendChild(header);
        if (detail) {
            const body = document.createElement('div');
            body.className = 'activity-body';
            body.innerHTML = `<pre>${this._escHtml(detail)}</pre>`;
            item.appendChild(body);
        }
        log.appendChild(item);
        this._scrollToBottom();
    },

    _getCard(iteration) {
        return document.querySelector(`.iteration-card[data-iteration="${iteration}"]`);
    },

    showToast(text, type = 'info') {
        const toast = document.createElement('div');
        toast.className = `toast ${type}`;
        toast.textContent = text;
        document.body.appendChild(toast);
        setTimeout(() => { if (toast.parentNode) toast.remove(); }, 3000);
    },

    setLoading(loading) {
        AppState.isLoading = loading;
        const btn = document.getElementById('sendButton');
        const bar = document.getElementById('interruptBar');
        const status = document.getElementById('chatStatus');

        if (btn) btn.disabled = loading;
        if (bar) bar.style.display = loading ? 'flex' : 'none';
        if (status) {
            if (loading) {
                const phase = AppState._phase || 'generating';
                status.textContent = _t(phase === 'planning' ? 'phasePlanning' : 'phaseGenerating');
            } else {
                status.textContent = _t('ready');
            }
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
                    <div class="session-title">${this._escHtml(s.user_request || _t('newSessionTitle'))}</div>
                    <div class="session-date">${s.created_at ? new Date(s.created_at).toLocaleString() : ''}</div>
                </div>
                <button class="session-action-btn" onclick="event.stopPropagation(); AppActions.selectSession('${s.id}'); setTimeout(() => AppActions.exportSession(), 100);" title="${_t('download')}">
                    <i class="fa-solid fa-download"></i>
                </button>
                <button class="session-delete" onclick="event.stopPropagation(); AppActions.deleteSession('${s.id}')" title="${_t('sessionDelete')}">
                    <i class="fa-solid fa-trash"></i>
                </button>
            </div>`
        ).join('');
    },

    clearMessages() {
        this.renderWelcome();
        document.querySelectorAll('.suggestion-chip').forEach(chip => {
            chip.addEventListener('click', () => {
                document.getElementById('promptInput').value = chip.textContent;
                AppActions.sendMessage();
            });
        });
    },

    refreshI18n() {
        const $ = (id) => document.getElementById(id);
        const setText = (el, text) => { if (el) el.textContent = text; };
        const setPlaceholder = (el, text) => { if (el) el.placeholder = text; };

        const langToggle = $('langToggle');
        if (langToggle) langToggle.setAttribute('data-lang', I18n.getLang() === 'zh-CN' ? '中' : 'EN');

        setPlaceholder($('promptInput'), _t('inputPlaceholder'));
        setText($('chatStatus'), _t('ready'));

        updateSettingsUI();
        updateQuickParamsUI();
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
