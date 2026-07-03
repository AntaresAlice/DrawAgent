# 前后端修复计划

> 基于 `AUDIT.md` 的逐文件修复方案。按优先级分轮次。

---

## 第一轮: 使 Web UI 基本可用 (P0)

### C1. WebSocket 广播 dataclass 序列化修复

**根因:** `loop.py` 通过 `EventBus.emit()` 发送原生的 dataclass 对象到 WebSocket，而 `websocket.py:38` 的 `default=str` 把它们变成了不可解析的字符串。

**方案:** 修改 `loop.py`，在 emit 事件前将 dataclass 手动转为 dict。

**文件: `src/drawagent/orchestrator/loop.py`**

修改 4 处 emit:

```python
# Line 282 — IMAGES_READY: 将 ImageRecord list 转为 dict list
serializable_images = [
    {
        "filename": img.filename,
        "path": img.path,
        "iteration": img.iteration,
        "seed": img.seed,
        "width": img.width,
        "height": img.height,
        "prompt": img.prompt,
    }
    for img in images
]
await self.events.emit(DrawEvent.IMAGES_READY, images=serializable_images)

# Line 369 — INSPECTION_TASK_DONE: 将 InspectTaskResult 转为 dict
await self.events.emit(
    DrawEvent.INSPECTION_TASK_DONE,
    task=task.get("name"),
    result={
        "task_name": result.task_name,
        "task_description": result.task_description,
        "passed": result.passed,
        "observation": result.observation,
        "issues": result.issues,
    },
)

# Line 376 — INSPECTION_COMPLETE: 转 list[dict]
await self.events.emit(
    DrawEvent.INSPECTION_COMPLETE,
    results=[
        {
            "task_name": r.task_name,
            "passed": r.passed,
            "observation": r.observation,
            "issues": r.issues,
        }
        for r in inspection_results
    ],
)

# Line 388 — QUALITY_DECISION: 将 QualityDecision 转为 dict
await self.events.emit(
    DrawEvent.QUALITY_DECISION,
    decision={
        "passed": decision.passed,
        "confidence": decision.confidence,
        "reasoning": decision.reasoning,
        "remaining_issues": decision.remaining_issues,
        "recommendation": decision.recommendation,
    },
)
```

**替代方案 (更干净的):** 在 `loop.py` 加一个 `_dataclass_to_dict()` 辅助函数，对所有 emit 调用统一处理。或在 `EventBus` 中加一个整体序列化层。

**推荐:** 直接在 loop.py 4 处 emit 前加 dict 转换，最小化改动。

### C2. 前端 Agent B mcp_command 格式修复

**文件: `src/drawagent/ui/static/js/events.js:298`**

```javascript
// 改前:
mcp_command: mc.agentB.mcpCommand ? mc.agentB.mcpCommand.split(/\s+/) : null,

// 改后: 保持字符串
mcp_command: mc.agentB.mcpCommand || null,
```

### C3. Quick Params 和 Settings 默认值更新为 Z-Image 完整版

**文件: `src/drawagent/ui/static/js/app.js:19-22`**

```javascript
// 改前:
generationParams: {
    width: 1024, height: 1024,
    numImages: 2, steps: 8, guidance: 3.5, seed: -1,
},

// 改后:
generationParams: {
    width: 960, height: 1280,
    numImages: 2, steps: 30, guidance: 7.0, seed: -1,
},
```

**文件: `src/drawagent/ui/static/index.html:86-89`**

```html
<!-- 改后 -->
<input id="qpSteps" value="30">
<input id="qpGuidance" value="7.0">
```

**文件: `src/drawagent/ui/static/index.html:161,175,179`**

Slider 的 min/max 也需要调整以适应新范围:

```html
<!-- Steps slider: -->
<input type="range" id="stepsSlider" min="8" max="50" step="1" value="30">

<!-- Guidance slider: -->
<input type="range" id="guidanceSlider" min="1" max="10" step="0.5" value="7.0">
```

**文件: `src/drawagent/ui/static/js/events.js:248`**

```javascript
// resetSettings:
AppState.settings.generationParams = { width: 960, height: 1280, numImages: 2, steps: 30, guidance: 7.0, seed: -1 };
```

### C4. cfg_truncation 接入前端 UI

**文件: `src/drawagent/ui/static/index.html`**

在 Quick Params Bar 中添加（在 guidance 之后）:

```html
<div class="param-item">
    <label>CFG截断</label><input type="number" id="qpCfgTrunc" value="0.6" min="0" max="1" step="0.1">
</div>
```

在 Settings 面板的质量段添加:

```html
<div class="slider-group">
    <label class="slider-label" for="cfgTruncSlider"><span>CFG截断</span><span id="cfgTruncValue">0.6</span></label>
    <input type="range" class="slider" id="cfgTruncSlider" min="0" max="1" step="0.05" value="0.6">
</div>
```

**文件: `src/drawagent/ui/static/js/events.js:229-243`** — applySettings 中添加:

```javascript
p.cfgTruncation = parseFloat(document.getElementById('cfgTruncSlider').value);
```

**文件: `src/drawagent/ui/static/js/app.js:21`** — generationParams 初始值添加:

```javascript
generationParams: {
    ...
    cfgTruncation: 0.6,
},
```

**文件: index.html:504 (quick params sync)** — 添加:

```javascript
case 'qpCfgTrunc': p.cfgTruncation = parseFloat(el.value); break;
```

**文件: events.js:394 updateQuickParamsUI** — 添加:

```javascript
set('qpCfgTrunc', p.cfgTruncation);
```

**文件: events.js:358 updateSettingsUI** — 添加:

```javascript
set('cfgTruncSlider', p.cfgTruncation); txt('cfgTruncValue', p.cfgTruncation);
```

### H2. 修复错误卡片重试按钮

**文件: `src/drawagent/ui/static/js/renderer.js:62-80`**

修改 `addErrorCard` 增加可选 `retryPrompt` 参数:

```javascript
// 在 addErrorCard 的 innerHTML 中:
onclick="AppActions.retryMessage('${escapedMsg}')"

// 改为: 保存原始 prompt，让 retry 发送正确的消息
// addErrorCard(message, retryText = null)
// retryText 为 null 时重试原始请求
```

同时修改 events.js 中 ERROR 处理:

```javascript
case 'error':
    Renderer.removeLoading();
    Renderer.setLoading(false);
    Renderer.addErrorCard(event.message || _t('errorOccurred'), AppState._lastUserPrompt);
    break;
```

### H6 + H4: Settings panel 点击外部关闭 + 缺失 Agent B 字段

**文件: `src/drawagent/ui/static/index.html:148-217`**

```javascript
// 在 DOMContentLoaded 中添加:
els.settingsPanel.addEventListener('click', (e) => {
    if (e.target === els.settingsPanel) els.settingsPanel.classList.remove('active');
});
```

### 新增: GET /history 返回 inspections

**文件: `src/drawagent/api/schemas.py`**

`IterationSummary` 添加 inspections:

```python
class IterationSummary(BaseModel):
    number: int
    prompt: str
    images: list[ImageRef] = Field(default_factory=list)
    inspections: list[dict] = Field(default_factory=list)  # 新增
    passed: bool = False
    decision_reasoning: str = ""
```

**文件: `src/drawagent/api/routes.py:128-146`**

在 iterations 循环中添加:

```python
inspections = [
    {
        "task_name": insp.task_name,
        "task_description": insp.task_description,
        "passed": insp.passed,
        "observation": insp.observation,
        "issues": insp.issues,
    }
    for insp in it.inspections
]
iterations.append(IterationSummary(
    number=it.number,
    prompt=it.prompt,
    images=images,
    inspections=inspections,  # 新增
    passed=it.decision.passed if it.decision else False,
    decision_reasoning=it.decision.reasoning if it.decision else "",
))
```

---

## 第二轮: 改进用户体验 (P1)

### H3. Phase 4 inspection 进度展示

**文件: `src/drawagent/ui/static/js/events.js:38-42`**

```javascript
case 'inspection.task_done':
    if (event.task && event.result) {
        Renderer.addInspectionProgress(event.task, event.result.passed);
    }
    break;

case 'inspection.complete':
    Renderer.addSystemMessage(_t('allInspectionsDone'));
    break;
```

**文件: `src/drawagent/ui/static/js/renderer.js`** — 新增方法:

```javascript
addInspectionProgress(taskName, passed) {
    // 显示小标签: "检查 'content'... 通过 ✅"
    const indicator = document.createElement('div');
    indicator.className = `inspection-badge ${passed ? 'pass' : 'fail'}`;
    indicator.innerHTML = `<i class="fa-solid ${passed ? 'fa-circle-check' : 'fa-circle-xmark'}"></i> ${taskName}`;
    const container = document.getElementById('messagesContainer');
    container.appendChild(indicator);
    this._scrollToBottom();
    // 3 秒后自动消失
    setTimeout(() => { if (indicator.parentNode) indicator.remove(); }, 3000);
},
```

### H1. Viewer touch handler 修复

**文件: `index.html:563`**

```javascript
// 改前:
document.getElementById('viewerImage').addEventListener('touchend', () => { e => e.target.style.transform = ''; });

// 改后:
document.getElementById('viewerImage').addEventListener('touchend', (e) => { e.target.style.transform = ''; });
```

### M1. 系统设置 toast i18n

**文件: `src/drawagent/ui/static/js/i18n.js`**

添加 i18n 键:

```javascript
systemSettingsSaved: "System settings saved and applied",
systemSettingsSavedNote: "Settings saved",
systemSettingsSyncFailed: "Settings saved (server sync failed: ",
systemSettingsReset: "System settings reset",
```

**文件: `src/drawagent/ui/static/js/events.js:311,313,317,329`** — 使用 `_t()` 替换硬编码字符串。

### M3. Welcome screen suggestion chips i18n

**文件: `src/drawagent/ui/static/js/renderer.js:262`** — `renderWelcome()` 已经使用 `_t()`，OK。

但 `index.html:110-113` 的静态 HTML 版本需要保留初始值并确保 `renderWelcome()` 在首次加载时被调用。目前 `DOMContentLoaded` 中只调了 `Renderer.refreshI18n()`，没有 `renderWelcome()`。首屏会显示中文欢迎词。

**修复:** `DOMContentLoaded` 中在 `Renderer.refreshI18n()` 后加上条件判断: 如果当前语言是英文，调用 `renderWelcome()`。

### 前端的 ctrl+Enter 在移动端不友好

添加 `Shift+Enter` 换行支持:

```javascript
// 已经是默认行为 (textarea 的 Shift+Enter 会换行)
// 确认一下 textarea 没有被 preventDefault
```

### API PATCH vs PUT

目前使用 `PUT /api/config`，较好的 REST 实践应该是 `PATCH`（部分更新）。

---

## 第三轮: 完善与优化 (P2)

### 增加 Agent B 系统设置完整字段

**文件: `index.html:252-278`** — System Settings 中 Agent B 段添加:

```html
<div class="slider-group">
    <label class="slider-label" for="ssModelB"><span>模型</span></label>
    <input type="text" class="text-input" id="ssModelB" value="z-image">
</div>
<div class="slider-group" id="mcpToolNameB">
    <label class="slider-label" for="ssMcpToolName"><span>MCP 工具名</span></label>
    <input type="text" class="text-input" id="ssMcpToolName" value="generate_image">
</div>
<div class="slider-group" id="mcpUrlB">
    <label class="slider-label" for="ssMcpUrl"><span>MCP URL</span></label>
    <input type="text" class="text-input" id="ssMcpUrl" value="http://localhost:8000">
</div>
<div class="slider-group">
    <label class="slider-label" for="ssModelHints"><span>Model Hints</span></label>
    <textarea class="text-input" id="ssModelHints" rows="3" style="resize:vertical;"></textarea>
</div>
```

**文件: `events.js:267-280`** — applySystemSettings 中同步添加:

```javascript
mc.agentB.model = document.getElementById('ssModelB').value;
mc.agentB.mcpToolName = document.getElementById('ssMcpToolName').value;
mc.agentB.mcpUrl = document.getElementById('ssMcpUrl').value;
mc.agentB.modelHints = document.getElementById('ssModelHints').value;
```

### Page title 和 window 标题 i18n

**文件: `js/i18n.js`** — 添加:

```javascript
pageTitle: "DrawAgent — AI 图像生成",
pageTitleEn: "DrawAgent — AI Image Generation",
```

**文件: `js/events.js` 或 `renderer.js`** — 语言切换时跟随更新:

```javascript
document.title = I18n.getLang() === 'zh-CN' ? 'DrawAgent — AI 图像生成' : 'DrawAgent — AI Image Generation';
```

### Session 历史日期时间显示

**文件: `renderer.js:339`**

```javascript
// 改前:
${s.created_at ? new Date(s.created_at).toLocaleDateString() : ''}

// 改后:
${s.created_at ? new Date(s.created_at).toLocaleString() : ''}
```

### M2. Session 恢复后 list_ids 遗漏修复

**文件: `src/drawagent/orchestrator/session.py`**

在 `load_all()` 返回后，server 启动时需要确认加载的 session 被加入 `_sessions`。检查 `main.py:134-136`:

```python
restored = await session_manager.load_all()
if restored:
    print(f"Restored {len(restored)} session(s) from database")
```

没有把它们加入 `_sessions` dict。需要在 `load_all()` 内部或 `main.py` 中补充:

```python
for s in restored:
    session_manager._sessions[s.id] = s
```

### M5. API resp.json() 错误处理

**文件: `api.js:20-26`**

```javascript
// 改前:
const resp = await fetch(url, opts);
if (!resp.ok) { const err = await resp.text(); throw new Error(...); }
return resp.json();

// 改后: 加 try/catch
try {
    return await resp.json();
} catch (e) {
    throw new Error(`Invalid JSON response: ${await resp.text().slice(0, 200)}`);
}
```

---

## 文件修改优先级总表

| 优先级 | 文件 | 修改点数 | 参考 BUG 编号 |
|--------|------|---------|---------------|
| P0 | `src/drawagent/orchestrator/loop.py` | 4 | C1 |
| P0 | `src/drawagent/ui/static/js/events.js` | 2 | C2, C4 |
| P0 | `src/drawagent/ui/static/js/app.js` | 1 | C3, C4 |
| P0 | `src/drawagent/ui/static/index.html` | 5 | C3, C4, H4 |
| P0 | `src/drawagent/ui/static/js/renderer.js` | 1 | H2 |
| P0 | `src/drawagent/api/schemas.py` | 1 | Session历史 |
| P0 | `src/drawagent/api/routes.py` | 1 | Session历史 |
| P1 | `src/drawagent/ui/static/js/events.js` | 1 | H3 |
| P1 | `src/drawagent/ui/static/js/renderer.js` | 1 | H3 |
| P1 | `index.html` | 1 | H1 |
| P1 | `js/i18n.js` | 1 | M1 |
| P2 | `index.html` | 1 | Agent B 字段 |
| P2 | `js/events.js` | 1 | Agent B 字段 |
| P2 | `orchestrator/session.py` | 1 | M2 |

---

## 实现顺序

```
第一轮 P0 (需立即修复):
  → loop.py: C1 (4处)  ← 最关键，Unblock Web UI
  → events.js: C2 (1处)
  → app.js + index.html: C3 (3处)
  → index.html + events.js + app.js: C4 (6处)
  → renderer.js + events.js: H2 (2处)
  → schemas.py + routes.py: Session历史 (2处)
  → index.html: H4 (1处)

第二轮 P1 (体验改进):
  → events.js + renderer.js: H3 (检查进度)
  → index.html: H1 (viewer touch)
  → i18n.js + events.js: M1 (国际化)

第三轮 P2 (完善):
  → 剩余项
```
