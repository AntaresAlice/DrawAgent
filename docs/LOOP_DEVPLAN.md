# DrawAgent Loop 重构开发方案 (v2 — agentic 模式)

> 基于 LOOP_DESIGN.md 的架构设计 + opencode 实现参考，细化到模块、文件、接口级别的开发计划。
> 已整合 AUDIT_LOOP_DEVPLAN.md (20 条审计意见，全部采纳)。
>
> **Feature Flag**: `loop.engine: "classic"` (默认, 不变) | `"agentic"` (新)
> **核心原则**: agentic 模式全部新文件/新路径，classic 路径一行不改。两者完全隔离。

---

## 架构总览: 从五阶段状态机到 LLM 驱动循环

```
───────────────────────── Classic (程序驱动, 不变) ─────────────────────

SessionRunner._execute_loop()
  └─ _run_phase_0() → _run_phase_1() → _run_phase_2()
     → _run_phase_3() → _run_phase_4() → _run_phase_5()
     → (不通过?) → 从 Phase 2 重新开始

───────────────────────── Agentic (LLM 驱动, 新增) ─────────────────────

SessionRunner._run_agentic()
  └─ outer loop: while(has_pending_input)
       └─ inner loop: while(needs_continuation)
            └─ agent_a.run_agentic_turn()  ← 保留 AgentA, 新增方法
                 ├─ 获取完整上下文 (system prompt + messages + state + lessons)
                 ├─ ToolRegistry.materialize_all() → 全部工具可用
                 ├─ 流式推理 (Agent A / DeepSeek)
                 ├─ 执行工具调用 → 注入结果
                 └─ 判断 needs_continuation
```

**隔离策略:**

```
新文件 (agentic 专属):
  src/drawagent/models/agentic_session.py    # AgenticSession 数据模型
  src/drawagent/orchestrator/agentic_loop.py  # Agentic 循环
  src/drawagent/orchestrator/context_builder.py  # 上下文构建
  src/drawagent/orchestrator/compactor.py     # LLM 驱动压缩
  src/drawagent/orchestrator/learner.py       # 经验积累
  src/drawagent/orchestrator/guardrails.py    # 安全边界
  src/drawagent/tools/finalize.py             # finalize 工具
  src/drawagent/tools/memory.py               # save/load/search_memory 工具

修改文件 (agentic 能力增量):
  src/drawagent/orchestrator/server_runner.py  # 新增 _run_agentic()
  src/drawagent/agents/agent_a.py              # 新增 run_agentic_turn()
  src/drawagent/tools/base.py                  # 新增 materialize_all()
  src/drawagent/main.py                        # 新增 agentic WS 事件列表 (并行 emit)
  config.yaml                                  # 新增 loop.engine + agentic.* 配置节

不动文件 (classic 路径原封不动):
  src/drawagent/orchestrator/loop.py           # 一行不改
  src/drawagent/core/types.py                  # Session 一行不改
  src/drawagent/orchestrator/session.py        # 一行不改 (SQLite 扩展新表)
  src/drawagent/orchestrator/interrupt.py       # 一行不改
  src/drawagent/context/compaction.py          # 一行不改 (classic 保留)
  src/drawagent/context/assembler.py           # 一行不改
```

---

## 阶段 0: 数据库 Schema 升级 + 配置扩展

> **目标**: 在编码开始前定好数据层和配置层，避免后续返工
> **风险**: 低 — 只加新表/新配置，不改现有

### 0.1 新增数据库表 (SQLite)

**文件**: `src/drawagent/orchestrator/session.py` (在现有 `Database` 类中新增表)

```sql
-- 保留现有四张表: sessions, iterations, images, inspections
-- 新增以下表 (agentic 模式专用):

CREATE TABLE IF NOT EXISTS agentic_turns (
    id          TEXT PRIMARY KEY,
    session_id  TEXT NOT NULL REFERENCES sessions(id),
    seq         INTEGER NOT NULL,  -- monotonic within session
    user_msg_id TEXT,              -- FK to agentic_messages
    assistant_text TEXT,
    finish_reason TEXT,            -- "stop" | "tool_calls" | "error"
    tokens_used INTEGER DEFAULT 0,
    started_at  TEXT,
    completed_at TEXT,
    UNIQUE(session_id, seq)
);

CREATE TABLE IF NOT EXISTS agentic_tool_calls (
    id          TEXT PRIMARY KEY,
    turn_id     TEXT NOT NULL REFERENCES agentic_turns(id),
    session_id  TEXT NOT NULL REFERENCES sessions(id),
    tool_name   TEXT NOT NULL,
    arguments   TEXT NOT NULL,  -- JSON
    status      TEXT NOT NULL DEFAULT 'pending',  -- pending/running/completed/error
    result      TEXT,           -- JSON (null if pending/running)
    error       TEXT,
    started_at  TEXT,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS agentic_messages (
    id          TEXT PRIMARY KEY,
    session_id  TEXT NOT NULL REFERENCES sessions(id),
    seq         INTEGER NOT NULL,
    delivery    TEXT NOT NULL DEFAULT 'steer',  -- steer/queue
    text        TEXT NOT NULL,
    admitted_at TEXT NOT NULL,
    promoted_at TEXT,           -- NULL = not yet fed to LLM
    UNIQUE(session_id, seq)
);

CREATE TABLE IF NOT EXISTS agentic_compactions (
    id          TEXT PRIMARY KEY,
    session_id  TEXT NOT NULL REFERENCES sessions(id),
    seq         INTEGER NOT NULL,
    summary     TEXT NOT NULL,
    recent_context TEXT,
    compacted_turn_count INTEGER DEFAULT 0,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agentic_lessons (
    id          TEXT PRIMARY KEY,
    session_id  TEXT NOT NULL REFERENCES sessions(id),
    seq         INTEGER NOT NULL,
    lesson      TEXT NOT NULL,   -- "category | observation | strategy" 格式
    created_at  TEXT NOT NULL
);
```

### 0.2 SessionManager 扩展方法

**文件**: `src/drawagent/orchestrator/session.py` (扩展，不改现有方法)

```python
class SessionManager:
    # ===== 现有方法全部保留 (classic 路径) =====
    # persist_session(), add_iteration(), load_all(), load_session(), ...

    # ===== 新增方法 (agentic 路径) =====
    def save_agentic_turn(self, session_id: str, turn_data: dict): ...
    def save_tool_call(self, turn_id: str, tool_data: dict): ...
    def save_message(self, session_id: str, msg_data: dict): ...
    def promote_messages(self, session_id: str, delivery: str, cutoff_seq: int) -> int: ...
    def has_pending_messages(self, session_id: str, delivery: str) -> bool: ...
    def save_compaction(self, session_id: str, comp_data: dict): ...
    def save_lesson(self, session_id: str, lesson: str): ...
    def load_agentic_history(self, session_id: str) -> dict: ...
```

### 0.3 数据库迁移脚本

**文件**: `scripts/migrate_to_agentic.py` (新建)

```python
"""
运行一次: 为现有数据库创建新表，不做数据迁移 (classic sessions 保持原样)
"""
```

### 0.4 配置文件扩展

**文件**: `config.yaml` (新增节)

```yaml
loop:
  engine: "classic"     # "classic" | "agentic"

  # ===== classic 配置 (不变) =====
  max_iterations: 10
  keep_recent_iterations: 3
  compaction_threshold_tokens: null
  # ...

  # ===== agentic 配置 (新增) =====
  agentic:
    max_tool_rounds: 10        # inner loop 上限
    max_agentic_rounds: 20     # outer loop 上限
    max_finalize_rejections: 3  # 连续 finalize 被拒上限

    compaction:
      enabled: true
      buffer_tokens: 20480     # 类比 opencode DEFAULT_BUFFER
      keep_tokens: 8000        # 压缩后保留的最近 context
      summary_max_tokens: 4096
      # 不设独立 model: 直接复用 loop 的 agent_a 主模型, 减少配置复杂度

    learning:
      enabled: true
      max_lessons: 10          # system prompt 注入的最大经验条数
      reflection_model: "deepseek-v4-flash"

    # context window (用于溢出检测)
    context_window: 65536      # DeepSeek v4 上下文窗口
    output_buffer: 8192        # 留给输出的 token 余量
```

### 阶段 0 检查点

- [ ] 5 张新表在 SQLite 中创建成功
- [ ] `SessionManager` 新方法通过单元测试 (mock DB)
- [ ] `migrate_to_agentic.py` 对空库和已有数据的库都能正常执行
- [ ] `config.yaml` 新节被 `ServerRunner` 正确加载

---

## 阶段 1: AgenticSession 数据模型

> **目标**: 定义 agentic 模式专用的数据模型，与 classic `core/types.py:Session` 完全隔离
> **策略**: "新模型 + 适配层"，旧 `Session` 一行不改

**隔离方案 (回应审计 #1):**

```
经典路径 (不动):           Agentic 路径 (新增):
  core/types.py              models/agentic_session.py
    Session                   AgenticSession
    (state, interrupt_event,    (id, user_request, messages[],
     pending_action,             turns[], compactions[],
     steer_message, ...)         learned_lessons[], errors[])
```

两者互不引用。`ServerRunner` 根据 `loop.engine` 选择使用哪个。

### 1.1 AgenticSession 定义

**文件**: `src/drawagent/models/agentic_session.py` (新建)

```python
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal
from uuid import uuid4


@dataclass
class AgenticUserMessage:
    """用户输入 (类比 opencode session_input 中的 Prompted)"""
    id: str = field(default_factory=lambda: f"umsg_{uuid4().hex[:8]}")
    text: str
    delivery: Literal["steer", "queue"]
    admitted_at: datetime = field(default_factory=datetime.now)
    promoted_at: datetime | None = None  # NULL → 尚未注入 LLM
    seq: int = 0


@dataclass
class AgenticToolCall:
    """一次工具调用 (类比 opencode AssistantTool)"""
    call_id: str = field(default_factory=lambda: f"call_{uuid4().hex[:8]}")
    tool_name: str
    arguments: dict = field(default_factory=dict)
    status: Literal["pending", "running", "completed", "error"] = "pending"
    result: dict | None = None
    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


@dataclass
class AgenticTurn:
    """
    一轮 LLM 交互 (类比 opencode assistant message)
    user_message 不为 None —— 第一次 turn 从 InputQueue promote 产生
    """
    id: str = field(default_factory=lambda: f"turn_{uuid4().hex[:8]}")
    user_message: "AgenticUserMessage"  # 必填: 由 promote 保证
    assistant_text: str | None = None
    tool_calls: list[AgenticToolCall] = field(default_factory=list)
    finish_reason: Literal["stop", "tool_calls", "error", "interrupted"] | None = None
    tokens_used: int = 0
    started_at: datetime | None = None
    completed_at: datetime | None = None


@dataclass
class AgenticCompaction:
    """上下文压缩 (类比 opencode compaction message)"""
    id: str = field(default_factory=lambda: f"comp_{uuid4().hex[:8]}")
    seq: int
    summary: str
    recent_context: str = ""
    compacted_turn_count: int = 0
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class AgenticSession:
    id: str = field(default_factory=lambda: f"ses_{uuid4().hex[:8]}")
    user_request: str           # 第一条消息，永不覆盖
    messages: list[AgenticUserMessage] = field(default_factory=list)
    turns: list[AgenticTurn] = field(default_factory=list)
    compactions: list[AgenticCompaction] = field(default_factory=list)
    learned_lessons: list[str] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    # 兼容性: Web UI 仍需要 iterations / images 等字段
    iterations: list[dict] = field(default_factory=list)
    finalize_rejection_count: int = 0  # 连续 finalize 被拒计数 (审计 #17)
```

### 1.2 InputQueue (会话级单例)

**文件**: `src/drawagent/orchestrator/agentic_loop.py` (内嵌类，或在 agentic_session.py 中)

```python
class InputQueue:
    """
    AgenticSession 级别的输入队列。
    生命周期绑定于 AgenticSession — 由 SessionRunner 持有引用，
    WebSocket handler 通过 session_id 查找对应 queue 实例 (类比 opencode 的 session_input 表)。

    回应审计 #6: InputQueue 不再是 run_session() 的局部变量，
    而是 SessionRunner.agentic_queue 属性，WS handler 通过 runner 访问。
    """
    def __init__(self, session_id: str, db: SessionManager):
        self.session_id = session_id
        self.db = db

    def admit(self, text: str, delivery: Literal["steer", "queue"]) -> AgenticUserMessage:
        """记录一条用户输入"""
        ...

    def has_pending(self, delivery: Literal["steer", "queue"]) -> bool:
        """是否有未 promote 的消息"""
        ...

    def promote_steers(self, cutoff_seq: int = None) -> list[AgenticUserMessage]:
        """Promote 所有 steer 消息 (类比 opencode promoteSteers)"""
        ...

    def promote_next_queued(self) -> AgenticUserMessage | None:
        """Promote 恰好一条 queue 消息 (类比 opencode promoteNextQueued)"""
        ...
```

### 1.3 Web UI 兼容适配

```python
def agentic_session_to_api_response(session: AgenticSession) -> dict:
    """
    将 AgenticSession 转为 Web UI API 兼容格式。
    确保 GET /api/sessions 返回格式不变。
    """
    return {
        "id": session.id,
        "user_request": session.user_request,
        "iterations": session.iterations,
        "learned_lessons": session.learned_lessons,
        "error": session.errors[-1] if session.errors else None,
        "created_at": session.created_at.isoformat(),
        "updated_at": session.updated_at.isoformat(),
        "engine": "agentic",   # 前端据此判定是否启用新 UI
        "message_count": len(session.messages),
        "turn_count": len(session.turns),
    }
```

### 阶段 1 检查点

- [ ] `AgenticSession` / `AgenticTurn` / `AgenticUserMessage` / `AgenticCompaction` 定义完毕
- [ ] `InputQueue` 的 admit / promote 通过单元测试 (mock SessionManager)
- [ ] `agentic_session_to_api_response()` 输出格式与现有 `GET /api/sessions` 兼容
- [ ] classic `core/types.py:Session` 零改动

---

## 阶段 2: Agent 循环 + 工具解耦 + Guardrails (并行)

> **目标**: 实现 LLM 驱动的 outer+inner 循环 (最核心)
> **为什么合并 2+3+7**: 回应审计 #310 — runner_loop 需要从 registry 获取工具，guardrails 是循环的内嵌逻辑，不应分散到独立阶段
> **风险**: 高 — 充分 mock 测试后再对接真实 LLM

### 2.1 ToolRegistry 扩展 (不改旧逻辑)

**文件**: `src/drawagent/tools/base.py` (修改现有 — 回应审计 #4)

```python
class ToolRegistry:
    """现有类 — 保留所有现有方法，新增 agentic 模式方法"""

    # ===== 现有方法 (classic 不变) =====
    def register(self, tool: BaseTool): ...
    def materialize(self, enabled_tools: set[str] | None = None) -> ToolMaterialization: ...

    # ===== 新增方法 (agentic) =====
    def materialize_all(self) -> ToolMaterialization:
        """
        Agentic 模式: 返回所有已注册工具的 definitions。
        不过滤 enabled_tools — LLM 自主决定调用什么。

        类比 opencode ToolRegistry.materialize() (无 permission filter 的情况)。
        """
        definitions = []
        for name, tool in self._tools.items():
            definitions.append({
                "type": "function",
                "function": {
                    "name": name,
                    "description": tool.description,
                    "parameters": tool.input_schema  # JSON Schema
                }
            })
        return ToolMaterialization(definitions=definitions, settle=self._settle)
```

### 2.2 finalize 工具

**文件**: `src/drawagent/tools/finalize.py` (新建)

```python
"""finalize 工具 — agentic 模式下 LLM 明确终止的标志"""

FINALIZE_TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "accepted_images": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "绝对路径或 session 相对路径列表，表示验收通过的图片。"
                "必须基于实际的 inspection 结果，不能凭空声称通过。"
            )
        },
        "rejected_images": {
            "type": "array",
            "items": {"type": "string"},
            "description": "验收未通过的图片路径列表"
        },
        "reason": {
            "type": "string",
            "description": (
                "验收理由。必须引用具体的 inspection 结果，逐条说明哪些检查通过/未通过。"
                "格式: 'PASS: composition (构图平衡), FAIL: anatomy (手指关节数不对, 见图 inspection_23)'"
            )
        }
    },
    "required": ["accepted_images", "reason"]
}

async def execute_finalize(accepted_images: list[str], rejected_images: list[str], reason: str) -> dict:
    return {
        "status": "finalized",
        "accepted": accepted_images,
        "rejected": rejected_images,
        "reason": reason
    }
```

### 2.3 新增 generate_image / inspect_image / compare_images 工具类

**文件**: `src/drawagent/tools/generate_image.py` 等 (修改现有 — 注册为 `BaseTool` 子类)

现有工具已继承 `BaseTool`，在 `__init_subclass__` 或初始化时自动注册到 `ToolRegistry`。agentic 模式不需要改动工具本身 — `materialize_all()` 会直接暴露它们。

**Tool schema 来源标注 (回应审计 #14):**

| 工具 | Schema 来源 | 原因 |
|------|------------|------|
| `generate_image` | **MCP-proxied** — schema 从 Agent B MCP server 动态获取，客户端硬编码的 schema 仅作 fallback | 遵循 PITFALLS "MCP server 的 TOOL_SCHEMA 是 truth" 原则 |
| `inspect_image` | **客户端工具** — schema 硬编码 | VLM 调用逻辑在客户端 |
| `compare_images` | **客户端工具** — schema 硬编码 | 对比逻辑在客户端 |
| `finalize` | **客户端工具** — schema 硬编码 | 纯逻辑，无外部依赖 |
| `save_memory` | **客户端工具** — schema 硬编码 | 持久化逻辑在客户端 |
| `load_memory` | **客户端工具** — schema 硬编码 | 查询逻辑在客户端 |

### 2.4 AgentA 新增 run_agentic_turn()

**文件**: `src/drawagent/agents/agent_a.py` (扩展 — 回应审计 #9)

```python
class AgentA:
    # ===== 现有 run_turn() 保留 (classic) =====
    async def run_turn(self, ...): ...

    # ===== 新增 (agentic) =====
    async def run_agentic_turn(
        self,
        system_prompt: str,
        messages: list[dict],
        tools: list[dict],
        event_bus: EventBus,
        verbose: bool = False,
    ) -> AgenticTurnResult:
        """
        Agentic 模式的一次 LLM 调用 + 工具执行沉降。
        类比 opencode runTurn() 中的 LLM streaming + tool settle 部分。

        Returns:
            AgenticTurnResult:
                text: str
                tool_results: list[AgenticToolCall]
                finish_reason: Literal["stop", "tool_calls", "error"]
                finalized: bool  # LLM 调用了 finalize 工具且 execute 成功
                tokens_used: int

        Flow:
        1. 流式发送给 DeepSeek, 收集 text + tool_calls
        2. 对 tool_calls 逐个执行:
           - finalize → 程序 verify + 记录 reject count
           - generate_image → 发 WS 事件, 记录到 iterations (兼容前端)
           - 其他工具 → 执行
        3. 工具结果注入 tool_results 供下轮 inner loop 使用
        """
        ...
```

**关键: run_agentic_turn() 替代 `_llm_call_with_tools()`** — 审计 #9 指出旧方案绕过了 `AgentA`，新方案 AgentA 保留为主入口，agentic 能力作为新方法叠加。

### 2.5 上下文构建器

**文件**: `src/drawagent/orchestrator/context_builder.py` (新建)

```python
class ContextBuilder:
    """
    构建 agentic run_turn 所需的 system prompt + 消息历史。
    类比 opencode 中的 system prompt assembly + toLLMMessages()。
    """

    def __init__(self, agent_config: dict):
        self.agent_config = agent_config

    def build_system_prompt(self, session: AgenticSession) -> str:
        """类比 opencode: [agent.system, system.baseline].filter(Boolean).join("\n\n")"""
        parts = [self.agent_config.get("system_prompt", "")]
        parts.append(self._state_summary(session))
        parts.append(self._lessons_summary(session))
        parts.append(self._compaction_summary(session))
        return "\n\n---\n\n".join(p for p in parts if p)

    def build_messages(self, session: AgenticSession) -> list[dict]:
        """类比 opencode toLLMMessages() — turns → OpenAI messages 数组"""
        # [compaction summaries as user messages] + [turns as user/assistant/tool messages]
        ...

    def _state_summary(self, session: AgenticSession) -> str:
        """程序提供的结构化状态信息"""
        lines = ["## Current Session State"]
        lines.append(f"- User request: {session.user_request}")
        lines.append(f"- Turns completed: {len(session.turns)}")
        if session.iterations:
            last = session.iterations[-1]
            lines.append(f"- Last generated images: {len(last.get('images', []))} files")
            if last.get("decision"):
                d = last["decision"]
                lines.append(f"- Last quality: {'PASSED' if d.get('passed') else 'FAILED'} "
                             f"(confidence {d.get('confidence', '?')}/10)")
        return "\n".join(lines)

    def _lessons_summary(self, session: AgenticSession) -> str:
        """经验注入"""
        if not session.learned_lessons:
            return ""
        lines = ["## Lessons Learned from Previous Iterations"]
        for i, lesson in enumerate(session.learned_lessons[-10:], 1):
            lines.append(f"{i}. {lesson}")
        lines.append("You are NOT required to follow all lessons — use your best judgment.")
        return "\n".join(lines)

    @staticmethod
    def _compaction_summary(session: AgenticSession) -> str:
        if not session.compactions:
            return ""
        comp = session.compactions[-1]
        return f"<conversation-checkpoint>\n<summary>{comp.summary}</summary>\n</conversation-checkpoint>"
```

**回应审计 #11**: 原方案中 `_format_decision()` / `_extract_issues()` 未定义，新版直接用 `last['decision']['passed']` 等字典访问，无需额外辅助函数。

### 2.6 Agentic 主循环

**文件**: `src/drawagent/orchestrator/agentic_loop.py` (新建)

```python
class AgenticLoop:
    """
    LLM 驱动的 outer + inner 循环。
    类比 opencode SessionRunner.run() 的 while(shouldRun) + while(needsContinuation)。
    """

    def __init__(self, session: AgenticSession, agent_a: AgentA,
                 registry: ToolRegistry, config: dict, event_bus: EventBus):
        self.session = session
        self.agent_a = agent_a
        self.registry = registry
        self.config = config
        self.event_bus = event_bus
        self.guardrails = SessionGuardrails(config.get("agentic", {}))
        self.ctx = ContextBuilder(config.get("agent_a", {}))
        self.queue = InputQueue(session.id, db=...)  # 审计 #6: 会话级属性

    async def run(self) -> AgenticSession:
        max_rounds = self.config.get("agentic", {}).get("max_agentic_rounds", 20)
        outer_round = 0

        while outer_round < max_rounds:
            # ── Promote inputs ── (类比 opencode promoteSteers / promoteNextQueued)
            has_queue = self.queue.has_pending("queue")
            if has_queue:
                self.queue.promote_next_queued()
            self.queue.promote_steers()

            if not had_any_promotion:
                break  # 没有待处理输入，结束

            # ── Guardrail: check iterations ──
            if outer_round >= max_rounds:
                await self.event_bus.emit("agentic.max_rounds_reached",
                    {"rounds": outer_round, "max": max_rounds})
                break

            # ── INNER LOOP (tool chaining) ──
            needs_continuation = True
            tool_round = 0
            max_tool_rounds = self.config.get("agentic", {}).get("max_tool_rounds", 10)

            while needs_continuation:
                # Guardrail: tool round limit
                if self.guardrails.check_tool_rounds(self.session, tool_round, max_tool_rounds):
                    # 注入 system 消息强制 finalize
                    self._inject_force_finalize_message()

                # 1. Prepare context
                system_prompt = self.ctx.build_system_prompt(self.session)
                messages = self.ctx.build_messages(self.session)
                tools = self.registry.materialize_all()

                # 2. Compact if needed (阶段 4)
                if self.config.get("agentic", {}).get("compaction", {}).get("enabled"):
                    compactor = ContextCompactor(self.config)
                    if compactor.compact_if_needed(self.session, system_prompt, messages, tools):
                        # 重新构建上下文 (compact 后 turns 已变)
                        system_prompt = self.ctx.build_system_prompt(self.session)
                        messages = self.ctx.build_messages(self.session)

                # 3. LLM call
                await self.event_bus.emit("turn.started", {"session_id": self.session.id})
                result = await self.agent_a.run_agentic_turn(
                    system_prompt=system_prompt,
                    messages=messages,
                    tools=tools.definitions,
                    event_bus=self.event_bus,
                )
                await self.event_bus.emit("turn.ended", {
                    "session_id": self.session.id,
                    "finish_reason": result.finish_reason,
                    "finalized": result.finalized,
                    "tokens_used": result.tokens_used,
                })

                # 4. Record turn
                turn = AgenticTurn(
                    user_message=self.session.messages[-1],  # 最近 promote 的消息
                    assistant_text=result.text,
                    tool_calls=result.tool_results,
                    finish_reason=result.finish_reason,
                    tokens_used=result.tokens_used,
                )
                self.session.turns.append(turn)

                # 5. Check continuity
                if result.finalized:
                    # LLM 调用了 finalize → 程序 verify
                    if self._verify_finalize(result):
                        needs_continuation = False
                    else:
                        # finalize 被拒绝 (审计 #17)
                        self.session.finalize_rejection_count += 1
                        if self.guardrails.check_finalize_rejections(self.session):
                            self._inject_finalize_rejection_message()
                        needs_continuation = True
                elif result.tool_calls and tool_round < max_tool_rounds:
                    needs_continuation = True
                    tool_round += 1
                else:
                    needs_continuation = self._needs_continuation_check(result)
                    # 回应审计 #5: 明确返回 needs_continuation bool，函数名清晰

                # 6. After settlement, check for new steer
                if not needs_continuation:
                    needs_continuation = self.queue.has_pending("steer")
                    if needs_continuation:
                        self.queue.promote_steers()

            # 7. Reflect at iteration end (阶段 4)
            if self.config.get("agentic", {}).get("learning", {}).get("enabled"):
                learner = ExperienceLearner(self.agent_a, self.config)
                await learner.reflect(self.session)

            outer_round += 1

        return self.session

    def _needs_continuation_check(self, result: AgenticTurnResult) -> bool:
        """
        回应审计 #5: 返回 True = 需要继续, False = 已完成。
        命名反映返回语义，不做暧昧的 'is really done'。
        """
        # LLM 返回了空回复 → 需要追问
        if not result.text or not result.text.strip():
            return True

        # LLM 返回了文本但没有调工具、没有调 finalize
        # 检查是否有图片可交付
        if not self.session.iterations:
            return True  # 没生成过图片 → 不能结束，需要追问

        last_iter = self.session.iterations[-1]
        has_images = bool(last_iter.get("images"))
        if not has_images:
            return True  # 有对话但没图片 → 需要追问 LLM 为什么没生成

        # 有图片 + LLM 说完成了 = 允许结束
        return False

    def _verify_finalize(self, result: AgenticTurnResult) -> bool:
        """
        验证 LLM 的 finalize 声明是否被实际 inspection 结果支持。
        回应审计 #17: 如果连续 N 次 finalize 被拒，注入 system 消息阻止死循环。
        """
        finalize_call = next((tc for tc in result.tool_results
                              if tc.tool_name == "finalize" and tc.status == "completed"), None)
        if not finalize_call:
            return False

        # 检查是否有 inspection 结果支撑
        # 如果上一轮 inspection 中存在 FAIL 但 finalize 声称通过 → 拒绝
        if self.session.iterations:
            last = self.session.iterations[-1]
            inspections = last.get("inspections", [])
            fails = [i for i in inspections if not i.get("passed", True)]
            if fails:
                # 有失败的检查项 → finalize 声称通过不合理
                return False

        return True

    def _inject_finalize_rejection_message(self):
        """注入 system 消息: 告知 LLM finalize 被拒绝的原因"""
        last = self.session.iterations[-1]
        fails = [i for i in last.get("inspections", []) if not i.get("passed", True)]
        msg = ("Your finalize was rejected because the following inspection checks failed:\n"
               + "\n".join(f"- [{i['dimension']}] {i.get('observation', 'no detail')}"
                           for i in fails)
               + "\nPlease fix these issues before calling finalize again.")
        self.session.messages.append(AgenticUserMessage(
            text=msg,
            delivery="steer",
            promoted_at=datetime.now()
        ))

    def _inject_force_finalize_message(self):
        """超出 tool round 上限, 强制 LLM finalize"""
        self.session.messages.append(AgenticUserMessage(
            text=("Tool round limit reached. You MUST call finalize now "
                  "with whatever results you have. Be honest about quality issues."),
            delivery="steer",
            promoted_at=datetime.now()
        ))
```

### 2.7 Guardrails

**文件**: `src/drawagent/orchestrator/guardrails.py` (新建)

```python
class SessionGuardrails:
    """
    回应审计 #17 + #7.2: 所有守卫逻辑集中管理。
    类比 opencode 的 maxSteps / compaction / overflow 边界。
    """

    def __init__(self, agentic_config: dict):
        self.max_tool_rounds = agentic_config.get("max_tool_rounds", 10)
        self.max_finalize_rejections = agentic_config.get("max_finalize_rejections", 3)
        self.context_window = agentic_config.get("context_window", 65536)
        self.output_buffer = agentic_config.get("output_buffer", 8192)

    def check_tool_rounds(self, session: AgenticSession, current_round: int, limit: int) -> bool:
        return current_round >= limit

    def check_finalize_rejections(self, session: AgenticSession) -> bool:
        """审计 #17: 连续 finalize 被拒超过上限 → 注入阻止消息"""
        return session.finalize_rejection_count >= self.max_finalize_rejections

    def check_token_budget(self, system: str, messages: list[dict], tools: list[dict]) -> bool:
        """返回 True = 需要压缩"""
        total = self._estimate_tokens(system) + sum(self._estimate_tokens(json.dumps(m)) for m in messages)
        total += sum(self._estimate_tokens(json.dumps(t)) for t in tools)
        return total > self.context_window - self.output_buffer

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """
        审计 #8: 不用 len(text)//4 (中文误差大)。
        用 tiktoken 或 provider estimate。
        """
        try:
            import tiktoken
            enc = tiktoken.get_encoding("cl100k_base")
            return len(enc.encode(text))
        except ImportError:
            # fallback: 1 char ≈ 0.5 tokens (保守估计中文)
            return int(len(text) * 0.5)
```

### 2.8 ServerRunner 集成

**文件**: `src/drawagent/orchestrator/server_runner.py` (扩展)

```python
class ServerRunner:
    def _execute_loop(self, session_id: str, prompt: str):
        engine = self.config.get("loop", {}).get("engine", "classic")

        if engine == "agentic":
            asyncio.create_task(self._run_agentic(session_id, prompt))
        else:
            # ===== classic 路径: 一行不改 =====
            asyncio.create_task(self._run_classic(session_id, prompt))

    async def _run_agentic(self, session_id: str, prompt: str):
        """Agentic 模式入口"""
        session = AgenticSession(user_request=prompt)
        queue = InputQueue(session.id, self.session_manager)
        queue.admit(prompt, delivery="queue")

        loop = AgenticLoop(
            session=session,
            agent_a=self.agent_a,
            registry=self.agent_a.registry,
            config=self.config,
            event_bus=EventBus(websocket_manager=self.ws_manager),
        )
        await loop.run()
```

### 阶段 2 检查点

- [ ] `run_agentic_turn()` mock 测试: mock LLM 返回 `generate_image` → `inspect_image` → `finalize` 链，验证 tool_results 正确
- [ ] `_needs_continuation_check()` 测试: 空回复、无图片、有图片的各种情况返回值正确
- [ ] `_verify_finalize()` 测试: 有 FAIL inspection 时拒绝 finalize；拒绝 3 次后注入系统消息
- [ ] tool round 超限时注入强制 finalize 消息
- [ ] Guardrails 的 token 估算用 tiktoken (或 fallback)
- [ ] classic `loop.py` / `agent_a.py:run_turn()` 零改动

---

## 阶段 3: 中断机制 (SteerController)

> **目标**: 用简单的 steer 消息注入替代 classic 的 `pending_action` + `interrupt_event`
> **风险**: 中 — asyncio 桥接需要正确处理

### 3.1 SteerController

**文件**: `src/drawagent/orchestrator/steer_controller.py` (新建 — 回应审计 #2: 不叫 interrupt.py)

```python
class SteerController:
    """
    Agentic 模式的中断/反馈控制器。
    类比 opencode 的 wake() + hasPending("steer") 机制。

    审计 #2: 不叫 interrupt.py (与现有文件冲突)
    审计 #3: 全部用 asyncio.Event (不用 threading.Event)
    """

    def __init__(self, input_queue: InputQueue, ws_manager):
        self.queue = input_queue
        self.ws_manager = ws_manager
        self._new_steer = asyncio.Event()

    async def handle_user_message(self, session_id: str, text: str):
        """
        WebSocket handler 调用此方法:
        1. 将用户消息存入 InputQueue (delivery="steer")
        2. 设置 asyncio.Event 通知循环有新输入
        """
        self.queue.admit(text, delivery="steer")

        # Emit WS 事件: 告知前端消息已接收
        await self.ws_manager.broadcast(session_id, {
            "type": "interrupt.accepted",
            "message": text,
            "delivery": "steer",
        })

        self._new_steer.set()

    async def wait_for_pending(self, timeout: float = 0.1) -> bool:
        """
        循环调用此方法检查是否有新 steer (类比 opencode hasPending("steer"))。
        非阻塞 — 如果无新消息，立即返回 False。
        """
        if self.queue.has_pending("steer"):
            self._new_steer.clear()
            return True
        try:
            await asyncio.wait_for(self._new_steer.wait(), timeout=timeout)
            self._new_steer.clear()
            return self.queue.has_pending("steer")
        except asyncio.TimeoutError:
            return False
```

### 3.2 对比 classic InterruptHandler

| Classic `InterruptHandler` | Agentic `SteerController` |
|---|---|
| `pending_action` (PAUSE/ACCEPT/CUSTOM/DONE) | `delivery="steer"` UserMessage |
| `interrupt_event` (asyncio.Event) → 暂停 loop | `_new_steer` (asyncio.Event) → 通知 loop 有新输入 |
| `handle(session, action, data)` → 复杂分支 | `handle_user_message(session_id, text)` → 简单入队 |
| `steer_message` 字段手动注入 Phase 2 | 自动在下一个 inner loop 迭代中注入 LLM 上下文 |

### 阶段 3 检查点

- [ ] `SteerController` 不与现有 `InterruptHandler` 共享文件路径
- [ ] 全部使用 `asyncio.Event` (不混用 threading)
- [ ] `wait_for_pending()` 非阻塞检查 + 阻塞等待均可工作
- [ ] WebSocket handler 在 agentic 模式下走 `SteerController`，classic 模式走原有 `InterruptHandler`

---

## 阶段 4: 经验积累 + 上下文压缩

> **目标**: LLM 从历史迭代中学习；长对话自动压缩上下文
> **风险**: 中高 — 需明确与现有 `CompactedHistory` 的关系

### 4.1 与现有 Compaction 的关系 (回应审计 #8)

```
Classic 模式 (保留):
  context/compaction.py → CompactedHistory → 规则驱动截断 (from_iterations)
  context/assembler.py  → ContextAssembler.set_compacted_history()

Agentic 模式 (新增):
  orchestrator/compactor.py → ContextCompactor → LLM 驱动摘要 (compact_if_needed)
```

两者互不引用。Agentic 模式不使用 `CompactedHistory`。如果 agentic 模式稳定后决定废弃 classic，`context/compaction.py` 一并移除。

### 4.2 ExperienceLearner

**文件**: `src/drawagent/orchestrator/learner.py` (新建)

```python
class ExperienceLearner:
    """
    回应审计 #16: ExperienceLearner 与 save_memory 工具的关系:

    - save_memory 工具: LLM 在 turn 中主动调用，写入记忆。
                       格式自由，不强制 reflection 格式。
    - ExperienceLearner.reflect(): 程序在每轮 agentic outer loop 结束后被动触发，
                       调用独立的 LLM reflection，生成结构化经验条目。
                       结果写入 session.learned_lessons。

    两者并存，不互斥:
      - save_memory: LLM 自主记忆 (类似 opencode 的 todowrite 中的 memory)
      - reflect(): 程序保障的反思回路 (强制每轮结束后反思)
    """

    REFLECTION_PROMPT = """Based on the iteration results below, identify concrete lessons:

1. What went wrong or could be improved? (cite specific inspection fails)
2. What strategy worked well? (cite specific prompt techniques or parameter choices)
3. What should be done differently next time?

Output lessons in this exact format, one per line:
LEARNED: <category> | <observation> | <strategy>

Example:
LEARNED: skin_texture | 皮肤质感塑料, inspection 发现 texture_detail FAIL | 在 prompt 中加入"毛孔可见、自然肌肤纹理"，使用侧逆光增强立体感
LEARNED: prompt_style | 描述过于笼统, produced generic image | 用具体材质名词(丝绸、蕾丝、皮革)替代泛化形容词(顺滑、优质)

Iteration context:
{context}"""

    def __init__(self, agent_a: AgentA, config: dict):
        self.agent_a = agent_a
        self.config = config
        self.enabled = config.get("agentic", {}).get("learning", {}).get("enabled", True)
        self.max_lessons = config.get("agentic", {}).get("learning", {}).get("max_lessons", 10)

    async def reflect(self, session: AgenticSession):
        if not self.enabled:
            return
        # 用轻量模型做反思 (可配置, 默认复用 Agent A 模型)
        reflection_model = self.config.get("agentic", {}).get("learning", {}).get("reflection_model")
        response = await self.agent_a.chat(
            model=reflection_model,
            system_prompt="You are a quality analyst.",
            user_prompt=self.REFLECTION_PROMPT.format(context=self._format_context(session)),
        )
        new_lessons = self._parse_lessons(response)
        for lesson in new_lessons:
            if lesson not in session.learned_lessons:
                session.learned_lessons.append(lesson)
        # 保持不超过 max_lessons 条
        if len(session.learned_lessons) > self.max_lessons:
            session.learned_lessons = session.learned_lessons[-self.max_lessons:]

    @staticmethod
    def _parse_lessons(response: str) -> list[str]:
        return [line.removeprefix("LEARNED:").strip()
                for line in response.splitlines()
                if line.upper().startswith("LEARNED:")]

    @staticmethod
    def _format_context(session: AgenticSession) -> str:
        ...  # turns + iterations 摘要
```

### 4.3 ContextCompactor

**文件**: `src/drawagent/orchestrator/compactor.py` (新建)

```python
class ContextCompactor:
    """
    LLM 驱动的上下文压缩。
    替代 classic 的规则驱动 CompactedHistory。

    类比 opencode compactAfterOverflow() / compactIfNeeded():
    - 每次 LLM 调用前检查 token 用量
    - 超限时取旧 turns → LLM 生成摘要 → 存储 Compaction
    - 后续消息历史中: 摘要替换旧 turns

    审计 #8:
    - 用 tiktoken 估算, 不用 // 4
    - 压缩模型可配置 (config.compaction.model) // 不用compaction模型，直接使用主模型进行compaction
    """

    SUMMARY_TEMPLATE = """Summarize the conversation below while preserving:

1. Original user request (exact wording)
2. Key decisions made (prompt changes, parameter choices, inspection strategies)
3. What was tried + what worked + what failed (cite specific inspection results)
4. Any explicit user feedback
5. Current state (what's left to do)

<conversation>
{conversation}
</conversation>"""

    def __init__(self, config: dict):
        ac = config.get("agentic", {}).get("compaction", {})
        self.buffer_tokens = ac.get("buffer_tokens", 20480)
        self.keep_tokens = ac.get("keep_tokens", 8000)
        self.summary_max_tokens = ac.get("summary_max_tokens", 4096)
        self.compaction_model = ac.get("model", "deepseek-v4-flash")
        self.context_window = config.get("agentic", {}).get("context_window", 65536)

    def compact_if_needed(self, session: AgenticSession,
                          system_prompt: str, messages: list[dict],
                          tools: list[dict]) -> bool:
        """返回 True 表示已压缩，调用方应重建上下文"""
        guardrails = SessionGuardrails(config)
        if not guardrails.check_token_budget(system_prompt, messages, tools):
            return False
        # 执行压缩
        ...

    async def _compact(self, session: AgenticSession):
        """取旧 turns, 保留最近 N turns, 压缩旧部分"""
        ...  # 审计 #8: 使用 tiktoken 精确估算
```

### 阶段 4 检查点

- [ ] `ExperienceLearner.reflect()` 产生格式正确的 `LEARNED:` 条目
- [ ] `learned_lessons` 每轮自动追加，不超过 max_lessons
- [ ] `ContextCompactor.compact_if_needed()` 用 tiktoken 估算，中文不误判
- [ ] 压缩后的 Compaction 包含关键决策信息
- [ ] 压缩后 LLM 仍能推理 (e2e 验证)
- [ ] classic `context/compaction.py` 零改动

---

## 阶段 5: WebSocket 事件体系

> **目标**: 引入 agentic 新事件，与 classic 事件双发并行，前端逐步切换
> **策略**: 回应审计 #15 — 每个废弃事件标明过渡行为

### 5.1 事件清单

**文件**: `src/drawagent/main.py` (扩展事件列表 — 在现有列表后追加)

| 新事件 (agentic) | 含义 | 类比 opencode |
|---|---|---|
| `turn.started` | LLM 开始推理 | `step.started` |
| `turn.ended` | LLM 推理结束 (含 finish_reason + finalized flag) | `step.ended` |
| `text.delta` | 流式文本块 | `text.delta` |
| `tool.called` | 工具开始执行 | `tool.called` |
| `tool.completed` | 工具执行成功 | `tool.success` |
| `tool.failed` | 工具执行失败 | `tool.failed` |
| `session.finalized` | LLM 调用了 finalize (含 accepted/rejected/reason) | (无对等) |
| `session.learned` | 新经验条目产生 | (无对等) |
| `session.compacted` | 上下文被压缩 | `compaction.ended` |
| `interrupt.accepted` | 中断消息已入队 | (无对等) |

### 5.2 废弃事件的过渡行为 (回应审计 #15)

| 旧事件 (classic) | 过渡行为 | 移除条件 |
|---|---|---|
| `stage.changed` | **双发**: agentic 模式同时 emit stage.changed (值="agentic")，前端判 `engine==="agentic"` 时不渲染阶段指示器 | 前端全部切新 UI 后移除 |
| `prompt.refined` | **双发**: agentic 模式在 LLM 修改 prompt 后 emit prompt.refined (旧字段) + text.delta + tool.called | 同上 |
| `quality.decision` | **双发**: agentic 模式在 finalize 后 emit quality.decision (旧格式) + session.finalized (新格式) | 同上 |
| `iteration.started` | **保留**: agentic 模式在检测到 generate_image 工具调用时仍 emit (兼容前端迭代卡片) | 前端不再用迭代卡片渲染时移除 |
| `iteration.images_ready` | **保留**: 发图事件与循环模型无关，始终 emit | 长期保留 |
| `inspection.task_done` | **保留**: 检查结果始终 emit | 长期保留 |

### 5.3 前端 FEATURE FLAG

```javascript
// src/drawagent/ui/static/js/app.js

// 页面加载时从 GET /api/sessions 或 WS 首条消息获取 engine
let sessionEngine = "classic";

function onSessionInfo(data) {
    sessionEngine = data.engine || "classic";
    if (sessionEngine === "agentic") {
        enableAgenticUI();
    }
    // classic 模式: UI 行为不变
}

function enableAgenticUI() {
    // 绑定新事件监听
    socket.on("text.delta", renderTextChunk);
    socket.on("tool.called", renderToolCard);
    socket.on("tool.completed", updateToolCard);
    socket.on("session.finalized", renderFinalizeBanner);
    // 解绑/忽略与 agentic 冲突的旧事件
    // stage.changed: 不渲染阶段指示器
    // prompt.refined: 小增量事件覆盖, 不单独渲染卡片
}
```

### 阶段 5 检查点

- [ ] agentic 模式所有新事件正确 emit (日志验证)
- [ ] 废弃事件在 agentic 模式双发 (旧前端不崩)
- [ ] 前端 `sessionEngine === "agentic"` 判定正确
- [ ] classic 模式事件体系零改动

---

## 阶段 6: 前端活动流 UI

> **目标**: 用 OpenCode 风格活动流取代五阶段卡片
> **策略**: 渐进迁移 — agentic 模式启用新 UI，classic 模式保留旧 UI

### 6.1 组件拆分

```
src/drawagent/ui/static/js/
├── app.js              # + sessionEngine 判定, UI 路由
├── api.js              # 不变
├── events.js           # + agentic 事件绑定 (仅在 sessionEngine==="agentic" 时)
├── renderer.js         # 不变 (classic)
├── i18n.js             # + agentic 相关 i18n keys
└── components/         # 新建
    ├── activity-stream.js    # 活动流容器
    ├── turn-item.js          # 单个 turn 条目 (LLM text + tool calls 折叠)
    ├── tool-detail.js        # 工具调用详情 (参数 + 结果, 可折叠)
    ├── image-preview.js      # 图片预览缩略图 + 点击放大
    └── finalize-banner.js    # finalize 结果横幅 (通过/未通过)
```

### 6.2 活动流渲染逻辑

```javascript
// activity-stream.js
class ActivityStream {
    /**
     * 类比 opencode 的对话视图:
     * - 用户消息在左侧, Agent 消息在右侧
     * - 工具调用折叠在 Agent 消息内 (chevron 旋转展开)
     * - 图片缩略图嵌入工具调用结果
     */

    onTurnStarted(data) {
        this.appendItem({ type: "thinking", text: "Agent 正在思考..." });
    }

    onTextDelta(data) {
        this.updateLastItem({ type: "text", text: (current) => current + data.text });
    }

    onToolCalled(data) {
        this.appendItem({
            type: "tool",
            name: data.tool_name,
            args: data.arguments,
            status: "running",
            detailExpanded: false,  // 默认折叠
        });
    }

    onToolCompleted(data) {
        this.updateItem(data.call_id, {
            status: data.status,  // "completed" | "error"
            result: data.result,
        });
    }

    onFinalized(data) {
        this.appendItem({
            type: "finalize",
            accepted: data.accepted_images,
            rejected: data.rejected_images,
            reason: data.reason,
        });
    }

    // 流式追加/更新, 不重建整棵 DOM 树
}
```

### 阶段 6 检查点

- [ ] agentic 模式下活动流正确渲染 turn + tool 序列
- [ ] 工具调用详情折叠/展开 (chevron 旋转动画)
- [ ] 图片缩略图正确嵌入 (复用现有 image-gallery 组件)
- [ ] finalize 横幅显示验收/拒绝结果
- [ ] classic 模式 UI 零改动

---

## 阶段 7: 错误处理 + 配置 + 测试 + 清理

> **目标**: 补充审计指出的 3 个缺失设计点 (#18, #19, #20)

### 7.1 错误处理与恢复 (回应审计 #19)

```python
# orchestrator/agentic_loop.py 中的错误处理:

class AgenticLoop:
    ERROR_RETRY_COUNT = 3

    async def run_agentic_with_recovery(self, ...):
        try:
            return await self.run()
        except LLMAPIError as e:
            await self._handle_llm_error(e)
        except MCPConnectionError as e:
            await self._handle_mcp_error(e)
        except SessionSaveError as e:
            await self._handle_save_error(e)
        except asyncio.CancelledError:
            await self._handle_interruption()

    async def _handle_llm_error(self, error: LLMAPIError):
        """
        LLM API 调用失败:
        1. 重试最多 3 次 (exponential backoff)
        2. 3 次后 → 标记 Turn.finish_reason = "error"
        3. 通过 WS 通知用户: "Agent A API 调用失败，已重试 3 次"
        4. 保存部分结果, 不丢弃整个 session
        """
        self.session.errors.append({
            "type": "llm_api",
            "message": str(error),
            "turn_index": len(self.session.turns),
            "timestamp": datetime.now().isoformat()
        })
        await self.event_bus.emit("error.llm_api", { ... })

    async def _handle_mcp_error(self, error: MCPConnectionError):
        """
        Agent B MCP 断连:
        1. 通过 system message 告知 LLM: generate_image 暂时不可用
        2. 重试连接 3 次
        3. 仍失败 → 标记工具为 unavailable, 让 LLM 知道只能做文本操作
        """
        ...
```

### 7.2 配置文件完整 Schema (回应审计 #18)

```yaml
# config.yaml 完整新增节

loop:
  engine: "classic"  # "classic" | "agentic"

  agentic:
    # --- Loop control ---
    max_tool_rounds: 10
    max_agentic_rounds: 20
    max_finalize_rejections: 3

    # --- Context ---
    context_window: 65536
    output_buffer: 8192

    # --- Compaction ---
    compaction:
      enabled: true
      buffer_tokens: 20480
      keep_tokens: 8000
      summary_max_tokens: 4096
      model: "deepseek-v4-flash"

    # --- Learning ---
    learning:
      enabled: true
      max_lessons: 10
      reflection_model: "deepseek-v4-flash"

    # --- Guardrails ---
    guardrails:
      empty_response_threshold: 3   # 连续空回复上限
      no_image_threshold: 3         # 连续无 generate_image 调用上限
      llm_retry_count: 3
      mcp_retry_count: 3
      session_idle_minutes: 30      # 无用户输入超时
```

### 7.3 测试策略 (回应审计 #20)

```
tests/agentic/
├── test_agentic_session.py     # 阶段 1: 数据模型往返测试
├── test_agentic_loop.py        # 阶段 2: 核心循环 mock 测试
│   ├── test_basic_flow         # queue → LLM → finalize → done
│   ├── test_tool_chain         # load_memory → generate → inspect → finalize
│   ├── test_steer_injection    # 中途 steer → LLM 调整 → finalize
│   ├── test_finalize_rejected  # finalize 被拒 3 次 → 停止死循环
│   ├── test_force_finalize     # tool round 超限 → 强制 finalize
│   └── test_continuation_check # _needs_continuation_check 各种分支
├── test_tool_registry.py       # 阶段 3: materialize_all() 返回全部工具
├── test_compactor.py           # 阶段 4: token 估算, compact 触发, 中文准确性
├── test_learner.py             # 阶段 4: LEARNED 解析, max_lessons 截断
├── test_events.py              # 阶段 5: 新旧事件双发验证
└── test_e2e_agentic.py         # 端到端: 真实 LLM + MCP (手动触发, CI 可选)
```

### 7.4 清理计划

Agentic 模式稳定后 (所有 P0-P1 完成 + 1 周无 bug):
1. `config.yaml` 默认 `loop.engine` 改为 `"agentic"`
2. 移除 `orchestrator/loop.py` (五阶段)
3. 移除 `context/compaction.py` (规则驱动 Compression)
4. 移除 `core/types.py:Session` 中的 `state`, `interrupt_event`, `pending_action`, `steer_message`
5. 移除前端五阶段卡片 UI
6. 移除 feature flag `sessionEngine === "agentic"` 判定 (始终 true)

---

## 实施顺序 (回应审计 #310)

```
阶段 0: 数据库 Schema + 配置扩展 (1天)
  ↓
阶段 1: AgenticSession 数据模型 (1-2天)
  ↓
阶段 2+3+7 并行: Agent 循环 + 工具解耦 + Guardrails (3-5天)
  ↓
阶段 4: 经验积累 + 上下文压缩 (2-3天)
  ↓
阶段 5: WebSocket 事件双发 (1-2天)
  ↓
阶段 6: 前端活动流 UI (2-3天)
```

## 文件隔离对照表

| 新增/修改 | 文件 | 阶段 |
|-----------|------|------|
| 新增 | `models/agentic_session.py` | 1 |
| 新增 | `orchestrator/agentic_loop.py` | 2 |
| 新增 | `orchestrator/context_builder.py` | 2 |
| 新增 | `orchestrator/compactor.py` | 4 |
| 新增 | `orchestrator/learner.py` | 4 |
| 新增 | `orchestrator/guardrails.py` | 2 |
| 新增 | `orchestrator/steer_controller.py` | 3 |
| 新增 | `tools/finalize.py` | 2 |
| 新增 | `tools/memory.py` | 2 |
| 修改 (增量) | `orchestrator/server_runner.py` | 2 |
| 修改 (增量) | `agents/agent_a.py` | 2 |
| 修改 (增量) | `tools/base.py` | 2 |
| 修改 (增量) | `main.py` | 5 |
| 不动 | `core/types.py` | — |
| 不动 | `orchestrator/loop.py` | — |
| 不动 | `orchestrator/session.py` (扩展新方法) | 0 |
| 不动 | `orchestrator/interrupt.py` | — |
| 不动 | `context/compaction.py` | — |
| 不动 | `context/assembler.py` | — |
