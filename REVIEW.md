# DrawAgent v0.1 问题审查报告

> 基于对全部 38 个源文件的逐行审查，对比 DESIGN.md 与 DEVEL.md 的设计意图。

---

## 一、致命问题（当前版本不可用）

### 1. 服务器模式（Web UI）完全没有工作流引擎

**位置**: `src/drawagent/api/routes.py:80-100`, `src/drawagent/main.py:40-77`

`POST /api/sessions/{id}/message` 端点接收到用户消息后，**仅**将消息存入内存 dict，从不触发 `InnerLoop.run()`。服务器只创建了 `SessionManager`、`InterruptHandler`、`EventBus` 三个空壳，但从未创建：
- `AgentA`（LLM 推理引擎）
- `ProviderFactory`（模型连接）
- `ToolRegistry`（工具注册）
- `GenerateImageTool` / `InspectImageTool`
- `InnerLoop`（核心状态机）

**结果**：用户在 Web UI 发送消息 → 前端显示 loading spinner → 后端不做任何处理 → 永远卡住。Web UI 是一个精美的空壳。

### 2. 只有 CLI 模式能真正工作

`drawagent cli` 是唯一完整连接了所有组件的路径（`main.py:80-223`）。但它仅支持单次交互式的命令行输入输出，对普通用户完全没有可操作性。

### 3. Web UI 设置面板是"假的"

**位置**: `ui/static/js/events.js:190-213`, `ui/static/index.html:103-196`

设置面板允许修改 Provider、Model、API Key、Temperature 等，但这些设置**仅保存到 localStorage**，从不传递给后端。后端配置来自 YAML 文件，前后端配置完全脱节。用户在面板里改了模型，实际运行时用的还是 YAML 里的配置。

### 4. API Key 明文存储在 localStorage

**位置**: `ui/static/index.html:184`, `ui/static/js/app.js:29-31`

`modelApiKey` 字段以明文形式存入 `localStorage.setItem('drawagent_settings', ...)`。这是安全漏洞——任何能访问该浏览器的人都能读取 API Key。

---

## 二、严重影响可用性的问题

### 5. Memory 工具已实现但从未注册

**位置**: `src/drawagent/main.py:161-167`（CLI 模式的 ToolRegistry）, `src/drawagent/agents/prompts.py:15-16`

- `memory/tools.py` 中 `LoadMemoryTool`、`SearchMemoryTool`、`SaveMemoryTool` 完整实现
- `memory/` 目录下有 8 个精心编写的 Markdown 记忆文件（prompts + inspections）
- `prompts.py` 的 system prompt 里明确告诉 Agent A "你有 load_memory、search_memory、save_memory 三个工具"
- 但在 `main.py` 的 CLI 模式注册工具时**只注册了 generate_image、inspect_image、ask_user**，没有注册任何 memory 工具

**结果**：Agent A 被提示有记忆工具，但实际调用时会报 "Unknown tool"。整个记忆系统完全不可用。

### 6. 持久化层是死代码

**位置**: `src/drawagent/persistence/database.py`, `src/drawagent/orchestrator/session.py`

- `Database` 类有完整的 aiosqlite schema 和迁移逻辑
- `SessionManager` 只用内存 dict 存储 session
- 没有任何代码调用 `Database`

**结果**：服务器重启 → 所有会话、历史、生成记录全部丢失。

### 7. 上下文压缩（Compaction）完全未实现

**位置**: `src/drawagent/context/compaction.py`, `src/drawagent/config/schema.py:40`

- `CompactedHistory` 数据类已定义，`from_iterations()` 方法已实现
- `LoopConfig.compaction_threshold_tokens = 20000`
- 但 `InnerLoop.run()` 中**从不调用** `from_iterations()`，也不使用 `ContextAssembler` 的压缩功能

**结果**：随着迭代次数增加，上下文无限增长，很快就会超出 LLM token 限制导致 API 调用失败。

### 8. Web UI 缺少关键功能

**位置**: `ui/static/` 全部文件

UI 是一个完整的聊天界面框架（侧边栏、设置、图片查看器），但缺少：
- **无下载按钮**：生成的图片只能查看，不能下载到本地
- **无分享/导出功能**：无法导出 session 记录或图片
- **无批量操作**：无法一次下载所有迭代的图片
- **无历史恢复**：关闭浏览器后所有历史消失
- **离线字体不可用**：依赖 Google Fonts 和 Font Awesome CDN，离线环境会丢失样式

---

## 三、循环逻辑的功能缺陷

### 9. 每轮只检查第一张图

**位置**: `src/drawagent/orchestrator/loop.py:210`

```python
Call inspect_image with the first image and the task description.
```

即使每轮生成了 2-4 张图像，inspection 阶段**只检查第一张**。其余图片被静默忽略，浪费了生成成本和用户的等待时间。

### 10. 检查通过/失败的判断逻辑过于简陋

**位置**: `src/drawagent/orchestrator/loop.py:224`

```python
task_passed = "error" not in tr.output.lower() and "issue" not in tr.output.lower()
```

使用简单的子字符串匹配。任何包含 "tissue"、"issuer"、"terror" 等单词的正常输出都会误判为失败。

### 11. Rollback 中断是空操作

**位置**: `src/drawagent/orchestrator/loop.py:97-102`

```python
if action_result == "rollback":
    target = self._parse_rollback_target()
    iteration = target
    if self.images_history and target < len(self.images_history):
        # Could restore prompt from history
        pass   # <--- 什么都没做
    self.session_mgr.clear_interrupt(self.session)
```

设置了 `iteration` 计数但**没有恢复对应的 prompt**，也没有回退 `observations_history`。实际上等于一个无用的重启。

### 12. `ask_user` 推荐路径不会真正暂停

**位置**: `src/drawagent/orchestrator/loop.py:280-296`

```python
if decision.passed:
    if decision.recommendation == "ask_user":
        await self.events.emit(DrawEvent.A_QUESTION, ...)
        # 没有 return！代码继续往下走！
    else:
        return LoopResult(...)
```

当 Agent A 建议 "ask_user" 时，代码发出事件后**不会停止**，继续执行到 auto-accept 检查。用户永远收不到询问。

### 13. JSON 解析使用贪婪正则

**位置**: `src/drawagent/agents/agent_a.py:222-244`

```python
match = re.search(r"\[.*\]", text, re.DOTALL)  # 贪婪匹配
match = re.search(r"\{.*\}", text, re.DOTALL)  # 贪婪匹配
```

当 LLM 返回嵌套 JSON 或多个 JSON 块时，`.*` 会贪婪捕获到最后一个 `]`/`}`，导致解析出错误的数据结构。

### 14. 生成阶段没有错误恢复

**位置**: `src/drawagent/orchestrator/loop.py:163-176`

如果 LLM 在 generation phase 抛出异常（网络超时、API 限流、token 耗尽），`InnerLoop.run()` 直接崩溃。`main.py:220` 的 `except Exception` 只能捕获然后打印错误，无法重试或恢复。

---

## 四、代码质量问题

### 15. CLI 模式每次都创建新对象

**位置**: `src/drawagent/main.py:200-210`

```python
agent_a2 = AgentA(provider=provider_a, tool_registry=registry, session=session)
loop = InnerLoop(session=session, agent_a=agent_a2, ...)
```

每次用户输入一条消息，都重新创建 `AgentA` 和 `InnerLoop` 实例。`provider_a` 和 `tool_registry` 本应复用。

### 16. HTTP 客户端从不关闭

**位置**: `src/drawagent/tools/generate_image.py:202`, `src/drawagent/providers/openai_compat.py`

- `GenerateImageTool` 有 `close()` 方法但从未被调用
- `OpenAICompatibleProvider` 使用 `httpx.AsyncClient` 但无 `close()` 方法
- 程序退出时 httpx 连接泄漏

### 17. 同步 `input()` 在异步上下文中阻塞事件循环

**位置**: `src/drawagent/tools/human_input.py:49-76`

`AskUserTool.prompt()` 使用同步的 `input()`，在 `async execute()` 中被调用。虽然 CLI 模式下没有其他并发任务所以"能工作"，但这是不良实践。

### 18. 两个同名 `ImageRecord` 类

**位置**: `src/drawagent/core/types.py:19` vs `src/drawagent/persistence/models.py:60`

两个模块都定义了 `ImageRecord` 类，字段不同。容易引入混淆和导入错误。

### 19. `pyproject.toml` 构建配置不匹配

**位置**: `pyproject.toml:36-44`

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.setuptools]    # <--- hatchling 不使用 setuptools 配置
packages = ["drawagent"]
```

`hatchling` 构建后端不使用 `[tool.setuptools]`。应使用 `[tool.hatch.build.targets.wheel]`。

### 20. FastAPI 使用已弃用的 `on_event`

**位置**: `src/drawagent/api/app.py:36`

```python
@app.on_event("startup")
```

在较新版本的 FastAPI 中已弃用，应改用 `lifespan` 上下文管理器。

---

## 五、用户体验问题汇总

| # | 问题 | 影响 |
|---|------|------|
| A1 | Web UI 发送消息后无任何反馈（后端不处理） | 用户困惑，以为卡死 |
| A2 | 无生成进度指示（无 step count、无 ETA） | 用户不知道要等多久 |
| A3 | 无图片下载功能 | 用户无法保存生成的图片 |
| A4 | 无法对比不同轮次的图片 | 无法判断迭代是否有改善 |
| A5 | 无法查看 prompt 演变历史 | 用户不懂 Agent 做了什么修改 |
| A6 | 设置面板修改后不生效 | 用户困惑，失去信任 |
| A7 | API Key 明文存储 | 安全风险 |
| A8 | 无错误提示和恢复机制 | 出错后只能刷新页面 |
| A9 | 依赖 CDN 字体和图标 | 离线/内网环境不可用 |
| A10 | 无法取消正在进行的生成（中断按钮不工作） | 因为没有后端 loop，中断按钮无意义 |

---

## 六、总结

当前版本 v0.1 实际上是一个**不完整的原型**：

- **CLI 模式**是唯一可运行的路径，但仅适合开发者调试
- **Web UI 有完整的前端界面，但后端是空壳**——这是最致命的问题
- **Memory、持久化、上下文压缩**三大子系统已编码但从未接入运行时
- **循环逻辑**有多处功能缺陷（单图审查、贪婪解析、ask_user 不暂停等）
- **代码质量**方面有资源泄漏、重复定义、构建配置错误等问题

**建议优先级**：
1. **P0**：实现服务器模式的工作流引擎（连接 InnerLoop 到 HTTP 请求处理器）
2. **P0**：修复 ask_user 暂停逻辑、JSON 解析、多图审查
3. **P1**：注册 memory 工具、接入持久化层
4. **P1**：添加图片下载、错误恢复、进度反馈
5. **P2**：修复构建配置、资源泄漏、API Key 安全问题

---

## 七、用户反馈与补充分析

### 7.1 图像生成模型接入口分析

**当前接入方式**：`src/drawagent/tools/generate_image.py:160`

```python
api_url = f"{self.config.api_base.rstrip('/')}{self.config.endpoint}"
resp = await self._client.post(api_url, json=body)
```

当前是一个**硬编码的 HTTP POST 协议**。生成参数和模型信息全都写在 `AgentBConfig` 中（YAML 配置文件），`GenerateImageTool` 启动时读取配置，之后无法动态切换。每次调用都向固定的 `api_base + endpoint` 发 JSON POST。

**关于 MCP 支持**：
- DESIGN.md §12.3 将 MCP 列为 **Phase 3** 的远期计划，目前代码中 **零 MCP 实现**
- 没有 MCP client、没有 MCP server discovery、没有 `mcp_servers` 配置项的实际代码
- `config/schema.py` 和 `.drawagent.default.yaml` 中均无 MCP 相关字段
- 需要在 `ToolRegistry` 层面增加 MCP 工具发现机制，或在 `providers/` 下增加 `MCPProvider`

**建议**：将 `AgentBConfig` 扩展为支持两种后端模式：
```yaml
agent_b:
  type: mcp                    # "http" | "mcp"
  # HTTP 模式（当前）
  http:
    api_base: http://localhost:8000
    endpoint: /api/generate
  # MCP 模式（新增）
  mcp:
    command: ["python", "-m", "zimage_mcp"]
    # 或远程
    # url: https://mcp.example.com
```
这样同一个 tool interface 可以对接任意生图后端。

### 7.2 设置面板结构重组建议

当前 Web UI 设置面板将所有参数混在一个抽屉里：

```
[设置面板]  ← 一个面板包含所有
  ├── 图像 (宽/高/张数)
  ├── 质量 (步数/引导力/种子)
  ├── 智能体 (最大轮数/自动接受/显示中间)
  └── 模型配置 (Provider/Model/API Base/API Key/Temperature)
```

**问题**：模型配置属于"系统级/一次设置"，而图像参数属于"每次生成可能调整"。混在一起导致：
- 用户每次调参数都要滚动跳过模型配置
- 模型配置容易误触
- API Key 暴露在显眼位置

**建议重组为两个独立入口**：

| 入口 | 位置 | 内容 | 变更频率 |
|------|------|------|---------|
| **系统设置** | 侧边栏底部齿轮图标 → 独立页面/模态框 | Agent A (主 LLM)、Agent B (生图模型/MCP)、Agent C (VLM 视觉模型)、Memory 路径、API Keys | 极低（首次配置后基本不动） |
| **生图参数** | 聊天输入框上方 / 快捷面板 | 宽、高、张数、步数、引导力、种子、最大迭代轮数 | 高频（每次生成前可能调整） |

页面结构建议：
```
┌─ 侧边栏 ───────────────────────────────────────┐
│ 🏠 DrawAgent                                    │
│ ─────────────────────────────────────────────── │
│ 📁 会话列表                                     │
│   ├ 会话1                                       │
│   └ 会话2                                       │
│ ─────────────────────────────────────────────── │
│ [+ 新建会话]                                     │
│ [⚙ 系统设置]   ← 入口改为独立页面               │
└────────────────────────────────────────────────┘

┌─ 聊天区 ───────────────────────────────────────┐
│ ...                                             │
│ ┌─ 快捷参数栏（可折叠）───────────────────────┐ │
│ │ 宽: [1024] 高: [1024] 张数: [2]             │ │
│ │ 步数: [8] 引导: [3.5] 种子: [-1] 轮数: [7] │ │
│ │ [展开更多 ▾]                                 │ │
│ └──────────────────────────────────────────────┘ │
│ [输入框]                              [发送]     │
│ [接受] [修改方向] [暂停]                         │
└─────────────────────────────────────────────────┘
```

### 7.3 建议新增的 UX 功能

以下功能会显著提升用户使用体验：

#### A. 迭代版本浏览器
- 并排对比不同迭代轮次的生成结果
- 显示每轮的 prompt、inspection 结果、质量评分
- 支持"回到此版本"（恢复该轮的 prompt 继续优化）
- 参考 DESIGN.md §13-问题5 提到的需求

#### B. 实时生成预览
- 显示生成进度（如 stable diffusion 的 step 进度条）
- 渐进式图片渲染（如果有中间 decode）
- ETA 倒计时估算

#### C. 图片操作
- **下载按钮**：每张图片右下角下载图标（当前缺失）
- **复制到剪贴板**
- **收藏/标记最佳**：标记某张图为"最佳"，作为最终交付
- **图片元数据叠加**：hover 显示 seed、prompt、参数

#### D. Prompt 追溯
- 点击迭代卡片展开 → 显示该轮使用的完整 prompt
- Prompt diff 视图：高亮显示每轮 prompt 的修改（增/删/改）
- 最终 prompt 可一键复制

#### E. 会话管理增强
- 会话重命名（当前只有 "新会话"）
- 会话导出（导出为 ZIP：图片 + prompt + inspection 记录）
- 会话搜索/过滤

#### F. 快捷键
| 快捷键 | 功能 |
|--------|------|
| `Ctrl+Enter` | 发送消息（已实现） |
| `Esc` | 关闭图片查看器 / 取消生成 |
| `←` `→` | 图片查看器导航（已实现） |
| `Ctrl+S` | 下载当前查看的图片 |
| `Ctrl+Shift+N` | 新建会话 |

#### G. 通知与状态
- 生成完成时浏览器 Notification API 桌面通知
- 声音提示（可关闭）
- 状态栏显示当前阶段（规划中 / 生成中 / 审查中 / 评估中）

#### H. 错误处理 UX
- 友好的错误卡片（而非空白/卡死）
- "重试"按钮（而非只能刷新页面）
- API Key 未配置时的引导提示
- 网络断开时自动重连 WebSocket

#### I. 移动端适配增强
- 当前 CSS 有基础 responsive 设计，但设置面板在手机上占满全屏不可操作
- 建议移动端用 bottom sheet 代替侧边抽屉
- 图片查看器在移动端支持手势缩放

#### J. 生图前的需求澄清
- Agent A 理解用户需求后，先展示"我理解为：xxx，将生成 x 张图，预计 x 秒"
- 用户可以确认或修正理解
- 避免 LLM 误解需求后浪费生成配额

---

## 八、详细修复计划

### 🔴 Phase 1 — 让系统能跑起来（3-4 天）

> 目标：Web UI 能完成一次完整的"发送需求 → 生成图片 → 审查 → 返回结果"流程。

#### 1.1 实现服务器模式的工作流引擎

**文件**：`src/drawagent/main.py:40-77`, `src/drawagent/api/routes.py:80-100`, 新建 `src/drawagent/orchestrator/server_runner.py`

**方案**：在 `POST /sessions/{id}/message` 中启动后台异步任务运行 InnerLoop。

```python
# routes.py — send_message 末尾追加
import asyncio
from drawagent.orchestrator.server_runner import ServerRunner

runner = ServerRunner(provider_factory, tool_registry, ...)
asyncio.create_task(runner.run_for_message(session, req.text))
```

**具体步骤**：
1. 在 `run_server()` 中初始化 `ProviderFactory`、`ToolRegistry`（含 memory tools）、`AgentA`、`ContextAssembler`
2. 新建 `server_runner.py`，封装 `InnerLoop` 启动 + 事件→WebSocket 广播
3. `send_message` 端点调用 `server_runner.enqueue(session_id, text)`
4. 每轮事件（迭代开始、图片就绪、审查完成、质量判断）通过已有 `EventBus → WebSocket` 桥推到前端

**验证**：浏览器发送消息 → 后端调用 LLM → 生成图片 → 前端收到 `images.ready` 事件 → 图片显示在聊天区。

#### 1.2 修复循环核心缺陷

| 修复项 | 文件 | 行号 | 方案 |
|--------|------|------|------|
| ask_user 不暂停 | `loop.py` | 280-296 | `if decision.recommendation == "ask_user":` 分支末尾加 `return LoopResult(...)`，等待用户通过 interrupt API 明确接受或拒绝 |
| JSON 贪婪解析 | `agent_a.py` | 222-244 | 改用 `json.loads(text[match.start():match.end()])` 前先找到第一个完整 JSON（用括号计数而非正则），或用 `json.loads` 套 `try/except` 逐位置尝试 |
| 多图审查 | `loop.py` | 201-215 | 将 `inspect_image with the first image` 改为 `for each image`，对每张图独立调用 `inspect_image`，汇总结果 |
| 审查判定逻辑 | `loop.py` | 224 | 改用 Agent A 解析审查工具的文本输出来判断 pass/fail，而非简单子串匹配。或让 inspect_turn 的 text 输出本身就包含结构化判断 |
| Rollback 空操作 | `loop.py` | 97-102 | 实现 `_restore_iteration(target)`: 从 `session.iterations[target]` 恢复 `current_prompt` 和 `observations_history[:target]` |
| auto_accept 配置 | `loop.py` | 298-312 | 将 `self.config.auto_accept_threshold <= 10.0` 改为 `decision.confidence >= self.config.auto_accept_threshold / 10.0` |
| 生成阶段异常处理 | `loop.py` | 163-176 | 外层 `try/except`，捕获 `ProviderError`/`httpx.HTTPError`，记录错误到 events，自动 fallback 简化 prompt 重试一次 |

#### 1.3 注册 Memory 工具

**文件**：`src/drawagent/main.py:161-167`

```python
from drawagent.memory.tools import LoadMemoryTool, SearchMemoryTool, SaveMemoryTool
from drawagent.memory.store import MemoryStore
from drawagent.memory.index import MemoryIndex

store = MemoryStore(Path(config.memory.base_dir).expanduser())
index = MemoryIndex(store)
registry.register(LoadMemoryTool(store))
registry.register(SearchMemoryTool(store))
registry.register(SaveMemoryTool(store, index))
```

**同步修改**：服务器模式 `run_server()` 中同样注册这三个工具。

---

### 🟡 Phase 2 — 让系统稳定可靠（2-3 天）

> 目标：数据不丢失、长会话不崩溃、设置面板可用。

#### 2.1 接入持久化层

**文件**：`src/drawagent/orchestrator/session.py`, `src/drawagent/persistence/database.py`

1. `SessionManager` 构造函数接受 `Database` 实例
2. `create()` 写入 `sessions` 表
3. `add_iteration()` 写入 `iterations` 和 `images` 表
4. `get()` 从 DB 加载会话及其所有迭代和图片记录
5. 服务器启动时从 DB 恢复所有活跃会话

#### 2.2 实现上下文压缩触发

**文件**：`src/drawagent/orchestrator/loop.py`, `src/drawagent/context/compaction.py`

1. 在 `run()` 的每次迭代开始前，用 `ContextAssembler.estimate_tokens()` 估算当前上下文长度
2. 当超过 `config.compaction_threshold_tokens` 时，调用 `CompactedHistory.from_iterations(session.iterations[:-2])` 生成压缩摘要
3. 将压缩后的摘要注入 `ContextAssembler`，替换掉旧迭代的完整上下文

#### 2.3 拆分设置面板

**文件**：`ui/static/index.html`, `ui/static/css/style.css`, `ui/static/js/events.js`

**前端改动**：
1. 创建独立的 `系统设置` 页面（路由 `/settings` 或模态框），包含：
   - Agent A: Provider / Model / API Base / API Key / Temperature
   - Agent B: 接入类型 (HTTP/MCP) / API Base / Endpoint (或 MCP 命令/URL)
   - Agent C: Provider / Model / API Base / API Key / Temperature
   - Memory: 基础路径
2. 在原设置面板中删除"模型配置"区域，只保留图像参数和质量参数
3. 将快捷参数栏从下拉抽屉改为输入框上方的可折叠横条

**后端改动**：
1. 新增 `PUT /api/config` 端点，允许前端更新运行时配置
2. `GET /api/config` 增加 Agent B 和 Agent C 的完整信息

#### 2.4 MCP 接入支持

**文件**：新建 `src/drawagent/providers/mcp_provider.py`, 修改 `src/drawagent/config/schema.py`

1. `config/schema.py` — 扩展 `AgentBConfig`:
```python
class AgentBConfig(BaseModel):
    type: Literal["http", "mcp"] = "http"
    # HTTP 模式
    api_base: str = "http://localhost:8000"
    endpoint: str = "/api/generate"
    # MCP 模式
    mcp_command: list[str] | None = None   # 本地 MCP server
    mcp_url: str | None = None             # 远程 MCP server
    mcp_tool_name: str = "generate_image"  # MCP 工具名
```

2. `providers/mcp_provider.py` — 实现 MCP client:
   - 支持 stdio 本地 MCP server（`subprocess` + JSON-RPC）
   - 支持 HTTP 远程 MCP server
   - 启动时 `initialize` → `list_tools` → 找到生图工具
   - 调用时 `call_tool(name, args)` → 返回图片数据

3. `tools/generate_image.py` — `GenerateImageTool` 内部根据配置走 HTTP 或 MCP 分支

---

### 🟢 Phase 3 — 让系统好用（3-4 天）

> 目标：普通用户能舒适地完成日常画图任务。

#### 3.1 图片操作

| 功能 | 实现位置 | 方案 |
|------|---------|------|
| 下载按钮 | `renderer.js` — `addIterationCard()` 中每张图片添加下载图标 | `<a download href="...">` 或 `fetch` + `URL.createObjectURL` |
| 复制到剪贴板 | `viewer.js` | `navigator.clipboard.write([new ClipboardItem(...)])` |
| 收藏标记 | `app.js` — `AppState` 新增 `favorites: Set` | 星标图标，localStorage 持久化 |
| Metadata hover | `renderer.js` — 图片上叠加 tooltip | CSS `::after` + `data-*` 属性显示 seed/prompt/参数 |

#### 3.2 迭代版本浏览器

**文件**：新建 `ui/static/js/compare.js`, 修改 `renderer.js`

1. 在迭代卡片头部添加"对比"按钮
2. 点击后弹出对比视图：左右/上下并排显示不同迭代的图片
3. 底部显示对应的 prompt 和 inspection 摘要
4. "回退到此版本"按钮 → 调用 `POST /api/sessions/{id}/interrupt {action: "rollback", data: {target: N}}`

#### 3.3 Prompt 追溯与 Diff

**文件**：`renderer.js`

1. 迭代卡片展开后显示完整 prompt（目前只有图片和审查结果）
2. 第 2+ 轮卡片附 `[查看 Prompt 变更]` 链接，点击展开 diff 视图
3. 前端做简单的行级 diff（新增=绿色、删除=红色、修改=黄色）
4. 最终 prompt 旁加复制按钮

#### 3.4 错误处理 UX

**文件**：`events.js`, `renderer.js`

1. `EventRouter.dispatch('error')` 时移除 loading，显示红色错误卡片
2. 错误卡片包含：错误描述 + "重试"按钮 + "新建会话"按钮
3. WebSocket `onclose` 时自动重连（指数退避，最多 5 次）
4. API Key 未配置时在聊天区显示引导卡片（而非静默失败）

#### 3.5 桌面通知与状态栏

**文件**：`events.js`, `index.html`

1. `loop.terminated` 事件触发时，若页面不可见则发 `new Notification('DrawAgent', {body: '生成完成'})`
2. 状态栏 `#chatStatus` 文案细化为：`规划中` → `生成中 (1/2)` → `审查中` → `评估中` → `完成`（通过监听 WebSocket 事件切换）

#### 3.6 会话导出

**文件**：`routes.py` — 新增 `GET /api/sessions/{id}/export`

1. 后端生成 ZIP：`{session_id}/` 下包含 `images/`、`iterations.json`、`messages.json`
2. `iterations.json` 包含每轮的 prompt、参数、inspection 结果、质量决策
3. 前端添加导出按钮 → 触发下载

#### 3.7 生图前需求澄清

**文件**：`loop.py` — Phase 0（新增）, `index.html` — 确认卡片 UI

1. 在 PLANNING 之前新增 `CLARIFYING` 阶段
2. Agent A 输出："我理解为：你想生成 [摘要]。将使用 [模型]，预计 [N] 轮迭代。确认开始？"
3. 前端渲染确认卡片，用户点"确认"或"修改需求"
4. 用户也可在输入框中追加补充说明

---

### 🔵 Phase 4 — 打磨与安全（2-3 天）

> 目标：生产就绪，无技术债务。

#### 4.1 安全性

| 修复项 | 文件 | 方案 |
|--------|------|------|
| API Key 明文存储 | `app.js`, `index.html` | 系统设置中的 API Key 改用 sessionStorage（关闭浏览器自动清除），或完全不存储让用户每次输入 |
| 输入校验 | `routes.py` | `SendMessageRequest.text` 加 `max_length=4000`，`InterruptRequest.action` 用 `Literal` 枚举限制 |
| 路径遍历防护 | 已实现 | `memory/store.py:_safe_path()` 已有正则校验，保持 |

#### 4.2 资源管理

| 修复项 | 文件 | 方案 |
|--------|------|------|
| httpx 客户端泄漏 | `generate_image.py`, `openai_compat.py` | 各自实现 `async def __aenter__/__aexit__`，在 `main.py` 用 `async with` 管理生命周期 |
| blocking `input()` | `human_input.py` | CLI 模式下直接调用 `sys.stdin.readline()` 的异步版本（或用 `asyncio.get_event_loop().run_in_executor`） |

#### 4.3 代码清理

| 修复项 | 文件 | 方案 |
|--------|------|------|
| 重复 `ImageRecord` | `core/types.py` + `persistence/models.py` | 统一使用 `core/types.py` 的定义，`persistence/models.py` 改为引用 |
| `pyproject.toml` 构建 | `pyproject.toml` | 将 `[tool.setuptools]` 改为 `[tool.hatch.build.targets.wheel]` 配置，或切换 build-backend 为 `setuptools` |
| FastAPI `on_event` | `app.py:36` | 改用 `@asynccontextmanager async def lifespan(app)` |
| CLI 复用对象 | `main.py:200-201` | 将 `AgentA` 和 `InnerLoop` 移到 `while` 循环外部，每次只更新 `session.user_request` |

#### 4.4 字体离线化

**文件**：`index.html`, `style.css`, 新建 `ui/static/fonts/`

1. 下载 Inter + Noto Sans SC 的 woff2 子集到 `static/fonts/`
2. 添加 `@font-face` 声明
3. Font Awesome 替换为内联 SVG 图标或下载需要的几个图标文件

#### 4.5 测试与文档

1. 补充 `test_loop.py`（Phase 1 后必须）
2. 补充 `test_server_runner.py`（Phase 1 后必须）
3. `README.md` 补充实际的启动步骤、MCP 配置示例
4. `.drawagent.default.yaml` 补充 MCP 配置注释

---

### 📊 工作量估算

| Phase | 内容 | 预计时间 | 累计 |
|-------|------|---------|------|
| 🔴 P1 | 服务器工作流 + 循环修复 + Memory 注册 | 3-4 天 | 3-4 天 |
| 🟡 P2 | 持久化 + 压缩 + 设置面板 + MCP | 2-3 天 | 5-7 天 |
| 🟢 P3 | 图片操作 + 版本浏览 + Prompt追溯 + 错误UX + 通知 + 导出 + 需求澄清 | 3-4 天 | 8-11 天 |
| 🔵 P4 | 安全 + 资源管理 + 代码清理 + 离线化 + 测试 | 2-3 天 | 10-14 天 |

**总计：约 2-3 周达到可发布状态。**

---

## 九、逐项验证报告

> 语法检查：38 个 Python 源文件全部通过 `ast.parse` 无 SyntaxError。以下为逐项功能/代码验证。

### 🔴 P1 验证

#### P1.1 服务器工作流引擎 ✅

| 检查项 | 文件 | 状态 |
|--------|------|------|
| `ServerRunner` 类创建 | `orchestrator/server_runner.py` (新建) | ✅ |
| `server_runner.py` — `run_for_message()` 启动后台 InnerLoop | 第 52-66 行 | ✅ |
| `server_runner.py` — `_execute_loop()` 创建 AgentA + InnerLoop 并运行 | 第 68-113 行 | ✅ |
| `server_runner.py` — cancel 和任务去重 | 第 56-60、115-121 行 | ✅ |
| `main.py:run_server()` — 初始化 ProviderFactory、ToolRegistry（含 memory）、AgentA | 第 60-102 行 | ✅ |
| `main.py:run_server()` — 创建 ServerRunner 并传入 init_routes | 第 93-105 行 | ✅ |
| `routes.py:send_message` — 通过 `_runner.run_for_message()` 触发生成 | 第 96-98 行 | ✅ |
| EventBus→WebSocket 桥事件类型已补充 | 第 113-119 行（含 user.steer, user.rollback, agent.question） | ✅ |

#### P1.2 循环七项缺陷修复验证

| # | 修复项 | 文件:行号 | 方案 | 验证 |
|---|--------|----------|------|------|
| 1 | ask_user 不暂停 | `loop.py:349-359` | `decision.recommendation == "ask_user"` 后立即 `return LoopResult` | ✅ |
| 2 | JSON 贪婪解析 | `agent_a.py:243-274` | `_find_json_block()` 用括号计数替代 `re.search(r"\[.*\]")` | ✅ |
| 3 | 多图审查 | `loop.py:249-297` | `for img_idx, image in enumerate(images)` 内层循环遍历所有图片 | ✅ |
| 4 | 审查判定逻辑 | `loop.py:278-292` | 优先 VERDICT 匹配 + 兜底关键词列表 `["error:", "issue:", "incorrect", ...]` | ✅ |
| 5 | Rollback 空操作 | `loop.py:109-122` | 恢复 `current_prompt`、`observations_history`、`images_history`、`iteration` | ✅ |
| 6 | auto_accept 配置 | `loop.py:373` | `self.config.auto_accept_threshold / 10.0` 替代 `<= 10.0` | ✅ |
| 7 | 生成阶段异常处理 | `loop.py:205-217` | `try/except` 捕获异常，iteration 1 自动重试简化 prompt | ✅ |

#### P1.3 Memory 工具注册 ✅

| 检查项 | 位置 | 状态 |
|--------|------|------|
| CLI 模式注册 LoadMemoryTool | `main.py:225` | ✅ |
| CLI 模式注册 SearchMemoryTool | `main.py:226` | ✅ |
| CLI 模式注册 SaveMemoryTool | `main.py:227` | ✅ |
| Server 模式注册 LoadMemoryTool | `main.py:89` | ✅ |
| Server 模式注册 SearchMemoryTool | `main.py:90` | ✅ |
| Server 模式注册 SaveMemoryTool | `main.py:91` | ✅ |
| Prompt 中提及的工具与 Registry 一致 | `prompts.py:15-16` ↔ `main.py:89-91` | ✅ |

---

### 🟡 P2 验证

#### P2.1 SQLite 持久化 ✅

| 检查项 | 文件:行号 | 状态 |
|--------|----------|------|
| `Database` 初始化 + schema 迁移 | `database.py:80-93` | ✅ |
| `SessionManager(db=db)` | `session.py:22-24` | ✅ |
| `create_and_persist()` 写入 sessions 表 | `session.py:37-47` | ✅ |
| `add_iteration()` 写入 iterations/images/inspections 表 | `session.py:81-122` | ✅ |
| `load_all()` 从 DB 恢复所有 session | `session.py:124-197` | ✅ |
| `delete()` 同步删除 DB 记录 | `session.py:69-73` | ✅ |
| Server 启动时 DB 恢复 | `main.py:63-70` | ✅ |

#### P2.2 上下文压缩 ✅ (修复后)

| 检查项 | 文件:行号 | 状态 |
|--------|----------|------|
| 压缩触发条件检查 | `loop.py:87-89` | ✅ |
| `CompactedHistory.from_iterations()` | `loop.py:91-93` | ✅ |
| 注入 AgentA 的 `_compacted` 字段 | `loop.py:95`（新增） | ✅ |
| `_inject_compacted()` 注入到所有 LLM 消息 | `agent_a.py:58-64` | ✅ |
| `_estimate_context_tokens()` 估算逻辑 | `loop.py:416-428` | ✅ |
| 压缩结果实际生效 | `agent_a.py:67,173,180,214,237`（所有方法调用 `_inject_compacted`） | ✅ |

#### P2.3 设置面板拆分 ⚠️ 仅后端就绪

| 检查项 | 状态 |
|--------|------|
| `config/schema.py` 支持完整模型配置（A/B/C） | ✅ |
| `routes.py:GET /config` 返回模型配置 | ✅ |
| `routes.py:POST /sessions` 支持 `CreateSessionRequest` | ✅ |
| **前端拆分系统设置/生图参数** | ❌ 未实现（需 UI 改动） |

#### P2.4 MCP 接入 ✅

| 检查项 | 文件:行号 | 状态 |
|--------|----------|------|
| `AgentBConfig` 新增 `type: Literal["http", "mcp"]` | `schema.py:25` | ✅ |
| `AgentBConfig` 新增 `mcp_command`, `mcp_url`, `mcp_tool_name` | `schema.py:32-34` | ✅ |
| `MCPProvider` — stdio 模式 | `mcp_provider.py:41-86` | ✅ |
| `MCPProvider` — HTTP 模式 | `mcp_provider.py:88-118` | ✅ |
| `MCPProvider` — JSON-RPC 2.0 协议 | `mcp_provider.py:120-142` | ✅ |
| `GenerateImageTool` 根据 config.type 分派 | `generate_image.py:81-83, 170-172` | ✅ |
| `_generate_mcp` MCP 图片解析（MCP content format） | `generate_image.py:174-213` | ✅ |

---

### 🟢 P3 验证

#### P3.1~P3.5 前端 UX 功能 ⚠️ 后端就绪，前端待实现

| 功能 | 后端状态 | 前端状态 |
|------|---------|---------|
| 图片下载 | ✅ `GET /api/images/...` | ❌ UI 缺下载按钮 |
| 迭代版本浏览 | ✅ `GET /api/sessions/{id}/history` | ❌ 缺对比视图 |
| Prompt 追溯 | ✅ 迭代数据含 prompt | ❌ 缺 diff 展示 |
| 错误处理 UX | ✅ `ERROR` 事件已通过 WebSocket 推送 | ❌ 前端仅 Toast |
| 桌面通知 | ✅ `loop.terminated` 事件 | ❌ 未实现 Notification API |
| 会话导出 | ✅ `GET /api/sessions/{id}/export`（`routes.py:203-276`） | ❌ 缺导出按钮 |

#### P3.7 需求澄清 ⚠️ 部分实现

| 检查项 | 文件:行号 | 状态 |
|--------|----------|------|
| AgentA `clarify_request()` 方法 | `agent_a.py:139-161` | ✅ |
| Phase 0 CLARIFYING 调用 | `loop.py:138-144` | ✅ |
| 澄清事件推送 | `loop.py:144` | ✅ |
| **用户确认前暂停循环** | — | ❌ 澄清后立即进入 PLANNING，不等待用户反馈 |

---

### 🔵 Bug 修复记录（本轮会话）

| # | Bug | 严重程度 | 状态 |
|---|-----|---------|------|
| 1 | `agent_a.py` — `refine_prompt` 方法被误删（代码掉入 `clarify_request` 内成为死代码） | **CRITICAL** | ✅ 已修复 |
| 2 | `loop.py` — `compacted` 变量创建后未注入 AgentA | **HIGH** | ✅ 已修复 |
| 3 | `loop.py` — 压缩触发时错误发送 `DrawEvent.ERROR` | **MEDIUM** | ✅ 已修复 |
| 4 | `loop.py` — clarification 不暂停生成 | **MEDIUM** | ⚠️ 已知限制（架构需较大改动） |
| 5 | `generate_image.py` — `_generate_http` 使用未定义变量 `ctx` | **CRITICAL** | ✅ 已修复 |
| 6 | `generate_image.py` — `_generate_mcp` 冗余内部 `import base64` | **LOW** | ✅ 已修复 |

### 语法验证

```
38 个 Python 源文件全部通过 ast.parse()
OK: 38 / FAIL: 0
```

### 结论

P1（能跑）和 P2（可靠）的**核心后端代码已就绪**，修复了 5 个 Bug（含 2 个 Critical）。剩余工作集中于：
- **前端 UI**：设置面板拆分、下载/导出按钮、版本对比视图、Prompt diff、错误卡片、桌面通知
- **clarification 暂停**：需技术改造以支持异步等待用户确认
- **npm/离线资源**：字体和图标本地化

---

## 十、P5 — 待解决问题清单（提交开发团队）

> 以下为 P1/P2/P3 验证后确认仍未解决的问题，按优先级排列。每个问题标注了类型（前端/后端/架构）、涉及文件和实现建议。

### P5-1 🔴 设置面板拆分（前端）

**来源**：P2.3 未完成部分 | **类型**：前端

当前 Web UI 将所有参数（模型配置 + 生图参数）混在一个抽屉面板中。需拆分为两个独立入口。

**涉及文件**：
- `ui/static/index.html:103-196` — 当前设置面板 HTML
- `ui/static/css/style.css` — 新增系统设置页面样式
- `ui/static/js/events.js:190-227` — `AppActions.applySettings` / `resetSettings`

**具体要求**：
1. 创建独立的"系统设置"页面/模态框，包含 Agent A/B/C 的 Provider/Model/API Base/API Key/Temperature
2. 原设置面板仅保留图像参数（宽/高/张数）、质量参数（步数/引导力/种子）、Agent 参数（最大轮数/自动接受）
3. 快捷参数栏从下拉抽屉改为输入框上方可折叠横条
4. 系统设置中的 API Key 改用 `sessionStorage`（关闭浏览器自动清除）
5. `PUT /api/config` 端点联动（后端已有 `GET /api/config`，需新增 PUT）

---

### P5-2 🔴 需求澄清暂停（架构改造）

**来源**：P3.7 未完成部分 | **类型**：后端 + 前端

当前 `loop.py:138-144` 调用 `clarify_request()` 后**立即进入 PLANNING**，不等待用户确认。

**涉及文件**：
- `orchestrator/loop.py:138-144` — Phase 0 CLARIFYING
- `api/websocket.py` — WebSocket 消息接收
- `ui/static/js/events.js` — 事件处理

**具体要求**：
1. Phase 0 完成后，loop **暂停**（设置 `session.interrupt_event`），等待用户通过 WebSocket 发送 `{type: "clarify_accept"}` 或 `{type: "clarify_modify", text: "..."}` 指令
2. 前端渲染确认卡片（Agent 的理解摘要 + "确认" / "修改需求" 按钮）
3. 用户点"修改需求"时，将补充文本追加到 `user_request` 并重新进入 Phase 0
4. `server_runner.py` 需支持 loop 暂停/恢复（当前 `cancel()` 只能取消，不能恢复）

---

### P5-3 🟡 迭代版本浏览器（前端）

**来源**：P3.2 | **类型**：前端

用户无法对比不同轮次的生成结果、回退到历史版本。

**涉及文件**：
- `ui/static/js/compare.js` — **新建**
- `ui/static/js/renderer.js:33-61` — 迭代卡片渲染
- `ui/static/js/events.js:166-188` — `AppActions`

**具体要求**：
1. 迭代卡片头部添加"对比"按钮
2. 点击弹出对比视图：左右/上下并排显示不同轮次的图片
3. 底部显示对应 prompt 和 inspection 摘要
4. "回退到此版本"按钮 → `POST /api/sessions/{id}/interrupt {action: "rollback", data: {target: N}}`
5. 支持拖拽选择要对比的轮次（如选择第 1 轮和第 3 轮对比）

---

### P5-4 🟡 Prompt 追溯与 Diff（前端）

**来源**：P3.3 | **类型**：前端

用户无法查看每轮的完整 prompt，也无法对比 prompt 变更。

**涉及文件**：
- `ui/static/js/renderer.js:33-61` — 迭代卡片

**具体要求**：
1. 迭代卡片展开后显示完整 prompt（当前仅显示图片+审查结果）
2. 第 2+ 轮卡片附 `[查看 Prompt 变更]` 链接
3. 前端做简单行级 diff：新增=绿色、删除=红色、修改=黄色
4. 最终 prompt 旁加"复制"按钮

---

### P5-5 🟡 错误处理 UX（前端）

**来源**：P3.4 | **类型**：前端

当前仅有 toast 提示错误，用户无法重试，无引导信息。

**涉及文件**：
- `ui/static/js/events.js:73-76` — 错误事件处理
- `ui/static/js/api.js:79-117` — `WSClient`

**具体要求**：
1. 错误发生时显示**错误卡片**（红色背景，含错误描述 + "重试"按钮 + "新建会话"按钮）
2. API Key 未配置时显示引导卡片（而非静默失败）
3. WebSocket `onclose` 时自动重连（指数退避 1s/2s/4s，最多 5 次）
4. 生成阶段网络超时时提供"继续等待"或"取消"选项

---

### P5-6 🟡 图片操作（前端）

**来源**：P3.1 | **类型**：前端

**涉及文件**：
- `ui/static/js/renderer.js:52-53` — 迭代图片渲染
- `ui/static/js/viewer.js` — 图片查看器

**具体要求**：
1. 每张图片右下角添加**下载按钮**（`<a download>` 或 `fetch + createObjectURL`）
2. 图片查看器中添加"复制图片"功能
3. 收藏/星标标记（`AppState` 新增 `favorites: Set`，localStorage 持久化）
4. 图片 hover 显示 tooltip（seed、尺寸、所属轮次）

---

### P5-7 🟢 状态栏与桌面通知（前端）

**来源**：P3.5 | **类型**：前端

**涉及文件**：
- `ui/static/index.html:47` — `#chatStatus`
- `ui/static/js/events.js` — 事件处理
- `ui/static/js/renderer.js:106-118` — `setLoading`

**具体要求**：
1. 状态栏文案细化：`就绪` → `规划中` → `生成中` → `审查中` → `评估中` → `完成`
2. `loop.terminated` 时若页面不可见，触发 `new Notification('DrawAgent', {body: '生成完成', icon: ...})`
3. 首次触发时请求 Notification 权限

---

### P5-8 🟢 会话导出按钮（前端）

**来源**：P3.6 前端部分 | **类型**：前端

后端 `GET /api/sessions/{id}/export` 已实现。

**涉及文件**：
- `ui/static/js/events.js` — `AppActions`
- `ui/static/index.html` — 会话列表/操作区

**具体要求**：
1. 会话列表每个 item 旁添加导出按钮
2. 或在侧边栏底部添加"导出当前会话"按钮
3. 触发下载 ZIP（含 images/、iterations.json、messages.json）

---

### P5-9 🟢 快捷键（前端）

**来源**：原 REVIEW §7.3-F | **类型**：前端

| 快捷键 | 功能 | 当前状态 |
|--------|------|---------|
| `Esc` | 取消生成 / 关闭查看器 | 查看器已实现，取消未实现 |
| `Ctrl+S` | 下载当前图片 | ❌ |
| `Ctrl+Shift+N` | 新建会话 | ❌ |

**涉及文件**：`ui/static/index.html:227-335` — DOMContentLoaded 事件绑定

---

### P5-10 🟢 字体与图标离线化（前端）

**来源**：P4.4 | **类型**：前端

当前依赖 CDN：Google Fonts (Inter + Noto Sans SC) + Font Awesome (fa-solid)。

**涉及文件**：
- `ui/static/index.html:7-8` — CDN link
- `ui/static/css/style.css:1-18` — CSS 变量/字体

**具体要求**：
1. 下载 Inter + Noto Sans SC woff2 子集到 `static/fonts/`
2. 添加 `@font-face` 声明
3. Font Awesome 图标替换为内联 SVG 或本地文件（需要的图标约 20 个：user, robot, wand, plus, gear, check, compass, pause, paper-plane, bars, language, eraser, chevron-left/right/down, xmark, shuffle, trash, circle-info, circle-check, circle-exclamation, message）

---

### P5-11 🟢 移动端适配增强（前端）

**来源**：原 REVIEW §7.3-I | **类型**：前端

当前 CSS 有基础 responsive（`@media max-width:768px`），但：
1. 设置面板在手机上占满全屏，返回按钮不明显
2. 侧边栏在手机上用 `position:fixed` 覆盖，但无遮罩层
3. 图片查看器在手机上不支持手势缩放

**涉及文件**：`ui/static/css/style.css:434-442`

---

### P5-12 🔵 API Key 安全（安全加固）

**来源**：P4.1 | **类型**：前端

当前 `app.js:29` 将 API Key 存入 `localStorage`（明文持久化）。

**要求**：
1. 系统设置中的 API Key 改用 `sessionStorage`（关闭浏览器自动清除）
2. 或完全不存储，每次都需要输入（更安全但体验差）
3. 前端发送时不记录到 console.log（当前 `api.js:18` 打印 body 可能含 Key）

---

### P5-13 🔵 资源管理与代码清理（技术债务）

**来源**：P4.2/P4.3 | **类型**：后端

| # | 问题 | 文件 | 修复方案 |
|---|------|------|---------|
| 1 | httpx 客户端生命周期 | `providers/openai_compat.py`, `tools/generate_image.py` | 实现 `__aenter__/__aexit__`，在 `main.py` 用 `async with` |
| 2 | 阻塞 `input()` | `tools/human_input.py:49` | CLI 改用 `asyncio.get_event_loop().run_in_executor` |
| 3 | 重复 `ImageRecord` | `core/types.py` vs `persistence/models.py` | 统一用 `core/types.py` |
| 4 | `pyproject.toml` 构建 | `pyproject.toml:36-44` | `[tool.setuptools]` → `[tool.hatch.build.targets.wheel]` |
| 5 | FastAPI 弃用 API | `api/app.py:36` | `on_event("startup")` → `lifespan` |
| 6 | `dev` 依赖错误 | `pyproject.toml:27` | `httpx2` → `httpx` |

---

### 工作量估算

| 编号 | 内容 | 类型 | 预计 |
|------|------|------|------|
| P5-1 | 设置面板拆分 | 前端 | 1.5 天 |
| P5-2 | 需求澄清暂停 | 架构 | 1.5 天 |
| P5-3 | 迭代版本浏览器 | 前端 | 1 天 |
| P5-4 | Prompt 追溯与 Diff | 前端 | 0.5 天 |
| P5-5 | 错误处理 UX | 前端 | 0.5 天 |
| P5-6 | 图片操作 | 前端 | 0.5 天 |
| P5-7 | 状态栏与桌面通知 | 前端 | 0.5 天 |
| P5-8 | 会话导出按钮 | 前端 | 0.25 天 |
| P5-9 | 快捷键 | 前端 | 0.25 天 |
| P5-10 | 字体/图标离线化 | 前端 | 0.5 天 |
| P5-11 | 移动端适配增强 | 前端 | 0.5 天 |
| P5-12 | API Key 安全 | 前端 | 0.25 天 |
| P5-13 | 资源管理与代码清理 | 后端 | 1 天 |
| **合计** | | | **~8.5 天** |
