/**
 * i18n — internationalization module.
 * Default: zh-CN, with en fallback. Toggle via AppState.settings.lang.
 */
const I18n = {
    _lang: "zh-CN",

    strings: {
        "zh-CN": {
            welcome: "DrawAgent",
            welcomeDesc: "描述你想要的图像，我来为你生成。",
            welcomeSuggest1: "一只猫坐在窗台上，金色阳光照进来",
            welcomeSuggest2: "夜晚的未来城市景观，霓虹灯闪烁",
            welcomeSuggest3: "一位身着铠甲的战士公主肖像",
            welcomeSuggest4: "宁静的日本庭院，樱花飘落",

            newSession: "新建会话",
            parameters: "生成参数",
            clearChatTitle: "清空对话",
            sidebarToggle: "切换侧边栏",
            ready: "就绪",
            generating: "生成中...",
            iterationProgress: "第 {current}/{max} 轮",

            inputPlaceholder: "描述你想要生成的图像...",
            sendTitle: "发送 (Ctrl+Enter)",
            interruptLabel: "正在生成",
            acceptBtn: "接受",
            acceptTitle: "接受当前结果",
            steerBtn: "修改方向",
            steerTitle: "调整方向",
            pauseBtn: "暂停",
            pauseTitle: "暂停",

            settingsTitle: "生成参数",
            sectionImage: "图像",
            labelWidth: "宽度",
            labelHeight: "高度",
            labelCount: "每轮张数",
            sectionQuality: "质量",
            labelSteps: "步数",
            labelGuidance: "引导力",
            labelSeed: "种子",
            labelRandom: "随机",
            sectionAgent: "智能体",
            labelMaxIter: "最大轮数",
            labelAutoAccept: "质量达标时自动接受",
            labelShowIntermediate: "显示中间结果",
            apply: "应用",
            reset: "重置",

            newSessionCreated: "新会话已创建",
            sessionDeleted: "会话已删除",
            settingsApplied: "设置已应用",
            settingsReset: "恢复默认设置",
            acceptedResult: "已接受当前结果",
            directionUpdated: "方向已更新",
            paused: "已暂停",
            resumed: "已恢复",
            newSessionTitle: "新会话",
            deleteConfirm: "确定要删除此会话吗？",
            clearConfirm: "确定要清空当前对话吗？",
            steerPrompt: "想要调整到什么方向？",
            sendFailed: "发送消息失败：",
            createFailed: "创建会话失败：",

            qualityPassed: "质量通过",
            issuesFound: "存在问题",
            iterationBadge: "第 {number} 轮",
            decisionPassed: "通过",
            decisionNeedsImprovement: "需要改进",

            iterationStarted: "开始第 {iteration} 轮迭代...",
            inspectionPlanReady: "检查计划已创建。",
            promptRefined: "提示词已根据上一轮检查结果优化。",
            generatingImages: "正在生成图像...",
            inspectionDonePass: "检查 '{task}': 通过",
            inspectionDoneFail: "检查 '{task}': 未通过",
            allInspectionsDone: "所有检查完成，正在评估质量...",
            qualityDecisionPass: "质量评估: 通过 (置信度: {confidence}%)",
            qualityDecisionFail: "质量评估: 需要改进 — {reason}",
            loopTerminated: "循环终止: {reason}",
            agentQuestion: "[Agent A] {text}",
            directionChanged: "方向已修改: {prompt}",
            errorOccurred: "发生错误",

            seedLabel: "种子",
            agentThinking: "智能体思考中...",
            loadFailed: "加载会话失败",
            listFailed: "获取会话列表失败",

            sessionDelete: "删除",
            sectionModel: "模型配置",
            labelProvider: "Provider",
            labelModel: "模型",
            labelApiBase: "API Base URL",
            labelApiKey: "API Key",
            labelTemperature: "Temperature",

            download: "下载",
            favorite: "收藏",
            copyUrl: "复制链接",
            phasePlanning: "规划中...",
            phaseGenerating: "生成中...",
            phaseInspecting: "检查中...",
            phaseEvaluating: "评估中...",
            generationComplete: "生成完成: {reason}",
            promptLabel: "提示词",
            confidence: "置信度",
            rollbackTo: "回退到第 {target} 轮",
            rollbackApplied: "已回退",
            exportSuccess: "会话已导出",
            promptDiff: "提示词变更",
            systemSettingsSaved: "系统设置已保存并生效",
            systemSettingsSavedNote: "设置已保存",
            systemSettingsSyncFailed: "设置已保存 (服务同步失败: ",
            systemSettingsReset: "系统设置已重置",
            exportFailed: "导出失败",
        },
        "en": {
            welcome: "DrawAgent",
            welcomeDesc: "Describe the image you want, and I'll create it for you.",
            welcomeSuggest1: "A cat sitting on a windowsill, golden hour lighting",
            welcomeSuggest2: "A futuristic cityscape at night with neon lights",
            welcomeSuggest3: "A portrait of a warrior princess in armor",
            welcomeSuggest4: "A serene Japanese garden with cherry blossoms",

            newSession: "New Session",
            parameters: "Parameters",
            clearChatTitle: "Clear chat",
            sidebarToggle: "Toggle sidebar",
            ready: "Ready",
            generating: "Generating...",
            iterationProgress: "Iteration {current}/{max}",

            inputPlaceholder: "Describe the image you want to generate...",
            sendTitle: "Send (Ctrl+Enter)",
            interruptLabel: "Generation in progress",
            acceptBtn: "Accept",
            acceptTitle: "Accept current result",
            steerBtn: "Steer",
            steerTitle: "Modify direction",
            pauseBtn: "Pause",
            pauseTitle: "Pause",

            settingsTitle: "Generation Parameters",
            sectionImage: "Image",
            labelWidth: "Width",
            labelHeight: "Height",
            labelCount: "Images per round",
            sectionQuality: "Quality",
            labelSteps: "Steps",
            labelGuidance: "Guidance",
            labelSeed: "Seed",
            labelRandom: "Random",
            sectionAgent: "Agent",
            labelMaxIter: "Max Iterations",
            labelAutoAccept: "Auto-accept when quality is met",
            labelShowIntermediate: "Show intermediate results",
            apply: "Apply",
            reset: "Reset",

            newSessionCreated: "New session created",
            sessionDeleted: "Session deleted",
            settingsApplied: "Settings applied",
            settingsReset: "Settings reset to defaults",
            acceptedResult: "Accepted current result",
            directionUpdated: "Direction updated",
            paused: "Paused",
            resumed: "Resumed",
            newSessionTitle: "New Session",
            deleteConfirm: "Delete this session?",
            clearConfirm: "Clear current chat?",
            steerPrompt: "What direction should we go?",
            sendFailed: "Failed to send message: ",
            createFailed: "Failed to create session: ",

            qualityPassed: "Quality passed",
            issuesFound: "Issues found",
            iterationBadge: "Iteration {number}",
            decisionPassed: "Passed",
            decisionNeedsImprovement: "Needs improvement",

            iterationStarted: "Starting iteration {iteration}...",
            inspectionPlanReady: "Inspection plan created.",
            promptRefined: "Prompt refined based on previous inspection results.",
            generatingImages: "Generating images...",
            inspectionDonePass: "Inspection '{task}': PASSED",
            inspectionDoneFail: "Inspection '{task}': FAILED",
            allInspectionsDone: "All inspections complete. Evaluating quality...",
            qualityDecisionPass: "Quality check: PASSED (confidence: {confidence}%)",
            qualityDecisionFail: "Quality check: needs improvement — {reason}",
            loopTerminated: "Loop terminated: {reason}",
            agentQuestion: "[Agent A] {text}",
            directionChanged: "Direction changed: {prompt}",
            errorOccurred: "An error occurred",

            seedLabel: "Seed",
            agentThinking: "Agent is thinking...",
            loadFailed: "Failed to load session",
            listFailed: "Failed to list sessions",

            sessionDelete: "Del",
            sectionModel: "Model Config",
            labelProvider: "Provider",
            labelModel: "Model",
            labelApiBase: "API Base URL",
            labelApiKey: "API Key",
            labelTemperature: "Temperature",

            download: "Download",
            favorite: "Favorite",
            copyUrl: "Copy URL",
            phasePlanning: "Planning...",
            phaseGenerating: "Generating...",
            phaseInspecting: "Inspecting...",
            phaseEvaluating: "Evaluating...",
            generationComplete: "Generation complete: {reason}",
            promptLabel: "Prompt",
            confidence: "Confidence",
            rollbackTo: "Rollback to iteration {target}",
            rollbackApplied: "Rollback applied",
            exportSuccess: "Session exported",
            promptDiff: "Prompt Changes",
            systemSettingsSaved: "System settings saved and applied",
            systemSettingsSavedNote: "Settings saved",
            systemSettingsSyncFailed: "Settings saved (server sync failed: ",
            systemSettingsReset: "System settings reset",
            exportFailed: "Export failed",
        }
    },

    init() {
        const lang = AppState.settings.lang || "zh-CN";
        this.setLang(lang);
    },

    setLang(lang) {
        if (!this.strings[lang]) lang = "zh-CN";
        this._lang = lang;
        document.documentElement.lang = lang === "zh-CN" ? "zh-CN" : "en";
        AppState.settings.lang = lang;
        AppState.saveSettings();
    },

    t(key, params = {}) {
        let text = (this.strings[this._lang] && this.strings[this._lang][key])
            || (this.strings["en"] && this.strings["en"][key])
            || key;
        for (const [k, v] of Object.entries(params)) {
            text = text.replace(`{${k}}`, v);
        }
        return text;
    },

    getLang() { return this._lang; },

    toggleLang() {
        this.setLang(this._lang === "zh-CN" ? "en" : "zh-CN");
        return this._lang;
    }
};
