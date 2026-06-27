/**
 * EventRouter — dispatches backend events to UI updates.
 * Reference: opencode EventV2 → UI rendering pipeline.
 */
const EventRouter = {
    dispatch(event) {
        console.debug('[Event]', event.type, event);

        switch (event.type) {
            case 'iteration.started':
                Renderer.setProgress(event.iteration || 1, AppState.maxIterations);
                Renderer.addSystemMessage(`Starting iteration ${event.iteration || 1}...`);
                break;

            case 'inspection.plan_ready':
                Renderer.addSystemMessage('Inspection plan created.');
                break;

            case 'prompt.refined':
                Renderer.addSystemMessage('Prompt refined based on previous inspection results.');
                break;

            case 'generation.started':
                Renderer.setLoading(true);
                Renderer.addSystemMessage('Generating images...');
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
                    `Inspection '${event.task || 'task'}': ${event.result && event.result.passed ? 'PASSED' : 'FAILED'}`
                );
                break;

            case 'inspection.complete':
                Renderer.addSystemMessage('All inspections complete. Evaluating quality...');
                break;

            case 'quality.decision':
                if (event.decision) {
                    const d = event.decision;
                    if (d.passed) {
                        Renderer.addSystemMessage(`Quality check: PASSED (confidence: ${(d.confidence * 100).toFixed(0)}%)`);
                    } else {
                        Renderer.addSystemMessage(`Quality check: needs improvement — ${d.reasoning || ''}`);
                    }
                }
                break;

            case 'loop.terminated':
                Renderer.setLoading(false);
                Renderer.addSystemMessage(
                    `Loop terminated: ${event.reason || 'completed'}`
                );
                break;

            case 'agent.question':
                Renderer.addSystemMessage(`[Agent A] ${event.text || 'Question for you:'}`);
                break;

            case 'user.steer':
                Renderer.addSystemMessage(`Direction changed: ${event.prompt || ''}`);
                break;

            case 'error':
                Renderer.setLoading(false);
                Renderer.showToast(event.message || 'An error occurred', 'error');
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
            const data = await API.createSession();
            Renderer.clearMessages();
            Renderer.showToast('New session created', 'success');
            await this.refreshSessions();
        } catch (e) {
            Renderer.showToast('Failed to create session: ' + e.message, 'error');
        }
    },

    async sendMessage() {
        const input = document.getElementById('promptInput');
        const text = input.value.trim();
        if (!text || AppState.isLoading) return;

        // Create session if needed
        if (!AppState.currentSessionId) {
            await API.createSession(text);
        }

        Renderer.addMessage('user', text);
        input.value = '';
        input.style.height = 'auto';

        // Connect WebSocket
        WSClient.disconnect();
        WSClient.connect(AppState.currentSessionId);

        try {
            await API.sendMessage(text);
            Renderer.showLoading('Agent is thinking...');
        } catch (e) {
            Renderer.showToast('Failed to send message: ' + e.message, 'error');
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
            console.error('Failed to load session:', e);
        }
    },

    async deleteSession(sessionId) {
        if (!confirm('Delete this session?')) return;
        await API.deleteSession(sessionId);
        await this.refreshSessions();
        Renderer.showToast('Session deleted', 'info');
    },

    async refreshSessions() {
        try {
            const sessions = await API.listSessions();
            Renderer.renderSessions(sessions);
        } catch (e) {
            console.error('Failed to list sessions:', e);
        }
    },

    async acceptCurrent() {
        await API.sendInterrupt('accept_current');
        Renderer.showToast('Accepted current result', 'success');
    },

    async steer() {
        const msg = prompt('What direction should we go?');
        if (msg) {
            await API.sendInterrupt('steer', { message: msg });
            Renderer.showToast('Direction updated', 'info');
        }
    },

    async pauseResume() {
        if (AppState.isLoading) {
            await API.sendInterrupt('pause');
            Renderer.setLoading(false);
            Renderer.showToast('Paused', 'info');
        } else {
            await API.sendInterrupt('resume');
            Renderer.showToast('Resumed', 'info');
        }
    },

    applySettings() {
        AppState.settings.generationParams = {
            width: parseInt(document.getElementById('widthSlider').value),
            height: parseInt(document.getElementById('heightSlider').value),
            numImages: parseInt(document.getElementById('countSlider').value),
            steps: parseInt(document.getElementById('stepsSlider').value),
            guidance: parseFloat(document.getElementById('guidanceSlider').value),
            seed: parseInt(document.getElementById('seedInput').value) || -1,
        };
        AppState.settings.maxIterations = parseInt(document.getElementById('maxIterSlider').value);
        AppState.settings.autoAccept = document.getElementById('autoAcceptCb').checked;
        AppState.settings.showIntermediate = document.getElementById('showIntermediateCb').checked;
        AppState.saveSettings();
        document.getElementById('settingsPanel').classList.remove('active');
        Renderer.showToast('Settings applied', 'success');
    },

    resetSettings() {
        AppState.settings.generationParams = {
            width: 1024, height: 1024, numImages: 2,
            steps: 8, guidance: 3.5, seed: -1,
        };
        AppState.settings.maxIterations = 7;
        AppState.settings.autoAccept = false;
        AppState.settings.showIntermediate = true;
        AppState.saveSettings();
        updateSettingsUI();
        Renderer.showToast('Settings reset to defaults', 'success');
    },
};

/** Sync UI sliders with current settings */
function updateSettingsUI() {
    const p = AppState.settings.generationParams;
    document.getElementById('widthSlider').value = p.width;
    document.getElementById('widthValue').textContent = p.width;
    document.getElementById('heightSlider').value = p.height;
    document.getElementById('heightValue').textContent = p.height;
    document.getElementById('countSlider').value = p.numImages;
    document.getElementById('countValue').textContent = p.numImages;
    document.getElementById('stepsSlider').value = p.steps;
    document.getElementById('stepsValue').textContent = p.steps;
    document.getElementById('guidanceSlider').value = p.guidance;
    document.getElementById('guidanceValue').textContent = p.guidance;
    document.getElementById('seedInput').value = p.seed;
    document.getElementById('seedValue').textContent = p.seed === -1 ? '-1 (random)' : p.seed;
    document.getElementById('maxIterSlider').value = AppState.settings.maxIterations;
    document.getElementById('maxIterValue').textContent = AppState.settings.maxIterations;
    document.getElementById('autoAcceptCb').checked = AppState.settings.autoAccept;
    document.getElementById('showIntermediateCb').checked = AppState.settings.showIntermediate;
}
