/**
 * EventRouter — dispatches backend events to UI updates.
 */
const EventRouter = {
    dispatch(event) {
        console.debug('[Event]', event.type, event);

        switch (event.type) {
            case 'iteration.started':
                Renderer.setProgress(event.iteration || 1, AppState.maxIterations);
                break;

            case 'inspection.plan_ready':
                break;

            case 'prompt.refined':
                Renderer.addSystemMessage(_t('promptRefined'));
                break;

            case 'generation.started':
                Renderer.setLoading(true);
                AppState._phase = 'generating';
                break;

            case 'images.ready':
                Renderer.removeLoading();
                if (event.images && event.images.length) {
                    const imgPaths = event.images.map(img =>
                        API.imageUrl(img.filename || (img.path && img.path.split('/').pop()) || '')
                    ).filter(Boolean);
                    if (imgPaths.length) {
                        AppState.viewer.images = AppState.viewer.images.concat(imgPaths);
                    }
                    Renderer.addIterationImages(event.images, event.iteration || AppState.currentIteration);
                }
                break;

            case 'inspection.task_done':
                break;

            case 'inspection.complete':
                break;

            case 'quality.decision':
                if (event.decision) {
                    const d = event.decision;
                    Renderer.addIterationDecision(
                        d.passed,
                        d.confidence,
                        d.reasoning || '',
                        d.recommendation || ''
                    );
                }
                break;

            case 'loop.terminated':
                Renderer.setLoading(false);
                Renderer.addSystemMessage(_t('loopTerminated', { reason: event.reason || '' }));
                AppState._phase = null;
                notifyComplete(event.reason);
                break;

            case 'agent.question':
                Renderer.addClarificationCard(event.text || '');
                break;

            case 'user.steer':
                Renderer.addSystemMessage(_t('directionChanged', { prompt: event.prompt || '' }));
                break;

            case 'user.rollback':
                Renderer.addSystemMessage(_t('rollbackTo', { target: event.target || '' }));
                break;

            case 'clarification.needed':
                Renderer.addClarificationCard(event.summary || '', event.estimated_iterations || 7);
                break;

            case 'error':
                Renderer.removeLoading();
                Renderer.setLoading(false);
                Renderer.addErrorCard(event.message || _t('errorOccurred'));
                break;

            default:
                console.debug('[Event] Unhandled:', event.type);
        }
    }
};

function notifyComplete(reason) {
    if (document.visibilityState !== 'visible' && 'Notification' in window && Notification.permission === 'granted') {
        new Notification('DrawAgent', { body: _t('generationComplete', { reason: reason || '' }) });
    }
}

/**
 * AppActions — user-initiated actions.
 */
const AppActions = {
    async newSession() {
        try {
            await API.createSession();
            Renderer.clearMessages();
            Renderer.showToast(_t('newSessionCreated'), 'success');
            await this.refreshSessions();
            AppState.viewer.images = [];
        } catch (e) {
            Renderer.showToast(_t('createFailed') + e.message, 'error');
        }
    },

    async sendMessage() {
        const input = document.getElementById('promptInput');
        const text = input.value.trim();
        if (!text || AppState.isLoading) return;

        console.debug('[Action] sendMessage:', text.slice(0, 100));

        if (!AppState.currentSessionId) {
            await API.createSession(text);
        }

        Renderer.addMessage('user', text);
        input.value = '';
        input.style.height = 'auto';

        WSClient.disconnect();
        WSClient.connect(AppState.currentSessionId);

        try {
            await API.sendMessage(text);
            Renderer.showLoading();
            AppState.viewer.images = [];
        } catch (e) {
            Renderer.showToast(_t('sendFailed') + e.message, 'error');
            Renderer.setLoading(false);
        }
    },

    async retryMessage(text) {
        if (!AppState.currentSessionId) return;
        Renderer.removeErrorCards();
        WSClient.disconnect();
        WSClient.connect(AppState.currentSessionId);
        try {
            await API.sendMessage(text);
            Renderer.showLoading();
            AppState.viewer.images = [];
        } catch (e) {
            Renderer.showToast(_t('sendFailed') + e.message, 'error');
            Renderer.setLoading(false);
        }
    },

    async selectSession(sessionId) {
        AppState.currentSessionId = sessionId;
        WSClient.disconnect();
        WSClient.connect(sessionId);
        try {
            const history = await API.getHistory();
            Renderer.clearMessages();
            AppState.viewer.images = [];
            if (history.messages) {
                history.messages.forEach(m => Renderer.addMessage(m.role, m.content));
            }
            if (history.iterations) {
                history.iterations.forEach(it => {
                    Renderer.addIterationCard(it.number, it.images, it.inspections, {
                        passed: it.passed,
                        reasoning: it.decision_reasoning,
                        prompt: it.prompt,
                    });
                });
            }
            document.getElementById('exportSessionBtn').style.display = 'inline-block';
            await this.refreshSessions();
        } catch (e) {
            console.error(_t('loadFailed'), e);
        }
    },

    async deleteSession(sessionId) {
        if (!confirm(_t('deleteConfirm'))) return;
        await API.deleteSession(sessionId);
        await this.refreshSessions();
        Renderer.showToast(_t('sessionDeleted'), 'info');
    },

    async refreshSessions() {
        try {
            const sessions = await API.listSessions();
            Renderer.renderSessions(sessions);
        } catch (e) {
            console.error(_t('listFailed'), e);
        }
    },

    async acceptCurrent() {
        await API.sendInterrupt('accept_current');
        Renderer.showToast(_t('acceptedResult'), 'success');
    },

    async steer() {
        const msg = prompt(_t('steerPrompt'));
        if (msg) {
            await API.sendInterrupt('steer', { message: msg });
            Renderer.showToast(_t('directionUpdated'), 'info');
        }
    },

    async pauseResume() {
        if (AppState.isLoading) {
            await API.sendInterrupt('pause');
            Renderer.setLoading(false);
            Renderer.showToast(_t('paused'), 'info');
        } else {
            await API.sendInterrupt('resume');
            Renderer.showToast(_t('resumed'), 'info');
        }
    },

    async rollbackTo(iteration) {
        if (!confirm(_t('rollbackTo', { target: iteration }))) return;
        await API.sendInterrupt('rollback', { target_iteration: iteration });
        Renderer.showToast(_t('rollbackApplied'), 'info');
    },

    applySettings() {
        const p = AppState.settings.generationParams;
        p.width = parseInt(document.getElementById('widthSlider').value);
        p.height = parseInt(document.getElementById('heightSlider').value);
        p.numImages = parseInt(document.getElementById('countSlider').value);
        p.steps = parseInt(document.getElementById('stepsSlider').value);
        p.guidance = parseFloat(document.getElementById('guidanceSlider').value);
        p.seed = parseInt(document.getElementById('seedInput').value) || -1;
        AppState.settings.maxIterations = parseInt(document.getElementById('maxIterSlider').value);
        AppState.settings.autoAccept = document.getElementById('autoAcceptCb').checked;
        AppState.settings.showIntermediate = document.getElementById('showIntermediateCb').checked;

        AppState.saveSettings();
        updateQuickParamsUI();
        document.getElementById('settingsPanel').classList.remove('active');
        Renderer.showToast(_t('settingsApplied'), 'success');
    },

    resetSettings() {
        AppState.settings.generationParams = { width: 1024, height: 1024, numImages: 2, steps: 8, guidance: 3.5, seed: -1 };
        AppState.settings.maxIterations = 7;
        AppState.settings.autoAccept = false;
        AppState.settings.showIntermediate = true;
        AppState.saveSettings();
        updateSettingsUI();
        updateQuickParamsUI();
        Renderer.showToast(_t('settingsReset'), 'success');
    },

    async applySystemSettings() {
        const mc = AppState.settings.systemConfig;
        mc.agentA = {
            provider: document.getElementById('ssProviderA').value,
            model: document.getElementById('ssModelA').value,
            apiBase: document.getElementById('ssApiBaseA').value,
            apiKey: document.getElementById('ssApiKeyA').value,
            temperature: parseFloat(document.getElementById('ssTemperatureA').value) || 0.7,
        };
        mc.agentB = {
            type: document.getElementById('ssTypeB').value,
            apiBase: document.getElementById('ssApiBaseB').value,
            endpoint: document.getElementById('ssEndpointB').value,
            mcpCommand: document.getElementById('ssMcpCommand').value,
        };
        mc.agentC = {
            provider: document.getElementById('ssProviderC').value,
            model: document.getElementById('ssModelC').value,
            apiBase: document.getElementById('ssApiBaseC').value,
            apiKey: document.getElementById('ssApiKeyC').value,
            temperature: parseFloat(document.getElementById('ssTemperatureC').value) || 0.3,
        };
        AppState.saveSettings();
        document.getElementById('systemSettingsOverlay').classList.remove('active');

        // Push config to backend so runtime uses new settings immediately
        try {
            const backendConfig = {
                agent_a: {
                    provider: mc.agentA.provider,
                    model: mc.agentA.model,
                    api_base: mc.agentA.apiBase,
                    api_key: mc.agentA.apiKey || null,
                    temperature: mc.agentA.temperature,
                },
                agent_b: {
                    type: mc.agentB.type,
                    api_base: mc.agentB.apiBase,
                    endpoint: mc.agentB.endpoint,
                    mcp_command: mc.agentB.mcpCommand ? mc.agentB.mcpCommand.split(/\s+/) : null,
                },
                agent_c: {
                    provider: mc.agentC.provider,
                    model: mc.agentC.model,
                    api_base: mc.agentC.apiBase,
                    api_key: mc.agentC.apiKey || null,
                    temperature: mc.agentC.temperature,
                },
            };
            const result = await API.updateConfig(backendConfig);
            if (result.updated) {
                Renderer.showToast('系统设置已保存并生效', 'success');
            } else {
                Renderer.showToast('设置已保存 (' + (result.note || '') + ')', 'info');
            }
        } catch (e) {
            console.warn('Backend config sync failed:', e);
            Renderer.showToast('设置已保存 (服务同步失败: ' + e.message + ')', 'warning');
        }
    },

    resetSystemSettings() {
        AppState.settings.systemConfig = {
            agentA: { provider: 'openai', model: 'gpt-4o', apiBase: 'https://api.openai.com/v1', apiKey: '', temperature: 0.7 },
            agentB: { type: 'http', apiBase: 'http://localhost:8000', endpoint: '/api/generate', mcpCommand: '' },
            agentC: { provider: 'openai', model: 'gpt-4o', apiBase: 'https://api.openai.com/v1', apiKey: '', temperature: 0.3 },
        };
        AppState.saveSettings();
        updateSystemSettingsUI();
        Renderer.showToast('系统设置已重置', 'success');
    },

    async exportSession() {
        if (!AppState.currentSessionId) return;
        try {
            const resp = await fetch(API.baseUrl() + '/api/sessions/' + AppState.currentSessionId + '/export');
            if (!resp.ok) throw new Error('Export failed');
            const blob = await resp.blob();
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'drawagent_' + AppState.currentSessionId + '.zip';
            a.click();
            URL.revokeObjectURL(url);
            Renderer.showToast(_t('exportSuccess', { id: AppState.currentSessionId }), 'success');
        } catch (e) {
            Renderer.showToast('导出失败: ' + e.message, 'error');
        }
    },

    /** Request desktop notification permission */
    requestNotificationPermission() {
        if ('Notification' in window && Notification.permission === 'default') {
            Notification.requestPermission();
        }
    },
};

function updateSettingsUI() {
    const p = AppState.settings.generationParams;
    const $ = (id) => document.getElementById(id);
    const set = (id, v) => { const el = $(id); if (el) el.value = v; };
    const txt = (id, v) => { const el = $(id); if (el) el.textContent = v; };
    set('widthSlider', p.width); txt('widthValue', p.width);
    set('heightSlider', p.height); txt('heightValue', p.height);
    set('countSlider', p.numImages); txt('countValue', p.numImages);
    set('stepsSlider', p.steps); txt('stepsValue', p.steps);
    set('guidanceSlider', p.guidance); txt('guidanceValue', p.guidance);
    set('maxIterSlider', AppState.settings.maxIterations); txt('maxIterValue', AppState.settings.maxIterations);
    set('seedInput', p.seed);
    txt('seedValue', p.seed === -1 ? '-1 (' + _t('labelRandom') + ')' : p.seed);
    const aa = $('autoAcceptCb'); if (aa) aa.checked = AppState.settings.autoAccept;
    const si = $('showIntermediateCb'); if (si) si.checked = AppState.settings.showIntermediate;
}

function updateSystemSettingsUI() {
    const mc = AppState.settings.systemConfig;
    const set = (id, v) => { const el = document.getElementById(id); if (el) el.value = v; };
    const ma = mc.agentA; const mb = mc.agentB; const mc_ = mc.agentC;
    set('ssProviderA', ma.provider); set('ssModelA', ma.model);
    set('ssApiBaseA', ma.apiBase); set('ssApiKeyA', ma.apiKey);
    set('ssTemperatureA', ma.temperature);
    document.getElementById('ssTempValueA').textContent = ma.temperature;
    set('ssTypeB', mb.type); set('ssApiBaseB', mb.apiBase);
    set('ssEndpointB', mb.endpoint); set('ssMcpCommand', mb.mcpCommand);
    document.getElementById('mcpFieldsB').style.display = mb.type === 'mcp' ? 'block' : 'none';
    set('ssProviderC', mc_.provider); set('ssModelC', mc_.model);
    set('ssApiBaseC', mc_.apiBase); set('ssApiKeyC', mc_.apiKey);
    document.getElementById('ssTempValueC').textContent = mc_.temperature;
    const tc = document.getElementById('ssTemperatureC'); if (tc) tc.value = mc_.temperature;
}

function updateQuickParamsUI() {
    const p = AppState.settings.generationParams;
    const set = (id, v) => { const el = document.getElementById(id); if (el) el.value = v; };
    set('qpWidth', p.width); set('qpHeight', p.height); set('qpCount', p.numImages);
    set('qpSteps', p.steps); set('qpGuidance', p.guidance); set('qpSeed', p.seed);
    set('qpMaxIter', AppState.settings.maxIterations);
}

function syncQuickParams() {
    // Read quick params from AppState settings on load
    updateQuickParamsUI();
}
