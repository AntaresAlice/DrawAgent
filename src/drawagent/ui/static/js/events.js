/**
 * EventRouter — dispatches backend events to UI updates.
 */
const EventRouter = {
    dispatch(event) {
        console.debug('[Event]', event.type, event);

        switch (event.type) {
            case 'iteration.started':
                Renderer.setProgress(event.iteration || 1, AppState.maxIterations);
                Renderer.addSystemMessage(_t('iterationStarted', { iteration: event.iteration || 1 }));
                break;

            case 'inspection.plan_ready':
                Renderer.addSystemMessage(_t('inspectionPlanReady'));
                break;

            case 'prompt.refined':
                Renderer.addSystemMessage(_t('promptRefined'));
                break;

            case 'generation.started':
                Renderer.setLoading(true);
                Renderer.addSystemMessage(_t('generatingImages'));
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
                }
                break;

            case 'inspection.task_done':
                Renderer.addSystemMessage(
                    _t(event.result && event.result.passed ? 'inspectionDonePass' : 'inspectionDoneFail', { task: event.task || 'task' })
                );
                break;

            case 'inspection.complete':
                Renderer.addSystemMessage(_t('allInspectionsDone'));
                break;

            case 'quality.decision':
                if (event.decision) {
                    const d = event.decision;
                    Renderer.addSystemMessage(
                        d.passed
                            ? _t('qualityDecisionPass', { confidence: (d.confidence * 100).toFixed(0) })
                            : _t('qualityDecisionFail', { reason: d.reasoning || '' })
                    );
                }
                break;

            case 'loop.terminated':
                Renderer.setLoading(false);
                Renderer.addSystemMessage(_t('loopTerminated', { reason: event.reason || '' }));
                break;

            case 'agent.question':
                Renderer.addSystemMessage(_t('agentQuestion', { text: event.text || '' }));
                break;

            case 'user.steer':
                Renderer.addSystemMessage(_t('directionChanged', { prompt: event.prompt || '' }));
                break;

            case 'error':
                Renderer.setLoading(false);
                Renderer.showToast(event.message || _t('errorOccurred'), 'error');
                break;

            default:
                console.debug('[Event] Unhandled:', event.type);
        }
    }
};

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
        } catch (e) {
            Renderer.showToast(_t('createFailed') + e.message, 'error');
        }
    },

    async sendMessage() {
        const input = document.getElementById('promptInput');
        const text = input.value.trim();
        if (!text || AppState.isLoading) return;

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
            if (history.messages) {
                history.messages.forEach(m => Renderer.addMessage(m.role, m.content));
            }
            if (history.iterations) {
                history.iterations.forEach(it => {
                    Renderer.addIterationCard(it.number, it.images, it.inspections, {
                        passed: it.passed,
                        reasoning: it.decision_reasoning,
                    });
                });
            }
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
        Renderer.showToast(_t('settingsReset'), 'success');
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
