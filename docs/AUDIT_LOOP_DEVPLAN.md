# Audit: LOOP_DEVPLAN.md

> 基于对现有代码 (loop.py, session.py, agent_a.py, compaction.py, interrupt.py, types.py, assembler.py, tools/) 的审查，对 LOOP_DEVPLAN.md 的逐阶段意见与问题。

---

## 总体评价

方案思路清晰，将 opencode 的 LLM 驱动循环思想映射到 DrawAgent 是正确的方向。但存在 **4 个与现有代码冲突的严重问题** 和若干中低风险的设计缺陷，需要在实施前解决。

---

## 严重问题 (必须在 Coding 前解决)

### 1. Session 模型双重定义冲突

**位置**: 阶段 1.1 新建 `models/session.py`，定义了新的 `@dataclass Session`

**现状**: `src/drawagent/core/types.py:70` 已有 `Session` dataclass，被 `loop.py`、`session.py`、`agent_a.py`、`assembler.py` 等 10+ 个文件引用。

**冲突**:
- 新 `Session` 多了 `messages`, `turns`, `compactions`, `learned_lessons`, `errors`
- 旧 `Session` 有 `state`, `interrupt_event`, `pending_action`, `steer_message`, `max_iterations`, `loaded_memories`
- 两套字段几乎没有交集——两个模型 **互不兼容**，无法简单合并

**问题**: 方案只提到 `iterations` 保留向后兼容，但完全没有说明 `interrupt_event`、`pending_action`、`steer_message`、`state` 这 4 个当前被 `loop.py` 和 `session.py` 重度依赖的字段如何处理。如果新 runner 不用它们，那在什么时候、以什么方式移除？

**建议**: 明确采用 "新模型 + 适配层" 模式：
- 新 `Session` 作为 `models/session.py` 的纯数据模型
- 旧 `core/types.py` 的 `Session` 保留为旧 runner 专用
- 适配层 `to_legacy()` / `from_legacy()` 不应只处理 `iterations`，还应处理 `interrupt_event`、`max_iterations` 等

---

### 2. 文件命名冲突: 阶段 2.4 `orchestrator/interrupt.py` 已存在

**位置**: 方案 2.4 新建 `src/drawagent/orchestrator/interrupt.py`

**现状**: `src/drawagent/orchestrator/interrupt.py:6` 已有 `InterruptHandler` 类，被 `loop.py` 引用。

**冲突**:
- 现有: `InterruptHandler` (async, action-based, `handle(session, action, data)`)
- 新设计: `InterruptController` (sync, `threading.Event`-based, `interrupt(session_id, message)`)

两个类设计思路完全不同，且共享同一个文件路径。不能既"新建"又"保留"该文件。

**建议**: 新中断控制器命名为 `orchestrator/interrupt_v2.py` 或 `orchestrator/steer_controller.py`。或者直接在现有 `InterruptHandler` 的基础上扩展 steer/queue 消息能力。

---

### 3. Threading.Event 与 Async 混用

**位置**: 阶段 2.4 `InterruptController.__init__` 用 `threading.Event`

**现状**: 整个代码库是 async/await 架构 (`loop.py` 使用 `asyncio.Event`、`asyncio.wait_for`)

**问题**: `threading.Event` 阻塞的是 OS 线程，在 asyncio 事件循环中调用 `.set()` 和 `.wait()` 会导致上下文不一致。虽然 Python 中两者可以混用（threading.Event 不会阻塞 event loop），但在设计层面不应混用两种并发模型。

**建议**: 统一使用 `asyncio.Event`，或者如果需要在同步上下文中触发中断，使用 `asyncio.run_coroutine_threadsafe()` 桥接。

---

### 4. 阶段 3 ToolRegistry 与现有实现冲突

**位置**: 阶段 3.1 新建 `tools/registry.py` 定义 `ToolRegistry`

**现状**: `src/drawagent/tools/base.py` 已有 `ToolRegistry` 类，被 `agent_a.py:82` 的 `run_turn()` 通过 `self.registry.materialize(enabled_tools)` 调用。

**关键差异**:
- 现有: `materialize(enabled_tools: set[str] | None)` — 过滤工具
- 新设计: `materialize(session: Session)` — 不过滤，全部返回

**问题**: 方案的 "移除 `enabled_tools` 概念" 只需要修改现有 `materialize()` 方法去掉过滤逻辑即可，不需要新写一个类。新注册中心也缺少 `BaseTool` 的注册方式（现有的 `ToolRegistry.register()` 接受 `BaseTool` 实例，新的是 `register(name, schema, executor)`）。

**建议**: 不要新建 `registry.py`，直接在现有 `tools/base.py` 的 `ToolRegistry` 上修改：
- `materialize()` 去掉 `enabled_tools` 参数
- 增加 `materialize_all()` 方法保持旧代码不受影响
- `register()` 保持 `BaseTool` 接口（现有 3 个工具继承自 `BaseTool`，重写 executor 格式成本太高）

---

## 中风险设计问题

### 5. `_check_if_really_done()` 逻辑有误

**位置**: 阶段 2.3 runner_loop.py L617-637

```python
def _check_if_really_done(session, turn, event_bus) -> bool:
    if not session.iterations:
        return False  # 还没生成过图片，不能结束
    last_iter = session.iterations[-1]
    has_images = bool(last_iter.images)
    has_inspections = bool(last_iter.inspections)

    if not has_images:
        return True  # 追问它   ← 注释说"追问"，但函数名是 check_if_really_done
    return False  # 有图片 + LLM 说完成 = 真正完成
```

**问题**:
1. 返回值语义模糊 — `False` 在有些分支表示 "不能结束"（L627），在 L637 表示 "真正完成"。调用方用 `needs_continuation = _check_if_really_done(...)` 来赋值，但函数名暗示返回的是"是否真的完成了"，而调用方期待的是"是否需要继续"——这两者是相反的。
2. L633 `has_inspections` 变量定义了但从未使用。
3. 缺少对 LLM 空回复 + 无图片场景的处理 — 应该返回 `True`（需要继续追问）而不是 `False`（不能结束，但也没继续）。

**建议**: 重命名为 `_needs_continuation_check()` 或明确返回 `needs_continuation: bool`，并在每个分支加注释。

---

### 6. InputQueue 的生命周期与填充

**位置**: 阶段 1.4 `InputQueue` + 阶段 2.3 `run_session()` 中 `queue = InputQueue()` 是局部变量

**问题**: `run_session()` 每次调用创建一个**新的空队列**，但用户中断消息是从 WebSocket 发来的，需要跨请求到达。当前方案中 `InputQueue.admit()` 的调用者是谁没有说明——是 WebSocket handler 直接调 `InputQueue` 实例吗？那它怎么拿到 `run_session()` 内部创建的那个实例？

**建议**: `InputQueue` 应该是 `SessionRunner` 的属性或全局单例，由 WebSocket handler 持有引用。或者采用类似现有 `session.pending_action` 的方式，将 steer 消息暂存在 Session 对象上，循环每次都检查。

---

### 7. SessionStore (JSON) vs SessionManager (SQLite)

**位置**: 阶段 1.3 新建 `SessionStore` 用 JSON 持久化

**现状**: `SessionManager`（`orchestrator/session.py`）通过 `Database` 用 SQLite 持久化（有 `persist_session()`, `add_iteration()`, `load_all()`, `load_session()`）

**问题**: 方案没有说明：
- 新的 JSON SessionStore 是否要替代现有 SQLite？
- 如果替代： `iterations` 中的 `ImageRecord`、`InspectionTaskResult`、`QualityDecision` 如何序列化到 JSON？
- 如果不替代：两个持久化层如何共存？数据一致性问题？
- `SessionStore.append_message()` 和 `append_turn()` 的"原子追加"在 JSON 文件上如何实现（无事务保证）？

**建议**: 明确表态——要么 JSON 保留为仅用于开发调试（类似现有 `temp/` 目录的 session dump），SQLite 继续做主存储；要么 SQLite 在新模型下扩展新表（`turns`, `messages`, `compactions`），JSON 仅为导出格式。

---

### 8. Compaction 已有实现，但方案完全不同

**位置**: 阶段 4.2 新建 `ContextCompactor`

**现状**: `src/drawagent/context/compaction.py` 已有 `CompactedHistory` 类，`from_iterations()` 是**规则驱动**的（直接截取文本前缀），不调 LLM。

**方案的新设计**: 将 old turns 发送给轻量级 LLM 生成摘要，用 token 估算触发。

**问题**:
1. 新 `ContextCompactor` 是一个完全不同的实现路径，但方案没有提及现有的 `CompactedHistory` 和 `ContextAssembler.set_compacted_history()` 是否废弃。
2. `_estimate_tokens()` 用 `len(text) // 4` 估算，对中文文本误差很大（中文 1 字 ≈ 1.5-2 token）。
3. `_call_compaction_llm()` 调用的模型是谁？轻量级 LLM 在当前的配置系统中是否可配置？方案未指定。

**建议**: 
- 在 4.2 开头明确说明与现有 `CompactedHistory` 的关系（替代？共存？）
- Token 估算用 `tiktoken` 或 provider 的 tokenizer，不要用 `// 4`
- 压缩 LLM 应该是可配置的（config 中新增 `compaction_model` 字段）

---

### 9. AgentA.run_turn() 已有的 tool chaining 未提及

**位置**: 阶段 2.3 的 `_llm_call_with_tools()` 是新实现

**现状**: `agent_a.py:154-179` 已经有 `MAX_TOOL_ROUNDS = 4` 的 tool chaining 循环。它处理 `load_memory → generate_image` 这类多轮工具链。

**问题**: `_llm_call_with_tools()` 是一个**平替**实现，完全绕过了 `AgentA.run_turn()`。但方案没有说是否要废弃 `run_turn()` 的 tool chaining，还是两个都保留。如果是平替，是否意味着新的 runner 不经过 `AgentA`？

**建议**: 明确 `_llm_call_with_tools()` 是作为 `AgentA` 的新能力 还是 替代 `AgentA`。如果替代，应该在阶段 2 中说明 `AgentA.run_turn()` 的废弃计划。

---

### 10. 缺少数据库迁移方案

**现状**: 现有 SQLite 数据库有 `sessions`, `iterations`, `images`, `inspections` 四张表。

**需要新增**: `turns`, `tool_calls`, `tool_results`, `messages`, `compactions`, `learned_lessons` 至少 6 张表。

**问题**: 整个方案没有提到数据库 schema 变更。7 个阶段没有一个包含 migration 脚本或 DB schema 设计。

**建议**: 增加一个"阶段 0: 数据库 schema 升级"，包含：
- 新表的 DDL
- 旧数据到新模型的迁移脚本（至少把 `sessions.user_request` 转为 `messages[0]`）
- 向后兼容查询（确保 Web UI API 返回格式不变）

---

## 低风险/细节问题

### 11. `_build_state_summary()` 引用了未定义的函数

**位置**: 阶段 2.2 L312-316

```python
if session.iterations:
    last = session.iterations[-1]
    lines.append(f"- Last iteration quality: {_format_decision(last)}")
    issues = _extract_issues(last)
```

`_format_decision()` 和 `_extract_issues()` 在方案中没有定义。如果 `last` 是 `Iteration` 对象，应该访问 `last.decision.passed` 和 `last.decision.remaining_issues`。

---

### 12. `run_session()` 中 Turn 的 `user_message` 可能为 None

**位置**: 阶段 2.3 L439

```python
turn = Turn(
    user_message=session.turns[-1].user_message if session.turns else None,
    ...
)
```

`Turn.user_message` 类型标注为 `UserMessage`（非 Optional），但在 session 初始无 turn 时传入 `None`。这会在 `build_messages()` 的 L343 `turn.user_message.text` 处 crash。第一次 run_turn 时应该从 InputQueue 的 promote 结果中创建 `UserMessage`。

---

### 13. `_llm_call_with_tools()` 中 `finalized` 变量未声明

**位置**: 阶段 2.3 L584

```python
if tcb.name == "finalize":
    result_data = finalize_images(**tc_record.arguments)
    finalized = True  # ← 函数顶层没有初始化
```

`finalized` 在 for 循环外被引用为 `LLMResult(finalized=...)`。如果 LLM 没调 finalize，`finalized` 是 `NameError`。应该在 for 循环外初始化为 `False`。

---

### 14. Tool schema 文件结构中的 `schemas.py` 与 PITFALLS.md 原则可能矛盾

**位置**: 阶段 3.2 文件结构

PITFALLS.md 说 "MCP server 的 TOOL_SCHEMA 是模型侧的 truth——客户端不应硬编码重复信息"。但 `schemas.py` 似乎是要在客户端硬编码所有工具 schema？如果 `generate_image` 的参数由 MCP server 动态提供，`GENERATE_IMAGE_SCHEMA` 应该从 MCP server 的 `TOOL_SCHEMA` 读取而非硬编码。

**建议**: 阶段 3.2 新增的文件中，`schemas.py` 应标注哪些工具是 MCP-proxied（schema 来源是 MCP 而非本地）、哪些是纯客户端工具（如 `finalize`）。

---

### 15. WebSocket 事件迁移路径不够清晰

**位置**: 阶段 5.2 旧事件处理方式

| 旧事件 | 处理方式 |
|--------|----------|
| `quality.decision` | 废弃，改为 `session.finalized` |
| `stage.changed` | 废弃，前端改用 `turn.*` 事件 |
| `prompt.refined` | 废弃，前端用小增量事件展示 |

**问题**: 这三行说了"废弃"但没有说"废弃时的具体行为"：
- `quality.decision` 废弃 → 在哪里拦截？如果旧 loop 还存在，这个事件仍然需要 emit
- `stage.changed` 废弃 → 前端目前依赖它来高亮当前 phase。过渡期如何避免 UI 闪烁？
- `prompt.refined` 废弃 → 新的 prompt 变更通过什么事件传递？（`text.delta` 不包含结构化信息）

**建议**: 每个"废弃"事件应增加一列"过渡行为"，如 `quality.decision → session.finalized`: "emit 新旧事件双发，前端用 `supports_v2_events` flag 判断消费哪个，1-2 周后移除旧事件 emit"

---

### 16. 阶段 4.1 `ExperienceLearner` 与 `save_memory` 工具的关系不明确

**位置**: 阶段 4.1 vs 阶段 3.2

阶段 3.2 的工具列表中有 `save_memory / load_memory / search_memory` 但阶段 4.1 的 `ExperienceLearner.reflect()` 是**程序主动触发**一个独立 LLM 调用来生成 lessons。而 LOOP_DESIGN.md 中说的是 "LLM 调用 `save_memory` 写入经验"。

**问题**: 到底经验是 LLM 主动调用 `save_memory` 工具写入，还是程序在每轮结束后调用 `ExperienceLearner.reflect()` 来生成？两者不是互斥的，但方案没说它们如何协作。

---

### 17. 阶段 7 Guardrails 缺少对 "LLM 重复调 finalize 被拒绝后又停止" 的处理

**位置**: 阶段 7.1

`max_tool_rounds` 到达上限后 "强行 finalize"，但如果 LLM 调用 finalize 后程序检测到上一轮 inspection 中有 FAIL（类似 LOOP_DESIGN 场景 3），程序拒绝 finalize。这时 LLM 可能陷入：
- finalize 被拒绝 → 返回 text 说 "我完成了"
- 程序检测到没有 finalize → 追问 → LLM 再 finalize → 再被拒绝 → 死循环

**建议**: 增加 guardrail: "连续 3 次 finalize 被拒绝 → 注入 system 消息告知 LLM 具体未解决的问题 → 要求 LLM 不要 finalize 直到解决"

---

## 缺失的设计要点

### 18. 缺少配置文件变更设计

方案在末尾提到了 `config.yaml` 的 `loop.engine` feature flag，但没有说明：
- 新配置项的完整 schema（`model_hints` 移至哪个节点？`compaction_model` 配置？`context_window` 配置？）
- 旧 runner 的配置项（`max_iterations`, `keep_recent_iterations`, `compaction_threshold_tokens`）哪些被复用、哪些被移除
- `AgentBConfig` 在新架构中的位置变化

---

### 19. 缺少错误处理与恢复设计

方案没有提到：
- LLM API 调用失败时，`Turn` 的状态怎么标记？（现有 `ToolCallRecord.status = "error"`，但 Turn 整体没有 error 状态）
- session 保存到一半崩溃怎么恢复？（JSON 写入无事务保证，不像 SQLite 有 journal）
- 工具执行失败（如 MCP 断连）后 LLM 是否被告知该工具暂时不可用？

---

### 20. 缺少测试策略

方案说 "每阶段可独立完成、测试、提交" 但 7 个阶段的检查点中，只有阶段 1 明确提到 "单元测试"。阶段 2 说 "e2e_run.py 跑通完整流程" 但这不够。建议至少：
- 阶段 2: `run_session()` 的 mock 测试（mock LLM 返回一系列 tool_calls 然后 finalize）
- 阶段 4: `ContextCompactor` 的 token 估算准确性测试
- 阶段 5: WebSocket 事件的集成测试

---

## 实施顺序优化建议

当前顺序：1 → 2 → 3 → 4 → 5 → 6 → 7

建议增加的并行度：
- 阶段 7 (Guardrails) 可与阶段 2 一起实施（是 runner_loop 的内嵌逻辑）
- 阶段 3 (工具解耦) 可与阶段 2 合并（runner_loop 需要从 registry 获取工具，解耦是循环的前提）
- 阶段 1 的工作量预估偏低（涉及 DB migration + API 兼容 + 旧代码适配，不只是"新建一个 dataclass"）

**建议顺序**: 1 → (2+3+7 并行) → 4 → 5 → 6

---

## 总结

| 类别 | 数量 |
|------|------|
| 严重冲突（必须解决） | 4 |
| 中风险设计问题 | 6 |
| 低风险细节 | 7 |
| 缺失设计要点 | 3 |

**最大的三个风险**:
1. `Session` 数据模型与现有 10+ 文件的兼容性——一旦改坏，整个系统挂掉
2. `runner_loop.py` 绕过了 `AgentA` 和 `ContextAssembler` ——这两块是之前踩坑修了很久的代码（PITFALLS #5 system prompt 注入、#6 逐张检查耗时），新实现是否继承了它们的经验？
3. JSON 持久化替代 SQLite 的去留——如果决定切 JSON，需要接受无事务保证的后果；如果保留 SQLite，阶段 1 的 `SessionStore` 需要重新设计
