# 前后端兼容性审查报告

> 审查日期: 2026-07-02
> 审查范围: 前端 (ui/static/*) vs 后端 (api/, orchestrator/, agents/, core/) 全链路
> 测试方法: 静态代码分析 + 数据流追踪

---

## 一、总览

审查发现 **4 个致命 BUG**（将导致运行时崩溃或功能不可用），**6 个高危问题**，**6 个中等问题**，**4 个低优先级问题**。

---

## 二、致命 BUG (RUNTIME FAILURE)

### C1. WebSocket 广播的 dataclass 对象序列化为字符串垃圾

**文件:** `src/drawagent/api/websocket.py:38`

`websocket.py` 的 `broadcast()` 使用 `json.dumps(..., default=str)`，当遇到不可序列化的 dataclass 对象时，fallback 为 `str(obj)`，把 dataclass 转成 `"ImageRecord(filename='...', path='...')"` 样式的字符串。

**影响的事件和数据（全部无法正常工作）：**

| 事件 | emit 数据 | 失败表现 |
|------|----------|---------|
| `images.ready` | `images=[ImageRecord, ...]` | 前端收到的 images 是字符串数组，无法取 `.filename` → 图片全不显示 |
| `inspection.task_done` | `result=InspectionTaskResult` | 前端收到字符串，无法读取检查结果 |
| `inspection.complete` | `results=[InspectionTaskResult, ...]` | 同上 |
| `quality.decision` | `decision=QualityDecision` | 前端 `event.decision.passed` 永远是 `undefined` → 状态栏从不更新 |

**根本原因:** `EventBus.emit(evt, **data)` 传递给 handler 的 `data` dict 中包含了原始 dataclass 对象，没有经过 dict/list 序列化。

**最大影响:** 前端永远不会收到任何迭代图片、检查进度、质量评估。Web UI 目前 **完全不可用**。

### C2. 前端 Agent B 配置推送 mcp_command 格式错误

**文件:** `src/drawagent/ui/static/js/events.js:298`

```javascript
// 前端: 把 "python D:\Z-Image-MCP\mcp_server.py" 拆成数组
mcp_command: mc.agentB.mcpCommand ? mc.agentB.mcpCommand.split(/\s+/) : null,
```

但后端 `AgentBConfig` (`config/schema.py:30`) 中 `mcp_command: str | None = None` 是字符串：

```python
# 后端期望: "python D:\\Z-Image-MCP\\mcp_server.py"
# 前端发送: ["python", "D:\\Z-Image-MCP\\mcp_server.py"]
```

这会导致 backend `update_config()` 中 `hasattr(section, key)` 检查通过但赋值了一个错误类型的值，后续 `subprocess.Popen(mcp_command)` 收到 list 而不是 str 会反直觉地工作（Popen 也接受 list），但带空格路径的 shell=True 模式下会有命令注入风险。**更严重的是**: cmd 被 `split(/\s+/)` 后路径中的空格会被错误切割。

### C3. Quick Params 快捷参数栏默认值为 Turbo 参数

**文件:** `src/drawagent/ui/static/index.html:78-92`

```html
<!-- 当前默认值 (Z-Image Turbo) -->
<input id="qpSteps" value="8">     <!-- 应为 30 -->
<input id="qpGuidance" value="3.5"> <!-- 应为 7.0 -->
```

同时 `app.js:20-21` 的 `generationParams` 初始值也是 Turbo 默认值，而系统 prompt 中的 `model_hints` 已推荐 steps=30、guidance=7.0。前端覆盖了代码逻辑但呈现给用户的默认值是错的。

**同样受影响的文件:**
- `index.html` 滑块: `#stepsSlider` (value=8), `#guidanceSlider` (value=3.5)
- `events.js:248` `resetSettings()` 也重置为 Turbo 参数

### C4. Prompt 快捷参数列缺少 cfg_truncation

`cfg_truncation` 是 Z-Image 完整版的关键参数（用户 params.json 中设为 0.6），但前端没有任何 UI 暴露此参数，Agent A 也无法通过前端覆盖它。当前只能通过 yaml 配置预设。

---

## 三、高危问题

### H1. 前端 View 的 `touchend` 事件 handler BUG

**文件:** `index.html:563`

```javascript
document.getElementById('viewerImage').addEventListener('touchend', () => { e => e.target.style.transform = ''; });
//                                                                          ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
//                                                                          这是一个永远不会执行的嵌套箭头函数！
```

应为:
```javascript
document.getElementById('viewerImage').addEventListener('touchend', (e) => { e.target.style.transform = ''; });
```

**影响:** pinch-zoom 释放后图片卡住不回弹。

### H2. 错误卡片"重试"按钮发送错误消息文本

**文件:** `renderer.js:70-76`

```javascript
// error card 的 innerHTML:
`onclick="AppActions.retryMessage('${escapedMsg}')"`
//                              ^^^^^^^^^^ 传的是错误消息文本
```

`retryMessage(text)` 中又把 `text` 传给 `API.sendMessage(text)`，导致后端把错误消息当成新的用户请求处理。应该保存原始 prompt 并传给它。

### H3. `inspection.task_done` 和 `inspection.complete` 事件在前端被忽略

**文件:** `events.js:38-42`

```javascript
case 'inspection.task_done':
    break;  // 什么都不做
case 'inspection.complete':
    break;  // 什么都不做
```

Phase 4 的 inspection 阶段（往往是 ~30 分钟的等待时间）前端完全没有任何进度展示。用户看不到检查进度，只能干等。

### H4. Settings Panel 关闭没有点击外部关闭的支持

**文件:** index.html 中 `#settingsPanel` 是个 slide-in 面板，但 event handler 没有监听背景蒙层点击。用户点击面板外区域无法关闭，必须点 × 按钮。

### H5. 前端缺少 Agent B 关键配置字段

`AgentBConfig` 拥有但前端 System Settings UI 缺失的字段：

| 后端字段 | 前端状态 | 影响 |
|---------|---------|------|
| `mcp_url` | 缺失 | MCP HTTP 模式无法配置 URL |
| `mcp_tool_name` | 缺失 | 无法自定义工具名 |
| `model` (Agent B) | 缺失 | 无法指定生成模型 |
| `model_hints` | 缺失 | 无法在前端编辑 prompt 提示 |
| `default_params` (所有子字段) | 缺失 | 无法配置生成默认参数 |
| `prompt_format` | 缺失 | 无法配置 prompt 语言格式 |

### H6. Session 历史展示只有日期没有时间

**文件:** `renderer.js:339`

```javascript
<div class="session-date">${s.created_at ? new Date(s.created_at).toLocaleDateString() : ''}</div>
```

同一个日期内创建的多个 session 无法区分。应改为 `.toLocaleString()`。

---

## 四、中等问题

### M1. 系统设置 toast 提醒硬编码中文

**文件:** `events.js:311,313,317,329`

在英文模式下的 4 处 toast 仍然输出中文：
- `'系统设置已保存并生效'`
- `'设置已保存'`
- `'设置已保存 (服务同步失败: ...)'`
- `'系统设置已重置'`

### M2. SessionManager.list_ids() 可能遗漏已恢复的 session

`list_ids()` 仅返回 `list(self._sessions.keys())`，但在 `load_all()` 流程中恢复的 session 是否加入 `_sessions` 存疑。`create_and_persist()` 和 `load_all()` 之间没有统一的路径将它们放入 `_sessions`。如果 load_all 恢复的 session 没有加入 `_sessions`，则他们不会出现在 list_sessions 的返回中。

### M3. 前端 Welcome 建议词 (suggestion chips) 始终为中文

**文件:** `index.html:110-113`

HTML 中硬编码的中文建议词（"一只猫坐在窗台上..."）不会被 i18n 切换。`refreshI18n → renderWelcome` 虽然重新生成了 welcome screen，但欢迎词依然来自 `index.html` 中硬编码的 HTML。

### M4. resetSettings() 重置到错误的默认值

`events.js:248` 重置 `generationParams` 为 `{steps: 8, guidance: 3.5}` 等 Turbo 值，与系统当前使用的模型不匹配。

### M5. API resp.json() 缺少解析失败处理

**文件:** `api.js:26`

```javascript
return resp.json();  // 若后端返回非 JSON 响应会 unhandled rejection
```

### M6. input 自动高度调整 race condition

**文件:** `index.html:438`

```javascript
els.promptInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); AppActions.sendMessage(); }
    setTimeout(() => { /* resize */ }, 0);  // sendMessage 已经清空 input，这里还在 resize
});
```

---

## 五、低优先级

### L1. `_system_prompt` 在 InnerLoop 初始化时构建一次，运行时 config 更新不生效
`loop.py:83` 在 `__init__` 中调用 `assembler._build_system_prompt(session)`，但 ServerRunner `update_config()` 只清空 provider cache，不清空 InnerLoop 的 system prompt（且 InnerLoop 已创建）。

### L2. Inspection phase agent_a.run_turn 不传系统 prompt
`loop.py:311-330` 的 Phase 4 inspection 传递了 `system_prompt=self._system_prompt`（已修复），但 Phase 5 evaluate 调用 `agent_a.evaluate_quality()` (line 383-387) 没有传 system_prompt。

### L3. 前端 page title 和 welcome title 硬编码中文
`index.html:6` 中 `<title>` 和 line 107 的 `<h1>` 是硬编码中文，不随语言切换。

### L4. Settings 面板的 systemConfig.serverUrl 未被前端读取
`app.js:17` 初始化 `serverUrl` 为 `http://127.0.0.1:8000`，但在 systemConfig 中没有此字段。如果用户通过其他网络访问服务，无法在前端配置。

---

## 六、数据流对比（前端期望 vs 后端实际发送）

### 1. `images.ready` 事件

| 字段 | 前端期望 | 后端实际 | 状态 |
|------|---------|---------|------|
| `event.images` | `[{filename, path, seed, width, height}, ...]` | `[ImageRecord dataclass, ...]` | **C1** |
| `event.iteration` | number | int | OK |

### 2. `quality.decision` 事件

| 字段 | 前端期望 | 后端实际 | 状态 |
|------|---------|---------|------|
| `event.decision.passed` | boolean | QualityDecision.passed | **C1** |
| `event.decision.confidence` | float | QualityDecision.confidence | **C1** |
| `event.decision.reasoning` | string | QualityDecision.reasoning | **C1** |
| `event.decision.recommendation` | string | QualityDecision.recommendation | **C1** |

### 3. `inspection.task_done` / `inspection.complete` 事件

| 字段 | 前端期望 | 后端实际 | 状态 |
|------|---------|---------|------|
| - | **前后端都是 no-op** | InspectTaskResult 被序列化失败 | **C1 + H3** |

### 4. `iteration.started` / `prompt.refined` / `loop.terminated`

这些事件使用简单类型（string, int），没问题。

### 5. API `/sessions/{id}/history` 响应

| 字段 | 前端期望 | 后端返回（routes.py:121-154） | 状态 |
|------|---------|-------------------------------|------|
| `history.messages` | `[{role, content}]` | `_message_ids.get(sid, [])` | OK |
| `history.iterations[].images` | `[{filename, path, seed, ...}]` | `ImageRef` (Pydantic) ✅ | OK |
| `history.iterations[].passed` | boolean | bool | OK |
| `history.iterations[].decision_reasoning` | string | string | OK |
| `history.iterations[].inspections` | **前端使用但 API 不返回** | routes.py **不包含 inspections** | **BUG** |

`selectSession()` (events.js:168) 调用 `history.iterations.forEach(it => ...)` 时使用了 `it.inspections`，但 `SessionHistoryResponse` 和 `routes.py` 的 `get_history()` 在 `IterationSummary` 中**没有** `inspections` 字段！前端永远收到 undefined → 历史记录中不显示检查项。

### 6. Session 恢复后 prompt 不匹配

`selectSession()` (events.js:167) 从 history 渲染时，决策卡使用 `it.prompt` 来显示：

```javascript
history.iterations.forEach(it => {
    Renderer.addIterationCard(it.number, it.images, it.inspections, {
        passed: it.passed,
        reasoning: it.decision_reasoning,
        prompt: it.prompt,  // ← 使用了 it.prompt（后端有）
    });
});
```

同时 `addIterationCard` 中渲染 inspections 用了：

```javascript
${inspections && inspections.length ? inspections.map(i => `... ${i.task_name || 'Inspection'} ...`) : ''}
```

但因为 `it.inspections` 在后端响应中不存在，history 重放时看不到检查结果。不过这是中等问题，因为图片和决策还能显示。

---

## 七、总结

| 分类 | 数量 | 核心影响 |
|------|------|---------|
| 致命 BUG | 4 | Web UI 完全不可用（图片不显示、状态不更新） |
| 高危问题 | 6 | 功能不完整、用户体验差 |
| 中等问题 | 6 | 边缘场景不工作 |
| 低优先级 | 4 | 语言/配置体验 |

**核心结论：Web UI 当前完全不可用。** C1 (dataclass 序列化) 全面阻塞了所有 WebSocket 关键事件，导致前端收不到图片列表、检查进度、质量评估。修复 C1 是最高优先级。
