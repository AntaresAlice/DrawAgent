/**
 * EventRouter — dispatches backend events to UI updates.
 */
const EventRouter = {
    dispatch(event) {
        console.debug('[Event]', event.type, event);

        // Auto-detect agentic engine from first agentic event
        if (!AppState.isAgentic && ['turn.started', 'text.delta', 'tool.completed', 'session.finalized'].includes(event.type)) {
            AppState.isAgentic = true;
            ActivityStream.init();
        }

        // Agentic mode events — render via ActivityStream
        if (AppState.isAgentic) {
            switch (event.type) {
                case 'turn.started':
                    ActivityStream.onTurnStarted(event);
                    return;
                case 'turn.ended':
                    ActivityStream.onTurnEnded(event);
                    return;
                case 'text.delta':
                    ActivityStream.onTextDelta(event);
                    return;
                case 'tool.completed':
                    ActivityStream.onToolCompleted(event);
                    return;
                case 'tool.called':
                    ActivityStream.onToolCalled(event);
                    return;
                case 'tool.failed':
                    ActivityStream.onToolCompleted(event);  // same handler
                    return;
                case 'session.finalized':
                    ActivityStream.onFinalized(event);
                    AppState.loopStatus = null;
                    Renderer.removeLoading();
                    Renderer.setLoading(false);
                    return;
                case 'session.compacted':
                    ActivityStream.onCompacted(event);
                    return;
                case 'session.learned':
                    ActivityStream.onLearned(event);
                    return;
                case 'interrupt.accepted':
                    ActivityStream.onInterruptAccepted(event);
                    return;
                case 'loop.terminated':
                    Renderer.removeLoading();
                    Renderer.setLoading(false);
                    AppState.loopStatus = null;
                    return;
                case 'error':
                    Renderer.removeLoading();
                    Renderer.setLoading(false);
                    Renderer.addErrorCard(event.message || _t('errorOccurred'), AppState._lastUserPrompt);
                    return;
            }
        }

        switch (event.type) {
            case 'iteration.started':
                AppState.currentIteration = event.iteration || 1;
                Renderer.removeLoading();
                Renderer.showLoading();
                Renderer.setProgress(AppState.currentIteration, AppState.maxIterations);
                Renderer.addIterationCard(AppState.currentIteration, [], [], null);
                AppState._phase = 'planning';
                Renderer.setPhase('planning');
                break;

            case 'inspection.plan_ready':
                if (event.plan) {
                    Renderer.addInspectionPlan(event.plan);
                }
                break;

            case 'prompt.refined':
                if (event.after) {
                    Renderer.updateIterationPrompt(AppState.currentIteration, event.after);
                }
                Renderer.addSystemMessage(_t('promptRefined'));
                break;

            case 'generation.started':
                Renderer.setLoading(true);
                AppState._phase = 'generating';
                Renderer.setPhase('generating');
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
                AppState._phase = 'inspecting';
                Renderer.setPhase('inspecting');
                if (event.task && event.result) {
                    Renderer.addInspectionToCard(AppState.currentIteration, event.task, event.result);
                }
                break;

            case 'inspection.complete':
                Renderer.addSystemMessage(_t('allInspectionsDone'));
                break;

            case 'quality.decision':
                AppState._phase = 'evaluating';
                Renderer.setPhase('evaluating');
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
                Renderer.setPhase(null);
                Renderer.addSystemMessage(_t('loopTerminated', { reason: event.reason || '' }));
                AppState._phase = null;
                notifyComplete(event.reason);
                break;

            case 'agent.question':
                Renderer.removeLoading();
                Renderer.setLoading(false);
                Renderer.addClarificationCard(event.text || '');
                break;

            case 'user.steer':
                Renderer.addSystemMessage(_t('directionChanged', { prompt: event.prompt || '' }));
                break;

            case 'user.rollback':
                Renderer.addSystemMessage(_t('rollbackTo', { target: event.target || '' }));
                break;

            case 'clarification.needed':
                Renderer.removeLoading();
                Renderer.setLoading(false);
                Renderer.addClarificationCard(event.summary || '', event.estimated_iterations || 7);
                break;

            case 'error':
                Renderer.removeLoading();
                Renderer.setLoading(false);
                Renderer.addErrorCard(event.message || _t('errorOccurred'), AppState._lastUserPrompt);
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
        AppState._lastUserPrompt = text;
        input.value = '';
        input.style.height = 'auto';

        // Reset agentic stream on new message
        if (AppState.isAgentic) {
            ActivityStream.reset();
        }

        WSClient.disconnect();
        await WSClient.connect(AppState.currentSessionId);

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
        await WSClient.connect(AppState.currentSessionId);
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

            // Detect engine from history response
            if (history.engine === 'agentic') {
                AppState.isAgentic = true;
                ActivityStream.init();
                ActivityStream.restoreFromHistory(history);
            } else {
                AppState.isAgentic = false;
            }

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

    async applySettings() {
        const p = AppState.settings.generationParams;
        p.width = parseInt(document.getElementById('widthSlider').value);
        p.height = parseInt(document.getElementById('heightSlider').value);
        p.numImages = parseInt(document.getElementById('countSlider').value);
        p.steps = parseInt(document.getElementById('stepsSlider').value);
        p.guidance = parseFloat(document.getElementById('guidanceSlider').value);
        p.cfgTruncation = parseFloat(document.getElementById('cfgTruncSlider').value);
        p.seed = parseInt(document.getElementById('seedInput').value) || -1;
        AppState.settings.maxIterations = parseInt(document.getElementById('maxIterSlider').value);
        AppState.settings.autoAccept = document.getElementById('autoAcceptCb').checked;
        AppState.settings.showIntermediate = document.getElementById('showIntermediateCb').checked;

        AppState.saveSettings();
        updateQuickParamsUI();
        document.getElementById('settingsPanel').classList.remove('active');
        Renderer.showToast(_t('settingsApplied'), 'success');

        // Push generation params to backend so they take effect immediately
        try {
            await API.updateConfig({
                agent_b: {
                    default_params: {
                        width: p.width,
                        height: p.height,
                        steps: p.steps,
                        guidance: p.guidance,
                        cfg_truncation: p.cfgTruncation,
                        seed: p.seed,
                    },
                },
                loop: { max_iterations: AppState.settings.maxIterations },
            });
        } catch (e) {
            console.warn('Backend quick-params sync failed:', e);
        }
    },

    resetSettings() {
        AppState.settings.generationParams = { width: 960, height: 1280, numImages: 2, steps: 30, guidance: 7.0, seed: -1, cfgTruncation: 0.6 };
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
            model: document.getElementById('ssModelB').value,
            apiBase: document.getElementById('ssApiBaseB').value,
            endpoint: document.getElementById('ssEndpointB').value,
            mcpCommand: document.getElementById('ssMcpCommand').value,
            mcpToolName: document.getElementById('ssMcpToolName').value,
            mcpUrl: document.getElementById('ssMcpUrl').value,
            mcpKeepAlive: document.getElementById('ssMcpKeepAlive').checked,
            modelHints: document.getElementById('ssModelHints').value,
        };
        mc.agentC = {
            provider: document.getElementById('ssProviderC').value,
            model: document.getElementById('ssModelC').value,
            apiBase: document.getElementById('ssApiBaseC').value,
            apiKey: document.getElementById('ssApiKeyC').value,
            temperature: parseFloat(document.getElementById('ssTemperatureC').value) || 0.3,
        };
        mc.loop = {
            engine: document.getElementById('ssEngine').value,
        };
        // Reset mode tracking so next message uses correct event dispatch
        AppState.isAgentic = (mc.loop.engine === 'agentic');
        if (AppState.isAgentic) {
            ActivityStream.init();
        }
        AppState.saveSettings();
        document.getElementById('systemSettingsOverlay').classList.remove('active');
        updateEngineBadge();

        // Push config to backend so runtime uses new settings immediately
        try {
            const ssStep = document.getElementById('ssStepMode');
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
                    provider: mc.agentB.provider || '',
                    model: mc.agentB.model,
                    api_base: mc.agentB.apiBase,
                    endpoint: mc.agentB.endpoint,
                    mcp_command: mc.agentB.mcpCommand || null,
                    mcp_tool_name: mc.agentB.mcpToolName || 'generate_image',
                    mcp_url: mc.agentB.mcpUrl || '',
                    mcp_keep_alive: Boolean(mc.agentB.mcpKeepAlive),
                    model_hints: mc.agentB.modelHints || '',
                },
                agent_c: {
                    provider: mc.agentC.provider,
                    model: mc.agentC.model,
                    api_base: mc.agentC.apiBase,
                    api_key: mc.agentC.apiKey || null,
                    temperature: mc.agentC.temperature,
                },
                loop: {
                    engine: mc.loop.engine,
                    step_mode: ssStep ? ssStep.checked : false,
                },
            };
            const result = await API.updateConfig(backendConfig);
            if (result.updated) {
                Renderer.showToast(_t('systemSettingsSaved'), 'success');
            } else {
                Renderer.showToast(_t('systemSettingsSavedNote') + (result.note || ''), 'info');
            }
        } catch (e) {
            console.warn('Backend config sync failed:', e);
            Renderer.showToast(_t('systemSettingsSyncFailed') + e.message + ')', 'warning');
        }
    },

    resetSystemSettings() {
        AppState.settings.systemConfig = {
            agentA: { provider: 'openai', model: 'gpt-4o', apiBase: 'https://api.openai.com/v1', apiKey: '', temperature: 0.7 },
            agentB: { type: 'http', model: 'z-image', apiBase: 'http://localhost:8000', endpoint: '/api/generate', mcpCommand: '', mcpToolName: 'generate_image', mcpUrl: '', mcpKeepAlive: true, modelHints: '' },
            agentC: { provider: 'openai', model: 'gpt-4o', apiBase: 'https://api.openai.com/v1', apiKey: '', temperature: 0.3 },
            loop: { engine: 'classic' },
        };
        AppState.saveSettings();
        updateSystemSettingsUI();
        updateEngineBadge();
        Renderer.showToast(_t('systemSettingsReset'), 'success');
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
            Renderer.showToast(_t('exportFailed') + ': ' + e.message, 'error');
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
    set('cfgTruncSlider', p.cfgTruncation); txt('cfgTruncValue', p.cfgTruncation);
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
    set('ssTypeB', mb.type); set('ssModelB', mb.model || 'z-image');
    set('ssApiBaseB', mb.apiBase);
    set('ssEndpointB', mb.endpoint); set('ssMcpCommand', mb.mcpCommand);
    set('ssMcpToolName', mb.mcpToolName || 'generate_image');
    set('ssMcpUrl', mb.mcpUrl || '');
    const mcpKeepEl = document.getElementById('ssMcpKeepAlive');
    if (mcpKeepEl) mcpKeepEl.checked = mb.mcpKeepAlive !== false;
    set('ssModelHints', mb.modelHints || '');
    document.getElementById('mcpFieldsB').style.display = mb.type === 'mcp' ? 'block' : 'none';
    set('ssProviderC', mc_.provider); set('ssModelC', mc_.model);
    set('ssApiBaseC', mc_.apiBase); set('ssApiKeyC', mc_.apiKey);
    document.getElementById('ssTempValueC').textContent = mc_.temperature;
    const tc = document.getElementById('ssTemperatureC'); if (tc) tc.value = mc_.temperature;
    const loopCfg = mc.loop || {};
    set('ssEngine', loopCfg.engine || 'classic');
    const ssStep = document.getElementById('ssStepMode');
    if (ssStep) ssStep.checked = !!loopCfg.step_mode;
}

async function loadSystemConfig() {
    try {
        const config = await API.getConfig();
        const mc = AppState.settings.systemConfig;
        const keepKeys = { agentA: mc.agentA.apiKey, agentC: mc.agentC.apiKey };

        if (config.agent_a) {
            mc.agentA.provider = config.agent_a.provider || mc.agentA.provider;
            mc.agentA.model = config.agent_a.model || mc.agentA.model;
            mc.agentA.apiBase = config.agent_a.api_base || mc.agentA.apiBase;
            mc.agentA.temperature = config.agent_a.temperature != null ? config.agent_a.temperature : mc.agentA.temperature;
            mc.agentA.apiKey = keepKeys.agentA || '';  // never overwrite from backend
        }
        if (config.agent_b) {
            mc.agentB.type = config.agent_b.type || mc.agentB.type;
            mc.agentB.model = config.agent_b.model || mc.agentB.model;
            mc.agentB.apiBase = config.agent_b.api_base || mc.agentB.apiBase;
            mc.agentB.endpoint = config.agent_b.endpoint || mc.agentB.endpoint;
            mc.agentB.mcpCommand = config.agent_b.mcp_command || mc.agentB.mcpCommand || '';
            mc.agentB.mcpToolName = config.agent_b.mcp_tool_name || mc.agentB.mcpToolName || 'generate_image';
            mc.agentB.mcpUrl = config.agent_b.mcp_url || mc.agentB.mcpUrl || '';
            mc.agentB.mcpKeepAlive = config.agent_b.mcp_keep_alive;
            mc.agentB.modelHints = config.agent_b.model_hints || mc.agentB.modelHints || '';
        }
        if (config.agent_c) {
            mc.agentC.provider = config.agent_c.provider || mc.agentC.provider;
            mc.agentC.model = config.agent_c.model || mc.agentC.model;
            mc.agentC.apiBase = config.agent_c.api_base || mc.agentC.apiBase;
            mc.agentC.temperature = config.agent_c.temperature != null ? config.agent_c.temperature : mc.agentC.temperature;
            mc.agentC.apiKey = keepKeys.agentC || '';  // never overwrite from backend
        }
        if (config.loop) {
            AppState.settings.maxIterations = config.loop.max_iterations != null ? config.loop.max_iterations : AppState.settings.maxIterations;
            mc.loop = mc.loop || {};
            if (config.loop.engine) mc.loop.engine = config.loop.engine;
            if (config.loop.step_mode != null) mc.loop.step_mode = config.loop.step_mode;
        }
        AppState.saveSettings();
        updateSystemSettingsUI();
        updateQuickParamsUI();
        updateEngineBadge();
        console.debug('[Config] Loaded runtime config from backend');
    } catch (e) {
        console.warn('[Config] Failed to load config from backend, using localStorage:', e.message);
    }
}

function updateQuickParamsUI() {
    const p = AppState.settings.generationParams;
    const set = (id, v) => { const el = document.getElementById(id); if (el) el.value = v; };
    set('qpWidth', p.width); set('qpHeight', p.height); set('qpCount', p.numImages);
    set('qpSteps', p.steps); set('qpGuidance', p.guidance); set('qpSeed', p.seed);
    set('qpCfgTrunc', p.cfgTruncation);
    set('qpMaxIter', AppState.settings.maxIterations);
}

function syncQuickParams() {
    updateQuickParamsUI();
}

function updateEngineBadge() {
    const badge = document.getElementById('engineBadge');
    if (!badge) return;
    const mc = AppState.settings.systemConfig;
    const engine = (mc.loop && mc.loop.engine) || 'classic';
    badge.textContent = engine === 'agentic' ? '智能体' : '经典';
    badge.className = 'engine-badge' + (engine === 'agentic' ? ' agentic' : '');
}
