# DrawAgent — 图像生成 Agent 系统设计文档 v2.1

## 目录

1. [概述与目标](#1-概述与目标)
2. [核心设计理念](#2-核心设计理念)
   - 2.1 [Anthropic 的三大 Agent 设计原则](#21-anthropic-的三大-agent-设计原则)
   - 2.2 [Anthropic 定义的六种 Agentic Workflow 模式](#22-anthropic-定义的六种-agentic-workflow-模式)
   - 2.3 [深入参考 OpenCode 的设计思想](#23-深入参考-opencode-的设计思想)
3. [系统架构](#3-系统架构)
4. [Agent Loop 设计（核心）](#4-agent-loop-设计核心)
   - 4.1 [双层循环架构](#41-双层循环架构)
   - 4.2 [状态机设计](#42-状态机设计)
   - 4.3 [Inner Loop 详细流程](#43-inner-loop-详细流程)
   - 4.4 [提示词分解策略](#44-提示词分解策略)
   - 4.5 [种子管理策略](#45-种子管理策略)
   - 4.6 [循环终止策略](#46-循环终止策略)
   - 4.7 [事件驱动设计](#47-事件驱动设计)
5. [Agent 定义](#5-agent-定义)
   - 5.1 [Agent A: 主控 LLM — 画图总监](#51-agent-a-主控-llm--画图总监)
   - 5.2 [Agent B: 图像生成器](#52-agent-b-图像生成器)
   - 5.3 [Agent C: 多模态视觉观察者](#53-agent-c-多模态视觉观察者)
6. [工具系统](#6-工具系统)
7. [上下文管理](#7-上下文管理)
8. [用户中断与控制](#8-用户中断与控制)
9. [配置系统](#9-配置系统)
10. [记忆模块（Memory）](#10-记忆模块memory)
    - 10.1 [记忆的定位与目标](#101-记忆的定位与目标)
    - 10.2 [记忆目录结构](#102-记忆目录结构)
    - 10.3 [记忆索引](#103-记忆索引-indexmd)
    - 10.4 [提示词记忆条目格式](#104-提示词记忆条目格式)
    - 10.5 [检查项记忆格式](#105-检查项记忆格式)
    - 10.6 [记忆与 Agent Loop 的集成](#106-记忆与-agent-loop-的集成)
    - 10.7 [记忆工具定义](#107-记忆工具定义)
    - 10.8 [Agent A 的记忆使用指南](#108-agent-a-的记忆使用指南system-prompt-注入)
    - 10.9 [记忆加载的上下文管理](#109-记忆加载的上下文管理)
    - 10.10 [记忆分类的自动演化](#1010-记忆分类的自动演化)
    - 10.11 [与未来扩展的衔接](#1011-与未来扩展的衔接)
    - 10.12 [Session 数据持久化](#1012-session-数据持久化)
    - 10.13 [持久化文件布局](#1013-持久化文件布局)
11. [UI 设计](#11-ui-设计)
12. [未来扩展计划](#12-未来扩展计划)
13. [待讨论问题与已决策事项](#13-待讨论问题与已决策事项)
14. [参考](#14-参考)

---

## 1. 概述与目标

### 问题描述

当前图像生成存在以下痛点：
1. **提示词难写**：用户不知道如何精确描述想要的图像
2. **提示词不可复用**：不同模型对提示词理解不同，提示词无法跨模型迁移
3. **等待时间太长**：生成需要反复调整提示词，用户花大量时间坐在电脑前等待

### 解决方案

构建一个三 Agent 协作的智能画图系统：

```
用户 → [Agent A: 主控LLM] → [Agent B: 文生图模型] → 图片
                                ↑
         [Agent C: 多模态视觉] ──┘ (看图反馈)
```

**核心思路**：用户只需用自然语言说出"想要什么样的图"，Agent A 负责将其转化为专业提示词、控制 B 生成、调用 C 审核，自动迭代优化，直到满意才交付给用户。

### 设计目标

| 目标 | 说明 |
|------|------|
| **降低门槛** | 用户用自然语言描述即可，无需学习提示词工程 |
| **自动化迭代** | 自动生成→审核→修正循环，减少人工等待 |
| **用户完全可控** | 任何时刻可中断、修改方向、提前终止 |
| **配置灵活** | A/B/C 可自由配置模型（本地/API），参数可调 |
| **可扩展** | 预留 MCP、Skills、插件等扩展接口 |
| **可观测** | 所有中间步骤可见，便于调试和优化 |

---

## 2. 核心设计理念

### 2.1 Anthropic 的三大 Agent 设计原则

在 Anthropic 与数十个团队合作构建 LLM Agent 的经验中，最成功的实现都遵循三条核心原则：

1. **保持简单 (Simplicity)**：从最简单的方案开始（往往就是单次 LLM 调用 + 好的 prompt），只在简单方案确实不够用时才增加复杂度。每增加一层抽象都应该有明确的、可测量的收益。

2. **透明性 (Transparency)**：显式展示 Agent 的规划步骤和决策理由。用户应该能看到 Agent "在想什么"——为什么选择了这个提示词、为什么认为某张图不通过、下一步打算怎么改进。这对建立用户信任至关重要。

3. **精心设计 Agent-Computer Interface (ACI)**：LLM 调用工具的方式和人类操作 UI 同等重要。工具的命名、参数设计、返回值格式、边界条件处理，直接影响 Agent 的可靠性和成功率。工具设计投入的时间应该不亚于 prompt 设计。

### 2.2 Anthropic 定义的六种 Agentic Workflow 模式

Anthropic 将 Agentic System 分为两大类——**Workflows**（流程通过预定代码路径编排）和 **Agents**（LLM 动态决定自身流程）——并总结了六种常见模式。本节列出全部六种，并分析哪些适用于 DrawAgent。

---

#### 模式一：Prompt Chaining（提示词链式调用）

```
Input → [LLM Call 1] → output_1 → [Gate/Check] → [LLM Call 2] → output_2 → ...
```

**思想**：将复杂任务分解为固定顺序的子任务，每个 LLM 调用处理前一步的输出。中间可插入程序化检查点（Gate）验证上一步结果。

**适用场景**：任务可以被干净地分解为独立的顺序步骤；每个步骤的输出是下一步的输入；步骤之间有明确的质量标准可以程序化验证。

**在 DrawAgent 中的体现**：
- Agent A 的"需求分析 → 提示词撰写"实际上是内部的 Prompt Chaining：先理解用户需求（内部思考），再产出提示词。
- 整个外层流程也可以视为链式：`用户输入 → A 分析需求 → A 产出 prompt → B 生成 → C 审核 → A 判断 → 交付或迭代`。但因为有循环回退，这更像 Evaluator-Optimizer。

---

#### 模式二：Routing（路由分发）

```
Input → [Classifier/LLM] ──→ [Specialized Handler A]
                          ├─→ [Specialized Handler B]
                          └─→ [Specialized Handler C]
```

**思想**：对输入进行分类，然后将请求路由到专门处理该类请求的下游流程。不同类别可以有不同的 prompt、工具甚至模型。

**适用场景**：任务有明显不同的类别，分类可以准确完成；不同类别需要完全不同的处理逻辑；可以用更便宜/更小的模型处理简单类别，更大的模型处理复杂类别。

**在 DrawAgent 中的体现（未来）**：
- 可以路由不同的生成需求到不同的 Agent B 实例：人像用 SD3，风景用 Flux，动漫用 Niji。
- 可以路由不同的审核需求到不同强度的 Agent C：简单场景用便宜的视觉模型，复杂场景用更强的。

---

#### 模式三：Parallelization（并行化）

```
Input → [Task Decomposition]
           ├─→ [LLM Call A] ──┐
           ├─→ [LLM Call B] ──┼─→ [Aggregation] → Output
           └─→ [LLM Call C] ──┘
```

**思想**：将任务拆分为可并行的子任务，同时执行。有两个子变体：
- **Sectioning（分段并行）**：不同子任务处理不同方面（如一个检查安全，一个检查语法）
- **Voting（投票并行）**：同一任务运行多次，综合多个结果以提升置信度

**适用场景**：子任务之间无依赖关系；需要多个视角或多次尝试提高准确性；延迟敏感，并行可加速。

**在 DrawAgent 中的体现**：
- **核心用法**：同一 prompt 同时生成多张图（B 并行调用），然后 A 从中选出最好的继续优化。这比串联生成（一张一张来）更高效。
- **Voting 变体**：对关键的质量判断，可以用多个 C 调用（或同一 C 多次调用）交叉验证，减少单一视觉模型判断失误的风险。
- **未来用法**：同时生成多个风格变体让用户选择。

---

#### 模式四：Orchestrator-Workers（编排-工人模式）

```
Input → [Orchestrator LLM] ─→ [Worker Task A] ──┐
                             ├─→ [Worker Task B] ──┼─→ [Orchestrator synthesizes]
                             └─→ [Worker Task C] ──┘
```

**思想**：一个中央 LLM（Orchestrator）动态拆分任务，分配给多个 Worker LLM，然后综合他们的结果。与 Parallelization 的关键区别：子任务不是预先定义的，而是由 Orchestrator 根据具体输入动态决定的。

**适用场景**：无法提前预测需要哪些子任务；子任务的数量和性质因输入而异；需要动态判断。

**在 DrawAgent 中的体现（未来）**：
- 复杂场景（如"画一个奇幻城市场景，要有城堡、市场、天空中有龙"）：A 可以拆分为子任务——一个 Worker 负责建筑设计，一个负责角色设计，一个负责氛围——各自生成参考图，A 综合后形成统一 prompt。
- 角色设计 + 场景设计 + 道具设计的并行开发。

---

#### 模式五：Evaluator-Optimizer（评估器-优化器循环）

```
Generator → produces output → Evaluator checks it
    ↑                              ↓
    └── feedback + suggestions ←───┘  (loop until satisfied)
```

**思想**：一个 LLM 生成内容，另一个 LLM 提供评估和反馈，循环迭代直到满足质量标准。这类似于人类写作中的"写 → 审阅 → 修改"过程。

**适用场景（两个关键信号）**：
1. 当人类给出反馈后，LLM 的产出可以得到明显改善（说明 LLM 能够利用反馈）
2. LLM 本身能够提供有意义的反馈（说明 LLM 具备评估能力）

**这是 DrawAgent 的核心模式**：
```
Agent A (Generator/Optimizer) → 给出提示词 → Agent B → 生成图像
       ↑                                              ↓
       └── 观察结果 + 修改决策 ←── Agent C (Observer) ←─┘  (loop)
```

**为什么选中这个模式**：
- 图像生成的质量标准是明确的（元素齐全、风格匹配、无伪影）
- 多模态 LLM 能有效描述图像内容（"看"的能力）
- 文本 LLM 能够将描述性问题转化为提示词修改（"改"的能力）
- 迭代改进带来可测量的质量提升
- 这个模式与人类艺术总监的工作流高度相似："画 → 看 → 指出问题 → 改 → 再画"

**关键设计选择**：在本系统中，Evaluator 的角色不是单一 Agent C，而是 **A 主导 + C 辅助**。A 是质量负责人，C 是 A 的"眼睛"——A 指挥 C 去看什么、检查什么，A 综合 C 的观察做出质量判断。详见 [5.1 节](#51-agent-a-的质量控制角色)。

---

#### 模式六：Autonomous Agent（自主 Agent）

```
User Command → [Agent]
                 ├─ Plan (determine steps)
                 ├─ Execute Step (use tools)
                 ├─ Observe Result (environment feedback)
                 ├─ Evaluate Progress
                 ├─ (optionally) Ask Human for guidance
                 └─ Loop until done or blocked
```

**思想**：Agent 接收用户指令后，自主规划、使用工具、根据环境反馈调整、在检查点暂停等待人工确认。Agent 从头到尾掌控执行过程。

**适用场景**：开放性问题，无法预测需要多少步骤；无法硬编码固定路径；需要信任 LLM 的决策能力；环境反馈可以用来自动纠错。

**与 DrawAgent 的关系**：
- DrawAgent 本质上介于 **Evaluator-Optimizer Workflow** 和 **Autonomous Agent** 之间。
- 它比纯 Workflow 更"自主"——A 可以决定迭代多少次、何时问用户、何时放弃、如何修改提示词。
- 它比纯 Agent 更"受控"——用户可以在任何时刻干预，循环有明确的范围（只做图像生成迭代），A 不会去做搜索网页、写代码等无关操作。
- 可以理解为：**受约束的自主 Agent**，自主范围限定在图像生成优化领域。

---

#### 六种模式的联合使用（复合模式）

真实系统中往往组合多种模式。例如 DrawAgent 组合了：

```
Evaluator-Optimizer (核心循环)
  + Parallelization (同 prompt 多图并行生成)
  + Prompt Chaining (需求分析→提示词→参数选择 是内部链式)
  + Routing (未来：不同场景路由到不同画图模型)
  → 形成一个受约束的 Autonomous Agent
```

---

### 2.3 深入参考 OpenCode 的设计思想

OpenCode 作为一个成熟的生产级 Agent 框架，其架构中有许多设计思想可以借鉴。本节不简单列表映射，而是深入解释每个设计点背后的**为什么**，以及 DrawAgent 如何**适配**它。

---

#### 2.3.1 双层循环架构：解耦用户交互与 Agent 执行

**OpenCode 的设计**：

```
SessionExecution.resume(sessionID)
  → SessionRunCoordinator.drain(key)
    → 外层: while has_pending_inputs:
        promote_input_to_queue()      # 用户输入/steer 排队
        → 内层: while needs_continuation:
            runTurn()                 # 单次 LLM turn (可能含工具调用)
            check_for_new_steers()    # 每个 turn 后检查中断
```

**为什么这样设计**：用户可能在上一个 Agent turn 还在执行时就发来新消息或中断指令。外层循环负责**排队和优先级**（用户中断 > 正常输入），内层循环负责**一个完整推理回合**（LLM 思考 → 工具调用 → LLM 再思考 → ...）。

**DrawAgent 的适配**：

```
DrawSession.resume(session_id)
  → 外层: while session_is_alive:
      await user_input_queue()        # 等待用户输入或中断
      → 内层: while not_satisfied:
          iteration = (prompt_refine → generate → inspect → evaluate)
          if interrupt_pending: break # 每个 iteration 后检查
```

**关键差异**：OpenCode 的内层循环是 LLM 自主驱动的（LLM 决定何时调用工具、何时停止），而 DrawAgent 的内层循环是**程序驱动的状态机**（每个 iteration 有固定阶段：改 prompt→生成→审核→判断）。这是因为：
- 画图流程的步骤是确定的，不需要 LLM 自由决定"下一步做什么"
- 程序驱动可以更精细地控制中断检查点
- 减少 LLM 的"自由度"意味着更可预测的行为和更低的 token 消耗

---

#### 2.3.2 Tool Registry + Materialize/Settle：工具的三段式生命周期

**OpenCode 的设计**：

```typescript
// 1. 注册：所有工具在启动时注册
ToolRegistry.register(tool)

// 2. 物化：每个 turn 开始时，根据当前权限和上下文生成 LLM 可用的工具定义
const { definitions, settle } = registry.materialize(permissions)
// definitions → 发给 LLM 的 tool definitions (OpenAI format)
// settle → 执行工具调用的函数

// 3. 执行：LLM 发出 tool_call 后，调用 settle 执行
const results = await settle(toolCalls)
```

**为什么这样设计**：
- **安全性**：`materialize` 阶段可以根据当前权限过滤工具，某些工具可能在当前上下文中不可用
- **解耦**：LLM 只知道工具的接口定义（name, description, parameters），不知道实现细节
- **可控输出**：工具返回结果可以在 `settle` 中做截断、格式化、日志记录等后处理

**DrawAgent 的适配**：

```python
# 完全相同的思想，Python 化实现
class ToolRegistry:
    def materialize(self, permissions: PermissionSet) -> ToolMaterialization:
        definitions = []
        for tool in self._tools:
            if permissions.allows(tool.name):
                definitions.append(tool.to_openai_schema())
        return ToolMaterialization(
            definitions=definitions,
            settle=lambda calls: [tool.execute(c) for c in calls]
        )
```

**对 DrawAgent 的特别意义**：当系统支持多种图像生成后端（Z-Image / SD / DALL-E）时，`materialize` 可以根据当前配置只暴露当前使用的后端工具，避免 LLM 困惑。

---

#### 2.3.3 Context Epoch + Compaction：结构化的上下文生命周期

**OpenCode 的设计**：

```
初始化 (Initialize):
  所有 SystemContext sources 首次加载 → baseline text + snapshot
  
每次 Turn (Reconcile):
  对比当前 sources 与上次 snapshot
  → Unchanged: 不注入上下文
  → Updated: 注入 delta text (只描述变化部分)
  → Changed (schema incompatible): 完整替换 (full Replace)

Compaction:
  当上下文超过阈值时触发：
  1. 选择最近 N 条消息保留原文
  2. 更早的消息用专用 LLM 压缩为结构化摘要
  3. 摘要模板: Goal | Constraints | Progress | Key Decisions | Next Steps
```

**为什么这样设计**：
- **Baseline/Delta 模型**避免每轮都重复注入不变的上下文（节省 token）
- **结构化摘要**比简单的"截断旧消息"保留更多语义信息
- **Epoch 机制**确保上下文变化可追溯（何时因何故替换了基线）

**DrawAgent 的适配**：

```
DrawAgent 的上下文分为三层：

SystemContext (Epoch 管理):
  - Agent A system prompt、工具定义、用户偏好
  - 这些在一次 session 内基本不变，使用 baseline 模型
  - 只在用户切换模型或修改配置时才更新 (emit delta)

IterationContext (轮次管理):
  - 每轮的 prompt、生成参数、图像引用、C 的观察、A 的判断
  - 保留最近 2 轮完整内容
  - 更早轮次压缩为 CompactionRecord
  
CompactionRecord (压缩格式):
  - 原始需求 (永不压缩)
  - 迭代摘要: Done(已解决) | Blocked(卡住) | Next(下一步计划)
  - 提示词演变轨迹 (简要)
  - 最佳图像引用保留
```

**与 OpenCode 的关键差异**：OpenCode 的 Compaction 模型更通用（适用于任意编程任务），DrawAgent 的 CompactionRecord 可以更精炼——因为迭代是有明确结构的（每轮都是 prompt→生成→审核→判断），摘要可以高度结构化。

---

#### 2.3.4 Steer 机制：运行中的用户中断注入

**OpenCode 的设计**：

```typescript
// 用户随时可以 steer:
session.wake({ type: "steer", message: "Actually, use Python instead of Rust" })

// Runner 在每个 turn 开始时检查:
if (hasPendingSteer) {
    promoteSteerToInput()  // 将 steer 提升为正式的 LLM 输入
}
// 也会在执行工具的过程中检查中断（特别是长时间运行的工具）
```

**为什么这样设计**：
- 用户的控制权高于 LLM 的自主权
- Steer 不是"重新开始"，而是"注入修正"——保留已有进展，只改变方向
- 中断可以发生在不同粒度：turn 之间、工具调用之间、甚至工具执行中

**DrawAgent 的适配**：

```
DrawAgent 的中断检查点更密集：
1. 每个 iteration 之间 (必定检查)
2. 图像生成开始时 (可取消)
3. C 审核完成后 (让用户先看再决定是否继续)
4. 任何长时间操作中 (通过 WebSocket cancel 信号)

中断类型：
- STEER: "换个风格试试" → 保留当前进度，修改方向
- ACCEPT: "这张就行" → 立即终止循环
- MODIFY_PROMPT: "把红色改成蓝色" → 直接修改提示词，下一轮从新 prompt 开始
- ROLLBACK: "回到第2版" → 恢复历史迭代状态
- PAUSE: "暂停，我先看看" → 冻结当前状态，等待 RESUME
```

**与 OpenCode 的差异**：OpenCode 的 steer 是文本消息的形式（"use Python instead"），由 LLM 自己理解。DrawAgent 因为流程更结构化，可以用**具名 Action** 来精确表达用户意图，减少 LLM 理解歧义。

---

#### 2.3.5 Event Sourcing：用事件流驱动状态

**OpenCode 的设计**：

```
所有 session 状态变更都通过 EventV2 服务发布事件：
- message.added, message.updated
- tool_call.started, tool_call.completed
- compaction.started, compaction.ended
- context.updated, context.replaced

好处：
- UI 订阅事件流即可实时更新（无需轮询）
- 所有变更可审计（debug/回放）
- 后端组件之间解耦（通过事件总线通信）
```

**为什么这样设计**：
- 解耦：持久化层、UI 推送层、日志层可以独立订阅事件
- 可恢复：session 状态可以从事件流重建
- 可观测：每个状态变更都有记录

**DrawAgent 的适配**：

```python
# DrawAgent 的事件类型
class DrawEvent:
    ITERATION_STARTED       # iter_003 开始
    PROMPT_REFINED          # 提示词从 v2 变为 v3，变化摘要
    GENERATION_STARTED      # Agent B 开始生成 (含预估时间)
    GENERATION_PROGRESS     # 生成进度 (step 3/8)
    IMAGE_READY             # 图像生成完毕 (含缩略图/引用)
    INSPECTION_STARTED      # Agent C 开始审核
    INSPECTION_COMPLETE     # C 的观察结果
    QUALITY_DECISION        # A 的质量判断 (pass/fail + 理由)
    LOOP_TERMINATED         # 循环结束 (原因: accepted/max_iter/...)
    USER_INTERRUPTED        # 用户中断 (含 action 类型)
```

**与 OpenCode 的差异**：DrawAgent 的事件类型更加领域特定（"prompt refined"、"inspection complete"），因为流程本身更结构化。OpenCode 的通用事件（message added）需要处理任意对话场景，而 DrawAgent 的事件可以更精确地反映图像生成工作流。

---

#### 2.3.6 Agent 生成与切换：动态创建和切换 Agent

**OpenCode 的设计**：

```typescript
// 1. Build agent (默认)
// 2. Plan agent (只读 + plan 文件编辑)
// 3. 动态生成 Agent: Agent.generate(description) → 创建新的 agent 配置
// 4. Plan Exit: plan_exit 工具询问用户 "Switch to build agent?"
```

**为什么这样设计**：
- 不同的任务阶段需要不同的能力边界和权限限制
- Plan mode 限制编写工具权限，只允许编辑 plan 文件
- 切换 Agent 实际上就是切换 system prompt + 工具集 + 权限

**DrawAgent 的潜力方向**：虽然当前只需要一个 Agent A，但这个模式为未来扩展提供了思路：
- 如果将来需要"探索 agent"（自动搜索风格参考图），可以继承这个模式
- 用户可能切换"快速模式 A"（便宜的 LLM + 宽松审核）和"质量模式 A"（贵的 LLM + 严格审核）
- 这本质上就是切换不同的 `AgentConfig`（system prompt + model + tools + params）

---

#### 2.3.7 总结：OpenCode 设计思想的精华

| 设计思想 | 本质问题 | OpenCode 的解法 | DrawAgent 的应用 |
|---------|---------|----------------|-----------------|
| 双层循环 | 用户中断如何与 Agent 执行共存？ | 外层队列 + 内层 turn，每 turn 后检查 | 外层用户交互 + 内层 state-machine 迭代 |
| 三段式工具 | 工具何时暴露给 LLM？如何安全执行？ | register → materialize → settle | 完全采用 |
| Context Epoch | 长对话中不变内容如何不浪费 token？ | baseline/delta 模型 | 系统上下文用 baseline，迭代上下文用 compaction |
| Steer 机制 | 运行中用户如何注入修改？ | 队列化注入，在检查点提升 | 具名 Action + 密集检查点 |
| Event Sourcing | 多消费者如何感知状态变化？ | 事件总线/事件流 | WebSocket 事件推送到 UI + 持久化审计 |
| Agent 切换 | 不同阶段需要不同能力怎么办？ | 预定义 agent 配置 + 切换 | 未来可为不同场景预设多种 A 配置 |

---

## 3. 系统架构

### 3.1 整体架构图

```
┌─────────────────────────────────────────────────────────────────────┐
│                          DrawAgent System                            │
│                                                                      │
│  ┌──────────────┐     ┌──────────────────┐     ┌──────────────────┐ │
│  │   Web UI     │     │   Backend (FastAPI)    │   Config Store   │ │
│  │ (Chat-Style) │◄───►│                                      │◄───┤ (JSON/YAML)     │ │
│  └──────────────┘     │  ┌────────────┐  ┌────────────────┐ │     └──────────────────┘ │
│                        │  │ Orchestrator│  │ Session Store  │ │                          │
│  ┌──────────────┐     │  │  (Loop)    │  │  (SQLite)      │ │     ┌──────────────────┐ │
│  │  CLI Tool    │◄───►│  └─────┬──────┘  └────────────────┘ │     │  Plugin Registry │ │
│  └──────────────┘     │        │                              │◄───┤  (MCP/Skills)    │ │
│                        │  ┌─────┴──────────────────────┐     │     └──────────────────┘ │
│                        │  │       Agent A (Main LLM)    │     │                          │
│                        │  │  ┌──────────────────────┐  │     │     ┌──────────────────┐ │
│                        │  │  │    Tool Execution     │  │     │     │  Model Provider  │ │
│                        │  │  │  ┌──────┐  ┌───────┐ │  │     │◄───►│  Manager         │ │
│                        │  │  │  │ Gen  │  │Review │ │  │     │     │ (Local/API)      │ │
│                        │  │  │  │Image │  │ Image │ │  │     │     └──────────────────┘ │
│                        │  │  │  │ (B)  │  │  (C)  │ │  │     │                          │
│                        │  │  │  └──────┘  └───────┘ │  │     │                          │
│                        │  │  └──────────────────────┘  │     │                          │
│                        │  └────────────────────────────┘     │                          │
│                        └──────────────────────────────────────┘                          │
└─────────────────────────────────────────────────────────────────────┘
```

### 3.2 技术选型

| 层面 | 技术选择 | 理由 |
|------|---------|------|
| **语言** | Python 3.10+ | 生态成熟，LLM/图像领域首选 |
| **Web 框架** | FastAPI + WebSocket | 需要实时双向通信（进度、中断） |
| **异步** | asyncio | 图像生成为 I/O 密集型操作 |
| **持久化** | SQLite + JSON 文件 | 轻量，无需额外部署 |
| **前端** | 单页 HTML (参考 webui_v6.html) | 上手快，复杂 UI 框架非必需 |
| **LLM 调用** | OpenAI-compatible API / litellm | 统一多模型接口 |
| **图像生成** | HTTP API（兼容 Z-Image API 格式） | 解耦，支持任何生图服务 |
| **多模态视觉** | OpenAI-compatible vision API | 统一视觉模型接口 |

### 3.3 前后端解耦与多客户端扩展

虽然 Phase 1 采用 FastAPI + 纯 HTML 前端的方案，但架构从一开始就保持**前后端完全解耦**：

```
┌──────────────────────────────────────────────────────────────────┐
│                         HTTP + WebSocket API                      │
│                                                                   │
│  POST /api/sessions         创建会话                               │
│  POST /api/sessions/{id}/message  发送用户消息                     │
│  POST /api/sessions/{id}/interrupt 中断/steer                     │
│  GET  /api/sessions/{id}/history  获取会话历史                     │
│  WS   /ws/sessions/{id}          实时事件流                        │
│  GET  /api/images/{ref}          图像文件服务                      │
│                                                                   │
├──────────────────────────────────────────────────────────────────┤
│                                                                   │
│  ┌──────────┐    ┌──────────┐    ┌──────────────┐                │
│  │ Web UI   │    │ CLI Tool │    │ Electron App  │  ← 任意客户端  │
│  │ (Phase1) │    │ (未来)   │    │ (未来)        │                │
│  └──────────┘    └──────────┘    └──────────────┘                │
│                                                                   │
│  所有客户端通过同一套 HTTP + WebSocket API 通信                   │
│  前端框架可随时替换（React/Vue/Electron）而不改后端               │
└──────────────────────────────────────────────────────────────────┘
```

**关键原则**：
- 后端只暴露标准的 HTTP REST + WebSocket 接口
- 前端是 API 的消费者之一，可以是任何能发 HTTP 请求的客户端
- Electron 桌面应用只需内嵌同样的 Web 前端 + 系统托盘/通知等原生能力
- 未来甚至可以支持 Discord Bot、Telegram Bot 等非 Web 客户端

### 3.4 为什么不是 LangChain/CrewAI？

- **LangChain**：抽象层太厚，调试困难，序列化开销大
- **CrewAI**：过度设计，对 3-agent 简单场景引入不必要复杂度
- **直接使用 API + 自建循环**：更可控、更透明、更容易调试

遵循 Anthropic 的建议：**先直接用 API，仅在确实需要时引入框架**。

---

## 4. Agent Loop 设计（核心）

### 4.1 双层循环架构

借鉴 OpenCode 的设计，本系统采用 **双层循环**：

```
┌─ Outer Loop (用户交互层) ─────────────────────────────────────────────┐
│                                                                         │
│  while session_is_active:                                              │
│    event = await wait_for_input()    ← 用户需求 / A的提问 / 中断 / steer│
│                                                                         │
│  ┌─ Inner Loop (生成-观测-判断层) ──────────────────────────────────┐  │
│  │  (仅在用户给了"开始/继续画图"指令后进入)                          │  │
│  │                                                                   │  │
│  │  while not_satisfied AND not_interrupted AND iters < max:         │  │
│  │    A: refine_prompt(history)         → 优化提示词                  │  │
│  │    A: design_inspection_tasks(prompt) → 制定本轮检查计划           │  │
│  │    B: generate_images(prompt, seeds) → 生成图像                    │  │
│  │    A → C: inspect(image, tasks)      → 定向观察图像                │  │
│  │    A: evaluate(inspections, prompt)  → 综合判断质量                │  │
│  │    if issues: record for next round  → 记录问题                    │  │
│  │    if interrupted: BREAK             → 用户中断                    │  │
│  │                                                                   │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                         │
│  present_result_to_user()              ← 交付最终结果 / 等待续指令      │
└─────────────────────────────────────────────────────────────────────────┘
```

**关键设计**：内层循环不是 LLM 自主驱动的（不像 OpenCode 的 inner turn），而是**程序驱动的状态机**。每个 iteration 有固定的阶段顺序，A 只在特定节点做决策（检查什么？是否通过？如何修改？），减少 LLM 的"自由度"以换取可预测性和低 token 消耗。

### 4.2 状态机设计

```
                         ┌──────────┐
                         │   IDLE   │ ◄──────────────────────────┐
                         └────┬─────┘                            │
                              │ user submits request             │
                              ▼                                  │
                        ┌──────────┐                             │
         ┌──────────────│ REFINING │ (A 分析需求，可能提问)       │
         │              └────┬─────┘                             │
         │   user clarifies   │ A deems ready                   │
         │   ←────────────────┘                                  │
         │                   ▼                                   │
         │             ┌───────────┐                             │
         │             │  PLANNING │ (A 制定检查计划 + 选种子)    │
         │             └─────┬─────┘                             │
         │                   ▼                                   │
         │             ┌───────────┐                             │
         │             │ GENERATING│ (B 生成图像，可能并发多张)   │
         │             └─────┬─────┘                             │
         │                   │ image(s) ready                   │
         │                   ▼                                   │
         │             ┌───────────┐    A passes                │
         │             │ INSPECTING│────────────────────────────►│
         │             └─────┬─────┘                             │
         │                   │ issues found                     │
         │             ┌─────▼──────┐                            │
         │             │  ANALYZING │ (A 分析问题 → 修改方案)     │
         │             └─────┬──────┘                            │
         │                   │ prompt revised                   │
         │                   │                                  │
         │                   └────→ (回到 PLANNING)              │
         │                                                      │
         │             ┌──────────┐                              │
         └─────────────│INTERRUPT │ (用户随时可中断任意状态)      │
                       └──────────┘                              │
```

### 4.3 Inner Loop 详细流程

```python
async def inner_loop(session: Session, initial_prompt: str):
    """
    内层循环：PLANNING → GENERATING → INSPECTING → ANALYZING
    直到 A 判断通过、用户中断、或达到硬性限制
    """
    
    iteration = 0
    current_prompt = initial_prompt
    observations_history: List[InspectionRecord] = []
    images_history: List[GeneratedImages] = []
    seed_registry: SeedRegistry = SeedRegistry()  # 种子管理
    
    while True:
        # ── 每次 iteration 前检查硬性限制 ──
        if session.interrupt_pending:
            action = await handle_interrupt(session)
            if action.type in ("ACCEPT_CURRENT", "ACCEPT_BEST"):
                return pick_best(images_history)
            if action.type == "STEER":
                current_prompt = action.new_direction
                observations_history = []  # 重置部分历史
            if action.type == "ROLLBACK":
                iteration = action.target_iteration
                current_prompt = images_history[iteration].prompt
                continue
        
        iteration += 1
        if iteration > session.max_iterations:
            yield LoopTerminated("max_iterations_reached")
            return pick_best(images_history)
        
        yield IterationStarted(iteration)
        
        # ── Phase 1: PLANNING ──
        # A 制定本轮检查计划：关注什么？检查什么？
        inspection_plan = await agent_A.design_inspection_plan(
            original_request=session.user_request,
            current_prompt=current_prompt,
            history=observations_history,
            iteration=iteration
        )
        yield InspectionPlanReady(inspection_plan)
        
        # A 选择本轮生成参数（含种子策略）
        gen_params = await agent_A.select_generation_params(
            prompt=current_prompt,
            iteration=iteration,
            seed_registry=seed_registry,
            previous_results=images_history[-1:] if images_history else None
        )
        yield GenerationParamsSelected(gen_params)
        
        # ── Phase 2: PRMPT REFINEMENT (仅第2轮起) ──
        if iteration > 1 and observations_history:
            refinement = await agent_A.refine_prompt(
                original=session.user_request,
                current=current_prompt,
                issues=observations_history[-1].issues_found,
                previous_prompts=[h.prompt for h in observations_history]
            )
            current_prompt = refinement.prompt
            yield PromptRefined(
                before=refinement.previous_prompt,
                after=current_prompt,
                changes=refinement.changes_summary
            )
        
        # ── Phase 3: GENERATING ──
        yield GenerationStarted(gen_params.num_images)
        images = await agent_B.generate(
            prompt=current_prompt,
            negative_prompt=gen_params.negative_prompt,
            **gen_params.to_dict()
        )
        images.iteration = iteration
        images.prompt = current_prompt
        images_history.append(images)
        # 记录种子表现
        seed_registry.record(iteration, gen_params.seeds, images)
        yield ImagesGenerated(images)
        
        # ── Phase 4: INSPECTING ──
        # A 指挥 C 定向观察图像（可能多次调用 C）
        yield InspectionStarted()
        inspection_results = []
        for task in inspection_plan.tasks:
            observation = await agent_C.inspect(
                images=images,
                task=task,  # e.g. "Describe the character's hands. Count fingers."
            )
            inspection_results.append(observation)
            yield InspectionTaskDone(task.name, observation)
        
        yield InspectionComplete(inspection_results)
        
        # ── Phase 5: ANALYZING ──
        # A 综合所有 C 的观察结果，对照 prompt 要求，做出质量判断
        quality_decision = await agent_A.evaluate_quality(
            original_request=session.user_request,
            current_prompt=current_prompt,
            inspection_results=inspection_results,
            iteration=iteration,
            termination_guidelines=session.termination_config
        )
        yield QualityDecision(quality_decision)
        
        if quality_decision.passed:
            yield LoopTerminated("quality_passed")
            return images
        
        # 记录本轮观察结果供下一轮参考
        observations_history.append(InspectionRecord(
            iteration=iteration,
            prompt=current_prompt,
            plan=inspection_plan,
            results=inspection_results,
            decision=quality_decision
        ))
        yield FeedbackRecorded(observations_history[-1])
```

### 4.4 提示词分解策略（Prompt Decomposition）

用户的需求可能是**组合式**的，A 需要智能拆分。

#### 场景一：简单需求
```
用户: "画一只坐在窗台上的猫，阳光从窗外照进来"
→ A 产出 1 个 prompt，生成 2-4 张变体，迭代优化
```

#### 场景二：用户指定数量
```
用户: "生成4张不同姿势的猫"
→ A 产出 1 个 prompt 框架，B 生成 4 张 (num_images=4)，不同的 seed
```

#### 场景三：组合式需求（核心难点）
```
用户: "生成一个少女，发型是双马尾或者盘发或者长发或者短发，
       衣服是短袖或者校服或者衬衫"
```

**A 的处理策略**：

```
Step 1: 识别变量维度
维度1 (hair): 双马尾 | 盘发 | 长发 | 短发    (4 options)
维度2 (clothes): 短袖 | 校服 | 衬衫          (3 options)
总组合数: 4 × 3 = 12

Step 2: 决定策略
- 如果总组合数 ≤ 6: 生成全部
- 如果总组合数 > 6: 采样代表性组合 (例如此处选 6-8 个)
  采样原则: 覆盖所有选项 (每种发型至少出现1次，每种衣服至少出现1次)

Step 3: 采用 "框架优先 (Framework First)" 策略
Phase A — 建立框架:
  选 1 个代表性组合 (如: 双马尾 + 校服)
  进入 inner loop 迭代优化，直到质量基线达标
  
Phase B — 泛化变体:
  将优化好的 prompt 作为模板
  逐一替换变量维度 (发型、衣服描述)
  用更轻量的检查 (只看替换元素的正确性)
  批量生成其余组合

Step 4: 如果用户要求太多组合 (如 4×5×3=60)
  主动与用户沟通:
  "您要求的组合共60种，建议先展示8种代表性组合让您确认方向，
   满意后再批量生成全部，是否同意？"
```

#### 场景四：模糊需求
```
用户: "生成不同颜色的玫瑰"
→ A 选择有代表性的颜色 (红、白、黄、粉、蓝) → 5张
→ 如用户进一步说"还要紫色的" → 追加生成
```

```python
class PromptDecomposer:
    """提示词拆分器"""
    
    async def decompose(self, user_request: str) -> DecompositionResult:
        """
        A 调用此方法分析用户需求中的变量维度
        
        返回:
        - is_simple: 是否为简单需求 (无组合)
        - dimensions: 变量维度列表
        - strategy: "exhaustive" | "sampled" | "framework_first"
        - concrete_prompts: 拆解后的具体提示词列表
        - recommended_count: 建议生成张数
        """
        ...
    
    def sample_combinations(
        self, 
        dimensions: List[Dimension], 
        max_samples: int = 8
    ) -> List[Combination]:
        """从排列组合中采样，确保覆盖所有选项"""
        ...
```

### 4.5 种子管理策略

种子的好坏直接影响生成质量。DrawAgent 将种子视为**可复用资产**进行管理。

```python
class SeedRegistry:
    """种子注册表 - 追踪种子在本次 session 中的表现"""
    
    def __init__(self):
        self._seed_pool: Dict[int, SeedRecord] = {}     # 种子 → 表现记录
        self._good_seeds: List[int] = []                 # 表现好的种子 (按分数排序)
        self._blacklisted: Set[int] = set()              # 黑名单 (产生严重伪影)
        self._seed_lineage: Dict[int, int] = {}          # 种子谱系 (子种子 → 父种子)
    
    def record(self, iteration: int, seeds: List[int], images: GeneratedImages):
        """记录种子在当前 iteration 的表现"""
        for seed, img in zip(seeds, images):
            if img.has_critical_artifact:
                self._blacklisted.add(seed)
            else:
                self._seed_pool[seed] = SeedRecord(
                    iteration=iteration,
                    score=img.quality_score,
                    prompt_family=img.prompt_family_id
                )
                if img.quality_score >= 7.0:
                    self._good_seeds.append(seed)
    
    def suggest_seeds(self, count: int, prompt_family: str, iteration: int) -> List[int]:
        """
        为当前迭代推荐种子
        
        策略:
        - iteration 1: 全随机 (探索)
        - iteration 2+: 
          优先使用本 session 的好种子 (利用)
          + 混入 1-2 个新随机种子 (保持探索)
        - 排除黑名单种子
        - 同一 prompt_family 的好种子优先
        """
        candidates = sorted(
            [s for s in self._good_seeds if s not in self._blacklisted],
            key=lambda s: self._seed_pool[s].score,
            reverse=True
        )
        
        # 利用 + 探索策略
        exploit_count = min(count - 1, len(candidates))
        chosen = candidates[:exploit_count]
        
        # 补充随机新种子
        while len(chosen) < count:
            new_seed = random.randint(0, 2**31 - 1)
            if new_seed not in self._blacklisted and new_seed not in chosen:
                chosen.append(new_seed)
        
        return chosen
```

### 4.6 循环终止策略

终止判断是**多维度的、LLM 主导的**，而非简单的单阈值判断。

```yaml
# 配置中的终止指南
termination:
  # ── 硬性限制 (由 Orchestrator 强制执行) ──
  max_iterations: 7                # 绝对上限
  max_total_cost_usd: 5.0          # 单次 session 费用上限
  
  # ── 软性指南 (供 Agent A 参考) ──
  guidelines:
    - "当所有关键质量要求（critical requirements）都已满足，且剩余问题属于主观偏好类（如'色调可以再暖一点'），可以考虑通过"
    - "当连续 2 轮改进幅度 < 5%（即本轮评分相比上轮提升 < 0.5分 / 满分10），且评分已达到可接受范围（≥ 7.0），应考虑停止——进一步迭代的边际收益低"
    - "当某个问题连续 3 轮未能解决，这可能表示该问题是当前模型的固有限制，继续修改 prompt 无法解决，应当告知用户"
    - "当用户表现出对速度的偏好（如催促、用了'快'等词），适当降低质量门槛"
    - "永远保留最终判断给用户：在认为通过后，展示结果并询问用户意见"

  # Agent A 在 evaluate_quality 时的角色
  role: |
    你作为图像质量的总负责人，根据以下维度综合判断：
    1. 关键要求满足度：用户明确要求的元素是否都出现了？
    2. 技术质量：有无明显的AI生成伪影（畸形手指、扭曲面部等）？
    3. 迭代趋势：本轮是否比上轮有明显改进？
    4. 剩余问题性质：剩余的是客观缺陷还是主观偏好？
    
    你必须输出：
    - passed: bool (是否建议通过)
    - confidence: float (0-1, 你的判断置信度)
    - reasoning: str (判断理由，人类可读)
    - remaining_issues: List[dict] (仍然存在的问题)
    - recommendation: str (建议的下一步：继续修改 / 展示给用户 / 接受)
```

### 4.7 事件驱动设计

参考 OpenCode 的 Event Sourcing 模式，整个 Loop 通过 **事件流** 驱动：

```python
class DrawEvent:
    # ── 会话事件 ──
    SESSION_CREATED = "session.created"
    SESSION_RESUMED = "session.resumed"
    
    # ── 外层循环事件 ──
    USER_MESSAGE = "user.message"           # 用户发送消息
    A_QUESTION = "agent.question"           # A 向用户提问
    USER_ANSWER = "user.answer"             # 用户回答 A 的提问
    
    # ── 内层循环事件 ──
    ITERATION_STARTED = "iteration.started"
    INSPECTION_PLAN_READY = "inspection.plan_ready"
    PROMPT_REFINED = "prompt.refined"       # 提示词变化 (含 diff)
    GEN_PARAMS_SELECTED = "gen.params_selected"
    GENERATION_STARTED = "generation.started"
    GENERATION_PROGRESS = "generation.progress"  # 进度 (step n/N)
    IMAGES_READY = "images.ready"
    INSPECTION_TASK_DONE = "inspection.task_done"  # 单个检查任务完成
    INSPECTION_COMPLETE = "inspection.complete"
    QUALITY_DECISION = "quality.decision"   # A 的质量判断
    LOOP_TERMINATED = "loop.terminated"     # 循环结束 (含原因)
    
    # ── 用户中断事件 ──
    USER_INTERRUPT = "user.interrupt"
    USER_STEER = "user.steer"
    USER_ACCEPT = "user.accept"
    USER_ROLLBACK = "user.rollback"
```

---

## 5. Agent 定义

### 5.1 Agent A: 主控 LLM — 画图总监 (Orchestrator + Quality Owner)

**角色定位**：A 是**整个系统的智能核心和唯一决策者**。它负责需求理解、流程控制、提示词编写、质量把控的全部决策。B 和 C 是它的工具——B 负责"画"，C 负责"看"，但"判断"永远属于 A。

#### A 的核心能力

```
                    ┌─────────────────────────────┐
                    │        Agent A (主控 LLM)     │
                    │                              │
                    │  1. 需求分析 → 理解用户意图    │
                    │  2. 提示词工程 → 写高质量prompt │
                    │  3. 检查规划 → 决定检查什么     │
                    │  4. 质量判断 → 综合信息做决策    │
                    │  5. 策略管理 → 种子/多图/终止   │
                    │  6. 用户交互 → 提问/汇报/确认   │
                    │                              │
                    │  调用 B (generate_image)      │
                    │  调用 C (inspect_image)       │
                    │  调用 ask_user (向用户提问)    │
                    └─────────────────────────────┘
```

#### A 的质量控制角色（重点）

这是本系统的核心设计选择：**A 是质量的唯一负责人，C 是 A 的"眼睛"**。

**为什么这样设计？**

1. **智能层级**：A 通常是最强的 LLM（如 GPT-4o、Claude Sonnet），其理解力、推理力、判断力远高于 C（可能是一个较便宜的多模态模型）。让更强的模型做判断，较弱的模型做描述，是合理的分工。

2. **防止"传声筒"效应**：如果 C 直接给出评分和 pass/fail 结论，A 就会退化成一个传声筒——"C 说不行，那就改；C 说行了，那就过"。A 失去了自己对质量的独立判断，系统的整体智能被 C 的能力边界所限制。

3. **A 知道要检查什么**：生成图像之前，A 最清楚 prompt 里的关键要求是什么。A 应该主动指挥 C："去检查手指数量、检查头发颜色是否为红色、检查背景是否有星空"。而非被动接收 C 返回的通用审核报告。

4. **C 可能犯错**：多模态视觉模型也可能看错。如果 C 误报了一个问题，A 应该有足够的判断力去质疑："C 说手指畸形，但在描述中说手指呈握拳状，可能只是角度问题，我再让 C 换个角度确认一下。"

**A 的质量检查工作流**：

```
每轮迭代的 INSPECTING 阶段：
                              
A 制定检查计划                 C 执行观察                A 综合判断
─────────────          ────────────────         ─────────────────
                      
"这轮 prompt 强调:     C: "手指清晰可见，       A: "C 确认手指正常，
 1. 双马尾发型           每只手5根手指，          发型符合，
 2. 红色和服             关节自然"               但和服颜色偏橙，
 3. 樱花背景                                    背景樱花足够，
                      C: "发型是双马尾，         
先检查 3 项:            蝴蝶结装饰正确"           → 修改 prompt 中的
→ inspect(手指)                                 颜色描述，重新生成"
→ inspect(发型)         C: "衣服是红橙色，
→ inspect(和服颜色)        不是正红色，
→ inspect(樱花数量)        樱花元素充足"
```

**A 可以以不同方式使用 C**：

| 使用方式 | 说明 | 示例 Task |
|---------|------|-----------|
| **定向检查** | A 提出具体问题，C 回答 | "这个人物的眼睛是什么颜色？" |
| **计数检查** | A 要求 C 数数 | "画里有几个人？每个人有几根手指？" |
| **区域描述** | A 让 C 详细描述某区域 | "详细描述画面左上角的背景" |
| **对比检查** | A 让 C 对比两张图 | "图1和图2的角色面部，哪个更像亚洲人？" |
| **通用巡检** | A 让 C 按通用维度扫描 | "检查全图有无明显AI伪影，列出所有异常" |
| **风格分析** | A 让 C 分析艺术风格 | "这张图的整体色调和光照方向是什么？" |

#### A 的 System Prompt 设计要点

```markdown
你是一个专业的图像生成总监 (Art Director)。你的职责是：

## 1. 需求分析与对话
- 理解用户用自然语言表达的图像需求
- 如果需求不明确（风格、构图、色彩、数量），通过 ask_user 工具澄清
- 识别用户需求中的组合元素（如"或者"、"不同的"、列举），主动规划生成策略
- 你的提问应该简洁、有针对性，一次最多问2个问题

## 2. 提示词工程
- 将用户需求转化为 [目标模型名称] 的最佳提示词格式
- 正向提示词：主体 → 细节 → 环境 → 风格 → 构图 → 质量标记
- 负向提示词：已知常见问题（模糊、畸形、低画质）+ prompt 特定问题
- 如果用户要求多种变体，先建立基础提示词框架，再派生变体

## 3. 检查规划 (Inspection Planning)
这是你的核心职责。每次生成图像后，你必须：
- 回顾当前 prompt 中的每个关键要求
- 对照上一轮的遗留问题
- 为该轮制定具体的检查任务列表
- 每个任务应该是一个明确的、可回答的问题（不是"检查质量"，而是"画面中有几个人？"）
- 优先检查：容易出错的关键细节（手指、文字、对称性、特定元素）
- 使用 inspect_image 工具执行检查

## 4. 质量判断
你是最终的质量裁决者。综合 C 的所有观察结果，做出判断：
- 关键要求是否满足？（用户明确提出的必须有的元素）
- 技术质量可接受吗？（无明显伪影、畸变）
- 剩余问题是否可以接受？（主观偏好 vs 客观缺陷）
- 本轮相比上轮是否有实质改进？
- 继续迭代的边际收益是否值得？
- 参考终止指南，但最终判断由你做出

## 5. 工具使用
- generate_image: 调用图像生成服务（可并发调用）
- inspect_image: 让视觉助手观察图像（每次传一个具体任务）
- ask_user: 向用户提问或请求确认

## 6. 沟通原则
- 开始生成前，简要告诉用户你的计划
- 每轮迭代后，简要汇报结果和下一步计划
- 发现无法解决的技术限制时，诚实告知
- 用户中断时，立即响应，理解用户意图
- 不要用技术术语轰炸用户，用自然语言交流
```

**推荐模型**：GPT-4o / Claude Sonnet 4.5 / Qwen-Max / DeepSeek-V3
**关键要求**：强推理能力 + 强指令遵循能力 + 工具调用能力

---

### 5.2 Agent B: 图像生成器 (Generator Tool)

**角色定位**：纯工具 —— 接收 prompt，返回图像。不做任何决策。

**接口定义**：

```python
class ImageGenerationTool:
    """
    图像生成工具
    封装各种文生图后端，提供统一接口
    
    后端支持:
    - Z-Image (本地 DiT, REST API)
    - Stable Diffusion (diffusers / webui API)
    - DALL-E / Flux / Midjourney (云 API)
    - 任何兼容 OpenAI image API 的服务
    """
    
    async def generate(
        self,
        prompt: str,
        negative_prompt: str = "",
        width: int = 1024,
        height: int = 1024,
        num_images: int = 1,
        num_inference_steps: int = 8,
        guidance_scale: float = 0.0,
        seeds: List[int] = None,     # 指定的种子列表（长度应与 num_images 一致）
        **model_specific_params
    ) -> GeneratedImages:
        """
        生成图像
        
        Args:
            seeds: 指定的种子列表。如果为 None 或长度不足，剩余用随机种子。
                   种子列表的第 i 个对应第 i 张图。
        
        Returns:
            GeneratedImages 包含图像数据/引用、使用的种子、生成参数等元数据
        """
        ...
    
    def get_prompt_format_guide(self) -> str:
        """返回该模型的最佳提示词格式指南，会注入到 A 的 system prompt"""
        ...
    
    def get_supported_params(self) -> dict:
        """返回支持的参数列表、范围和默认值"""
        ...
```

**关键设计**：
1. `prompt_format_guide` — 每个后端提供自己的提示词格式说明，A 据此写 prompt。这解决了"不同模型提示词理解力不同"的问题。
2. `seeds` 参数 — 允许 A 显式控制种子，实现种子复用策略。
3. 后端完全可替换 — 通过配置文件切换，A 不需要知道底层是哪个模型。

---

### 5.3 Agent C: 多模态视觉观察者 (Observer Tool)

**角色定位**：纯工具 —— A 的"眼睛"。**只看、只描述，不判断、不评分**。

**设计原则**：
- C 不接受开放式"审核这张图"的指令
- C 接受具体的观察任务（一个问题、一个关注点）
- C 的回复是**描述性**的，不是**评价性**的
- 所有评分、pass/fail 判断一律由 A 负责

**接口定义**：

```python
class ImageInspectorTool:
    """
    图像观察工具 - A 的视觉代理
    
    C 不做的事:
    - 不给出整体评分 (1-10)
    - 不做出 pass/fail 判断
    - 不说"质量很好"或"质量很差"
    
    C 做的事:
    - 回答 A 的具体问题
    - 描述指定区域/元素的细节
    - 计数、定位、识别
    - 列出观察到的异常
    """
    
    async def inspect(
        self,
        images: List[ImageRef],
        task: InspectionTask,       # A 指定的检查任务
        context: str = None          # 可选附加上下文（如该元素的 prompt 描述）
    ) -> InspectionObservation:
        """
        执行一次定向观察
        
        Args:
            images: 要观察的图像（通常 1-2 张，便于对比）
            task: 具体的检查任务
            context: 附加上下文（如 "prompt要求头发是酒红色"）
        
        Returns:
            InspectionObservation（纯描述性结果）
        """
        ...

class InspectionTask:
    """检查任务定义"""
    name: str                       # 任务名 (用于日志)
    question: str                   # 具体问题
    focus: Optional[str]            # 关注区域 (如 "画面左下角")
    expected: Optional[str]         # 期望看到什么 (A 告诉 C 它应该看到什么)
    check_type: InspectionType      # 检查类型

class InspectionType(Enum):
    DESCRIBE = "describe"           # 描述：自由描述关注点
    VERIFY = "verify"               # 验证：确认某个元素是否存在/正确
    COUNT = "count"                 # 计数：数某个对象的数量
    COMPARE = "compare"             # 对比：对比多张图的差异
    SCAN = "scan"                   # 扫描：扫描全图寻找异常
    ANALYZE = "analyze"             # 分析：分析风格/色调/构图特征
```

**C 的输出格式（纯描述性）**：

```python
@dataclass
class InspectionObservation:
    task_name: str                  # 对应的检查任务名
    timestamp: datetime
    
    # 描述性内容
    description: str                # 自然语言描述
    found_elements: List[str]       # 观察到的元素列表
    missing_elements: List[str]     # 未观察到的元素列表 (相对于 expected)
    anomalies: List[str]            # 观察到的异常（"左手小指似乎只有2个关节"）
    
    # 定量信息（如果任务要求）
    counts: Optional[Dict[str, int]]      # 计数结果
    positions: Optional[List[Rect]]       # 定位信息
    
    # 元信息
    confidence: float               # C 对自己观察的置信度 (0-1)
    needs_recheck: bool             # C 建议换个角度再看一次
```

**C 的使用示例**：

```python
# 例1: A 想检查手指（经典难题）
task = InspectionTask(
    name="check_hands",
    question="仔细观察画面中人物的双手。每只手有几根手指？手指的关节和比例是否自然？有任何异常吗？",
    focus="人物的双手区域",
    check_type=InspectionType.DESCRIBE
)
obs = await agent_C.inspect(images, task)
# obs.description: "人物双手可见。左手伸出，五指清晰，关节正常。
#                   右手握拳，可见4根手指（可能是握拳姿势），拇指被遮挡..."

# 例2: A 想确认颜色
task = InspectionTask(
    name="verify_hair_color",
    question="这个人物的头发是什么颜色？请用精确的色名描述",
    expected="prompt要求'酒红色(wine red)'",
    check_type=InspectionType.VERIFY
)

# 例3: A 想全面扫描
task = InspectionTask(
    name="scan_artifacts",
    question="扫描全图，找出所有看起来不自然的区域。特别注意：扭曲的面部特征、不对称的眼睛、融合的背景物体、不正常的身体比例。描述每个异常的具体位置和表现。",
    check_type=InspectionType.SCAN
)
```

**推荐模型**：
- 高质量场景: GPT-4o / Claude Sonnet 4.5 (vision)
- 低成本场景: GPT-4o-mini / Claude Haiku (vision)
- 本地部署: Qwen-VL / LLaVA

**与旧设计的核心区别**：

| 维度 | 旧设计 (C = Evaluator) | 新设计 (C = Observer) |
|------|----------------------|---------------------|
| C 的自主权 | C 自己决定检查什么 | A 告诉 C 检查什么 |
| C 的输出 | 评分 + 问题 + 建议 | 纯描述 + 异常列举 |
| 质量判断 | C 评分 → A 参考 | A 综合观察 → A 判断 |
| 智能上限 | 受限于 C 的能力 | 受限于 A 的能力（更强） |
| 可组合性 | C 一次出完整报告 | A 可多次调用 C，不同角度 |

---

## 6. 工具系统

### 6.1 工具注册架构

参考 OpenCode 的 Tool Registry，采用 **注册-物化-执行** 三段式设计：

```python
class ToolRegistry:
    """
    工具注册中心
    
    模式：
    1. register() - 注册工具定义
    2. materialize() - 生成面向 LLM 的工具描述和 execute 函数
    3. settle() - 执行工具调用，处理结果
    """
    
    def __init__(self):
        self._tools: Dict[str, Tool] = {}
    
    def register(self, tool: Tool):
        """注册一个工具"""
        self._tools[tool.name] = tool
    
    def materialize(self, agent_config: AgentConfig) -> ToolMaterialization:
        """
        物化工具：为 LLM 调用做准备
        
        关键：根据当前 agent_config 过滤可用工具。
        例如，如果配置的是不支持 vision 的 LLM 做 A，
        则 inspector 工具可能需要走纯文本降级路径。
        """
        definitions = []
        for name, tool in self._tools.items():
            if tool.is_available_for(agent_config):
                definitions.append(tool.to_openai_schema())
        
        return ToolMaterialization(definitions, self._settle)
    
    async def _settle(self, tool_calls: List[ToolCall]) -> List[ToolResult]:
        results = []
        for call in tool_calls:
            tool = self._tools[call.name]
            result = await tool.execute(call.arguments)
            # 对图像类结果做特殊格式化（A 看不到图像本身）
            result = tool.format_for_llm(result)
            results.append(result)
        return results
```

### 6.2 核心工具列表

| 工具名 | 调用者 | 功能 | OpenAIschema |
|--------|--------|------|------|
| `generate_image` | A | 调用 B 生成图像 | prompt, negative_prompt, width, height, num_images, seeds[], steps, guidance |
| `inspect_image` | A | 调用 C 定向观察图像 | task{question, focus, expected, type}, image_refs[], context |
| `ask_user` | A | 向用户提问/请求确认 | question[], multiple_choice?, context |
| `save_image` | A | 保存指定图像到本地 | image_ref, path, format |
| `compare_images` | A | 调用 C 对比两张图的差异 | image_ref_a, image_ref_b, focus |
| `rollback_iteration` | A | 恢复到历史迭代的状态 | target_iteration |

### 6.3 工具调用流程

```
Agent A (LLM) 决定调用 inspect_image
    │
    ├─ LLM 输出 tool_call: {
    │     name: "inspect_image",
    │     args: {
    │       image_refs: ["@img_session_1_iter_2_0"],
    │       task: {
    │         question: "这个人物的左手有几根手指？",
    │         focus: "人物左手",
    │         expected: "应该有5根手指",
    │         type: "verify"
    │       }
    │     }
    │   }
    │
    ├─ Orchestrator 接收 tool_call
    │   ├─ 加载实际图像数据
    │   ├─ 调用 Agent C (多模态 LLM)
    │   ├─ 处理结果（提取描述文本）
    │   └─ 格式化工具返回结果
    │
    ├─ 工具结果注入 A 的上下文
    │   {role: "tool", tool_call_id: "xxx", content: "{
    │     'description': '左手可见5根手指，关节比例正常，...',
    │     'anomalies': [],
    │     'confidence': 0.92
    │   }"}
    │
    └─ A 继续推理，可能调用更多 inspect_image 或做出质量判断
```

**图像在 A 上下文中的表示**：

A 是纯文本 LLM，看不到图像本身。策略：
- A 的上下文中，图像只用 `@img_{session}_{iter}_{idx}` 引用
- 工具返回结果中附带缩略图的 base64（如果 A 的模型支持 vision）
- 如果 A 不支持 vision（纯文本模型），则完全依赖 C 的文字描述
- 对于支持 vision 的 LLM（如 GPT-4o），可以将缩略图直接放入上下文

---

## 7. 上下文管理

### 7.1 挑战

图像生成迭代会产生大量上下文：
- 每轮迭代：prompt + 审核结果 + 修改建议
- 多轮迭代后上下文可能超过模型窗口
- 图像本身不能放入文本上下文（Agent A 看不到图）

### 7.2 解决方案：分层上下文 + 结构化压缩

参考 OpenCode 的 **Context Epoch + Compaction** 设计。

#### SystemContext（固定层）

系统指令、工具定义、用户偏好 —— 这些在每个 turn 中保持不变。

```python
class SystemContext:
    """系统上下文 - 每个 session epoch 的基线"""
    
    agent_a_system_prompt: str     # Agent A 的系统提示
    tools_description: str         # 可用工具描述
    user_preferences: dict         # 用户偏好设置
    model_config: ModelConfig      # 当前模型配置
```

#### IterationContext（迭代层）

每轮迭代的输入输出，需要跨轮次传递的信息。

```python
class IterationContext:
    """单次迭代的上下文"""
    
    iteration: int
    prompt_used: str
    generation_params: dict
    image_refs: List[str]          # 图像引用 ID
    review_summary: str            # 审核摘要（不是原始结果）
    changes_made: str              # 本轮的修改
    decision: str                  # 为什么继续/停止
```

#### CompactedHistory（压缩层）

当迭代次数超过阈值时，将历史迭代压缩为结构化摘要。

```python
class CompactedHistory:
    """压缩后的历史上下文"""
    
    original_request: str          # 用户原始需求
    iteration_count: int           # 已完成迭代次数
    best_score: float              # 最高评分
    persistent_issues: List[str]   # 持续未解决的问题
    resolved_issues: List[str]     # 已解决的问题
    key_decisions: List[str]       # 关键决策记录
    prompt_evolution: str          # 提示词演变历程（简要）
```

### 7.3 压缩策略

```
if context_tokens > THRESHOLD:
    compact()
    
def compact():
    1. 保留最近 2 轮完整迭代上下文
    2. 更早的迭代用 LLM 压缩为 CompactedHistory
    3. 压缩时保留：
       - 用户原始需求（不可丢）
       - 未解决的问题（需要后续关注）
       - 提示词演变的关键决策
       - 最高分的图像引用
    4. 丢弃：中间版本的具体审核细节
```

### 7.4 上下文组装

每个 LLM 调用时，上下文的组装顺序：

```
1. SystemContext (固定)
2. CompactedHistory (如果有)
3. 最近 N 轮 IterationContext (完整)
4. 当前对话消息 (User ↔ Assistant)
5. 当前工具调用结果
```

---

## 8. 用户中断与控制

### 8.1 设计原则

用户对流程有**完全把控权**，任何时刻都可以：
- 暂停/中断当前操作
- 修改方向（"换个风格试试"）
- 接受当前结果（即使未完全通过审核）
- 拒绝当前方向，回到之前的某个版本
- 手动修改提示词

### 8.2 中断机制

参考 OpenCode 的 **Steer 机制**：

```python
class UserControl:
    """用户控制层"""
    
    async def interrupt(self, session_id: str, action: UserAction):
        """用户中断当前循环"""
        session = self.get_session(session_id)
        session.pending_action = action
        session.interrupt_flag.set()  # 设置中断标志
        
        # 如果正在进行图像生成（长时间操作），发送取消信号
        if session.state == SessionState.GENERATING:
            await self.cancel_generation(session_id)

class UserAction(Enum):
    PAUSE = "pause"                    # 暂停，等待用户后续指令
    ACCEPT_CURRENT = "accept_current"  # 接受当前图像作为最终结果
    STEER = "steer"                    # 修改方向，附上新需求
    REJECT = "reject"                  # 拒绝当前方向，回退
    MODIFY_PROMPT = "modify_prompt"    # 用户手动修改提示词
    SKIP_REVIEW = "skip_review"        # 跳过审核，直接接受
```

### 8.3 中断处理流程

```
Inner Loop 在每个检查点检查中断标志：

┌─ check_interrupt() ──────────────────────────────────────────────┐
│                                                                    │
│  if not session.interrupt_flag.is_set():                           │
│      return (继续)                                                  │
│                                                                    │
│  action = session.pending_action                                   │
│  session.interrupt_flag.clear()                                    │
│                                                                    │
│  switch action:                                                    │
│      case ACCEPT_CURRENT:                                          │
│          → 结束 inner loop，返回当前图像                            │
│      case STEER:                                                   │
│          → 将用户新需求注入上下文                                    │
│          → 回到 inner loop 起点，以新需求重新生成                    │
│      case MODIFY_PROMPT:                                           │
│          → 用用户修改后的提示词替换当前提示词                         │
│          → 回到 GENERATING 状态                                     │
│      case REJECT:                                                  │
│          → 如果指定了回退版本，恢复到该版本                          │
│          → 否则等待用户给出新方向                                    │
│      case PAUSE:                                                   │
│          → 悬停，等待用户 RESUME 或给出新指令                        │
│                                                                    │
└────────────────────────────────────────────────────────────────────┘
```

### 8.4 WebSocket 实时通信

用户控制和进度推送通过 WebSocket 实现：

```python
# WebSocket 消息类型
{
    "type": "progress",         # 进度更新
    "type": "image_generated",  # 新图像生成
    "type": "review_result",    # 审核结果
    "type": "state_change",     # 状态变化
    "type": "error",            # 错误信息
}

# 用户 → 服务器
{
    "type": "interrupt",
    "action": "steer",
    "data": {"message": "画面太暗了，我想要明亮的色调"}
}
```

---

## 9. 配置系统

### 9.1 配置文件格式

采用 YAML/JSON 配置文件，支持多层级覆盖：

```
~/.drawagent/
├── config.yaml              # 全局默认配置
├── presets/                  # 预设配置
│   ├── fast.yaml             # 快速生成预设
│   ├── quality.yaml          # 高质量预设
│   └── anime.yaml            # 动漫风格预设
├── history/                  # 生成历史
└── plugins/                  # 插件目录 (未来)

项目目录/
└── .drawagent.yaml           # 项目级配置（覆盖全局）
```

### 9.2 配置结构

```yaml
# ~/.drawagent/config.yaml

# ── Agent 模型配置 ──
agents:
  A:  # 主控 LLM
    provider: openai           # openai | anthropic | local | custom
    model: gpt-4o
    api_base: https://api.openai.com/v1
    api_key: ${OPENAI_API_KEY}  # 支持环境变量
    temperature: 0.7
    max_tokens: 4096
    system_prompt: default      # default | path/to/custom_prompt.md

  B:  # 图像生成
    provider: local_zimage     # local_zimage | comfyui | openai_dalle | sd_webui
    model: Z-Image-Turbo
    api_base: http://localhost:8000
    endpoint: /api/generate
    default_params:
      width: 1024
      height: 1024
      steps: 8
      guidance: 3.5
      seed: -1                  # -1 = random
    prompt_format: zimage      # zimage | sd | dalle | flux

  C:  # 多模态审核
    provider: openai
    model: gpt-4o              # 需支持 vision
    api_base: https://api.openai.com/v1
    api_key: ${OPENAI_API_KEY}
    temperature: 0.3           # 审核需要一致性，低温度
    max_tokens: 2048

# ── Loop 配置 ──
loop:
  max_iterations: 5             # 最大迭代次数
  auto_accept_threshold: 8.0    # 自动接受阈值（0-10，超过自动通过）
  review_dimensions:            # 审核维度（可启用/禁用）
    - element_completeness
    - style_accuracy
    - composition
    - detail_quality
    - color_accuracy
  context:
    max_tokens: 32000           # Agent A 最大上下文
    compaction_threshold: 20000  # 触发压缩的阈值
    keep_recent_iterations: 2   # 压缩时保留最近 N 轮

# ── 用户交互配置 ──
interaction:
  confirm_before_generate: false  # 生成前是否确认提示词
  auto_answer_simple: true        # 简单确认问题自动回答
  show_intermediate_images: true  # 是否展示中间版本
  notify_on_complete: true        # 完成时通知

# ── 输出配置 ──
output:
  save_dir: ./outputs
  save_intermediate: true         # 是否保存中间版本
  image_format: png
  quality: 95

# ── 扩展配置 (未来) ──
extensions:
  mcp_servers: []
  skills: []
  plugins: []
```

### 9.3 Model Provider 抽象

```python
class ModelProvider(ABC):
    """模型提供者抽象"""
    
    @abstractmethod
    async def chat(self, messages: List[Message], tools: List[ToolDef]) -> ChatResponse:
        """LLM 对话"""
        pass
    
    @abstractmethod
    async def generate_image(self, prompt: str, **params) -> List[Image]:
        """图像生成"""
        pass
    
    @abstractmethod
    async def review_image(self, image: Image, prompt: str) -> ReviewResult:
        """多模态图像审核"""
        pass

class OpenAIProvider(ModelProvider):
    """OpenAI 兼容 API"""
    ...

class AnthropicProvider(ModelProvider):
    """Anthropic API"""
    ...

class LocalZImageProvider(ModelProvider):
    """本地 Z-Image 模型"""
    ...
```

---

## 10. 记忆模块（Memory）

### 10.1 记忆的定位与目标

记忆模块解决跨会话的**经验复用**问题。当前图像生成的两个核心痛点——提示词反复调整和检查项遗漏——都可以通过记忆来缓解。

**核心目标**：
- **提示词复用**：某个场景经过多轮调试终于写出好 prompt，下次类似需求直接参考
- **检查项积累**：用户反馈"这里没检查到"，记下来下次主动检查
- **知识沉淀**：模型特定技巧、有效负向提示词模式、顽固问题解决方法等

**设计原则**：
- **用户需求永远是第一优先级**：记忆是辅助，不是替代。Agent 绝不能因为记忆中有"类似的"案例，就偷懒用旧方案顶替用户的新需求。记忆用于**加速到达目标**，而不是**改变目标本身**。判断标准：如果用户对比 prompt 和需求，能立刻看出"这是我想要的"，而不是"这看起来像上次那个"。
- Agent **自主决定**记什么、什么时候记（不是自动 dump 所有东西）
- 记忆是**被动的阅读材料**——Agent 读了后自己判断怎么用，不是硬编码的规则
- 文件系统 + Markdown，人类可读可编辑，Agent 也能读写
- 按需加载——不是一个文件全部注入，而是 Agent 根据任务特征选择性加载相关部分

### 10.2 记忆目录结构

```
~/.drawagent/
├── config.yaml                    # 全局配置
├── history/                       # 会话历史 (SQLite)
├── memory/                        # ★ 记忆模块 (Markdown)
│   ├── index.md                   # 记忆索引 — Agent 先读这个
│   ├── prompts/                   # 提示词记忆
│   │   ├── portraits.md           #   人像/角色类
│   │   ├── landscapes.md          #   风景/场景类
│   │   ├── objects.md             #   物品/静物类
│   │   ├── concepts.md            #   抽象概念/风格类
│   │   └── animals.md             #   动物类
│   ├── inspections/               # 检查项记忆
│   │   ├── _builtin_common.md     #   内置通用检查（发版自带）
│   │   ├── _builtin_portrait.md   #   内置人像专项检查
│   │   ├── _builtin_scene.md      #   内置场景专项检查
│   │   └── user_feedback.md       #   用户反馈积累的检查项
│   ├── techniques/                # 技巧/模式记忆
│   │   ├── negative_prompts.md    #   有效的负向提示词模式
│   │   ├── style_phrases.md       #   风格描述词汇/句式
│   │   └── model_specific.md      #   特定模型的提示词技巧
│   └── failures/                  # 教训/顽固问题
│       ├── known_issues.md        #   已知棘手问题及workaround
│       └── unsolvable.md          #   当前模型能力边界（记录但不强求）
└── presets/                       # 参数预设
```

### 10.3 记忆索引 (index.md)

Agent 在每个 session 开始时首先加载索引，了解有哪些记忆可用：

```markdown
# DrawAgent 记忆索引

> 每个条目记录: 场景关键词 + 文件路径 + 条目数 + 最后更新
> Agent 根据用户需求的关键词匹配，决定加载哪些文件

## Prompts (提示词记忆)

### prompts/portraits.md — 人像/角色 (3 entries)
- 关键词: 人物, 肖像, 角色, 面部, 半身像, 全身像, portrait, character, face
- 更新: 2026-06-20

### prompts/landscapes.md — 风景/场景 (2 entries)
- 关键词: 风景, 建筑, 室内, 室外, 城市, 自然, landscape, scenery, building
- 更新: 2026-06-15

### prompts/concepts.md — 抽象/风格 (1 entry)
- 关键词: 抽象, 赛博朋克, 幻想, 超现实, cyberpunk, fantasy, surreal
- 更新: 2026-06-18

## Inspections (检查项)

### inspections/_builtin_common.md — 通用检查 (12 items) [内置]
- 所有图像生成都适用

### inspections/_builtin_portrait.md — 人像专项检查 (8 items) [内置]
- 关键词: 人物, 肖像, 面部, 手

### inspections/user_feedback.md — 用户反馈积累 (2 items)
- 更新: 2026-06-22

## Techniques (技巧)

### techniques/negative_prompts.md — 负向提示词模式 (4 entries)
### techniques/style_phrases.md — 风格描述技巧 (3 entries)

## Failures (教训)

### failures/known_issues.md — 已知顽疾 (3 entries)
```

### 10.4 提示词记忆条目格式

每个记忆条目有统一的结构，方便 Agent 理解和匹配：

```markdown
# portraits.md — 人像/角色提示词记忆

---

## [记忆] 亚洲女性写实肖像 (半身, 正面, 自然光)
**日期**: 2026-06-20
**场景描述**: 
写实风格, 半身照, 正面朝向镜头, 年轻亚洲女性

**提示词**:
```
高质量的真人照片风格，一位25岁左右的亚洲女性，黑色长发柔顺披肩，
自然的淡妆，温柔的微笑表情。穿着白色棉质衬衫，坐在窗边木质椅子上。
柔和的自然光从左侧窗户照入，在面部形成柔和的伦勃朗光影。
浅景深效果(f/2.8)，背景自然虚化。画面干净，专业摄影质感，
高细节，锐利焦点。
```

**负向提示词**:
```
过度修图, 塑料感皮肤, 不自然的肤色, 手指畸形, 不对称的眼睛,
低画质, 模糊, 过度曝光, 恐怖谷效应
```

**关键参数**: steps=8, guidance=3.5, seed=42001
**效果评价**: 皮肤质感自然, 手指正常, 光影柔和且立体
**标签**: `人像` `写实` `女性` `自然光` `半身`

---

## [记忆] 赛博朋克风格角色 (全身, 夜景, 霓虹灯)
**日期**: 2026-06-18
**场景描述**:
赛博朋克风格, 全身像, 女性角色, 夜景城市背景

**提示词**:
```
cyberpunk style, full body shot of a female character, 20 years old,
short bob hair with neon blue highlights, wearing a black leather jacket
with LED trim, augmented reality visor over one eye. Standing on a
rain-slicked street in a futuristic city at night. Neon signs in
background with pink and cyan glow reflecting on wet pavement.
Cinematic lighting, high contrast, blade runner aesthetic, highly detailed.
```

**负向提示词**:
```
cartoon, anime, low poly, blurry background, overexposed neon, 
distorted face, extra limbs
```

**效果评价**: 霓虹光反射逼真, 雨夜氛围好, 但是第一次的手部有问题,
  使用 seed=88723 后解决
**标签**: `赛博朋克` `全身` `夜景` `女性` `科幻`
**关联教训**: 参见 failures/known_issues.md#赛博朋克手部问题
```

**关键字段说明**：
| 字段 | 用途 | Agent 使用方式 |
|------|------|---------------|
| 场景描述 | 匹配用户需求 | Agent 读取后判断"这个和用户要的像不像" |
| 提示词 | 复用/参考 | 可以直接复制或以此为模板修改 |
| 负向提示词 | 复用 | 同类场景通常适用 |
| 效果评价 | 了解效果 | 知道这个 prompt 的实际产出质量 |
| 标签 | 关键词匹配 | 便于 Agent 和未来搜索引擎检索 |
| 关联教训 | 问题追踪 | 如果有已知的坑，提醒 Agent 注意 |

### 10.5 检查项记忆格式

**内置通用检查项** (`inspections/_builtin_common.md`)：

```markdown
# 通用图像检查项 (内置)

> 这些检查项在每轮生成后都应考虑。
> 实际执行时，Agent A 应根据具体 prompt 从中挑选相关的，
> 转化为具体的 InspectionTask 交给 Agent C。

## 技术质量
- [ ] **整体清晰度**: 图像是否清晰锐利，无全局模糊？
- [ ] **伪影扫描**: 画面中是否有不自然的斑点、条纹、色块、鬼影？
- [ ] **JPEG伪影**: 是否有块状压缩痕迹？
- [ ] **分辨率一致性**: 不同区域的分辨率是否一致（无局部模糊）？

## 构图基础
- [ ] **主体完整**: 主体是否被裁切？是否在画面合理位置？
- [ ] **对称性**: 如有对称要求，左右是否均衡？
- [ ] **视觉重心**: 画面重心是否合理，元素分布是否平衡？

## 色彩与光照
- [ ] **色温一致**: 画面整体色温是否一致（无局部异常偏色）？
- [ ] **光源逻辑**: 若有明确光源，阴影方向是否一致？
- [ ] **饱和度**: 颜色是否过饱和或欠饱和？是否符合描述？

## 常见AI缺陷
- [ ] **文字渲染**: 如有文字，拼写是否正确，无乱码？
- [ ] **边缘融合**: 主体与背景边界是否清晰，无异常融合？
- [ ] **纹理重复**: 是否有不自然的重复图案（瓦片效应）？
- [ ] **透视一致性**: 透视/景深是否符合物理逻辑？
```

**内置人像专项检查** (`inspections/_builtin_portrait.md`)：

```markdown
# 人像专项检查项 (内置)

> 当 prompt 涉及人物时，Agent A 必须从以下项目中挑选相关的进行检查。

## 手部 (经典难点)
- [ ] **手指数量**: 每只手是否恰好5根手指？
- [ ] **手指关节**: 关节弯曲是否自然？有无多余的指节？
- [ ] **手指比例**: 手指长度比例是否正常（中指最长，拇指最粗）？
- [ ] **手部姿势**: 手势是否合理？是否出现握拳时手指穿模？
- [ ] **左右手区别**: 左右手的拇指方向是否正确？

## 面部
- [ ] **眼睛对称**: 双眼大小、位置、颜色是否对称？
- [ ] **嘴部**: 嘴唇形状是否自然，牙齿（如露出）是否正常？
- [ ] **面部比例**: 三庭五眼比例是否正常？
- [ ] **表情**: 表情是否符合 prompt 描述？是否自然？
- [ ] **肤色均匀**: 面部肤色是否均匀，无异常色斑？

## 身体与姿态
- [ ] **肢体数量**: 手臂/腿的数量是否正确？
- [ ] **关节方向**: 肘部、膝盖弯曲方向是否符合人体结构？
- [ ] **身体比例**: 头身比是否合理（除非 prompt 指定特殊风格）？
- [ ] **服装穿戴**: 衣物是否正常穿在身上，无穿模或异常褶皱？

## 头发
- [ ] **发丝自然**: 发丝是否流畅，有无断裂或模糊块？
- [ ] **头发与背景**: 头发边缘与背景是否清晰分开？
- [ ] **发色准确**: 发色是否符合 prompt 描述？
```

**用户反馈积累** (`inspections/user_feedback.md`)：

```markdown
# 用户反馈积累的检查项

> 这些检查项来自用户的明确反馈："这个应该检查，但我没说，你也没想到"
> Agent A 在制定检查计划时，应将相关项加入。

## 2026-06-22 — 来自用户 "风景画天空细节"
- 来源: 用户要求画"黄昏海滩"，生成后用户指出"天空的云颜色不对"
- 新增检查: "天空中的云朵颜色是否与时段匹配？（黄昏应有暖色调云层）"
- 关联场景: 日落, 日出, 黄昏, 黎明, 天空, 户外

## 2026-06-22 — 来自用户 "角色服装细节"
- 来源: 用户要求"穿和服的少女"，生成后发现"腰带（obi）的打结方式画错了"
- 新增检查: "如有传统服饰，其关键结构是否符合文化规范？"
- 关联场景: 和服, 汉服, 传统服饰, 民族服装
```

### 10.6 记忆与 Agent Loop 的集成

记忆在以下 4 个时间点介入流程：

```
Session 生命周期中的记忆交互：

1. SESSION START — 记忆加载
   ├─ Agent A 收到用户需求
   ├─ 读取 memory/index.md
   ├─ A 根据需求关键词匹配相关记忆文件
   ├─ 选择性加载相关文件内容到上下文
   │   (例如: 用户说"画一个女孩"→ 加载 portraits.md + _builtin_portrait.md)
   └─ 工具: load_memory("portraits") → 返回文件内容

2. PROMPT REFINEMENT — 记忆参考
   ├─ A 在编写/修改提示词时
   ├─ 可从已加载的记忆中参考类似场景的成功prompt
   ├─ 可直接复用成熟的负向提示词
   └─ 工具: search_memory("赛博朋克 夜景 提示词") → 语义搜索

3. INSPECTION PLANNING — 检查项注入
   ├─ A 制定 InspectionPlan 时
   ├─ 从已加载的检查项记忆中挑选适用的 items
   ├─ 结合用户反馈积累的检查项
   └─ 生成具体的 InspectionTask 列表

4. SESSION END — 记忆写入
   ├─ 用户满意后（或用户主动说"记下来"）
   ├─ A 评估本次 session 是否有值得保存的经验
   ├─ A 决定写入什么、写入哪个文件
   └─ 工具: save_memory(category="portraits", content="...")
           update_memory_index(category="portraits", summary="...")
```

### 10.7 记忆工具定义

```python
class MemoryTool:
    """记忆管理工具集"""
    
    async def load_index(self) -> str:
        """加载记忆索引 — 每个 session 开始前调用"""
        with open("~/.drawagent/memory/index.md") as f:
            return f.read()
    
    async def load_memory(self, category: str) -> str:
        """
        加载指定类别的记忆文件
        
        Args:
            category: 类别名，如 "portraits", "inspections/_builtin_portrait"
        
        Returns:
            文件内容（完整 Markdown）
        
        Security:
            路径必须限定在 memory/ 目录内，防止目录穿越
        """
        safe_path = self._validate_path(f"~/.drawagent/memory/{category}.md")
        with open(safe_path) as f:
            return f.read()
    
    async def search_memory(self, query: str) -> List[MemoryHit]:
        """
        在所有记忆中搜索相关内容（Phase 1: 关键词匹配; Phase 2: 向量搜索）
        
        Args:
            query: 搜索查询 (如 "赛博朋克 霓虹 夜景")
        
        Returns:
            匹配的记忆片段列表
        """
        ...
    
    async def save_memory(
        self, 
        category: str,       # e.g. "prompts/portraits"
        content: str,         # Markdown 格式的记忆条目
        append: bool = True   # True=追加到文件末尾, False=覆盖
    ):
        """写入记忆"""
        ...
    
    async def update_index(
        self,
        category: str,
        summary: str,         # 更新后的摘要描述
        entry_count: int       # 当前条目数
    ):
        """更新 index.md 中对应条目的摘要"""
        ...
```

### 10.8 Agent A 的记忆使用指南（System Prompt 注入）

在 Agent A 的 system prompt 中加入以下记忆使用指导：

```markdown
## 记忆系统使用

你有权访问一个跨会话的记忆系统（Markdown 文件），用于复用成功经验。

### 何时加载记忆
- Session 开始时，先读 index.md 了解有哪些可用记忆
- 根据用户需求的关键词，选择加载相关的记忆文件
- 如果用户需求有明确场景（如"画一个人像"），加载对应的检查项

### 如何在提示词阶段使用记忆
- 浏览已加载的提示词记忆，寻找与当前需求相似的场景
- 如果找到高度匹配的记忆，以其 prompt 为模板，针对当前需求修改
- 直接复用匹配场景的负向提示词（同类场景的 negative prompt 通常通用）
- 参考记忆中的参数设置（steps, guidance等）作为起点

### ⚠️ 记忆使用的铁律：用户需求优先
记忆是**参考资料**，不是**替代方案**。绝对禁止以下行为：
- ❌ "用户要画 A，记忆里有类似的 A'，直接用 A' 的 prompt 去生成" — 这是偷梁换柱
- ❌ "记忆中 A' 的效果很好，说服用户接受 A' 而不是 A" — 代理不能改变用户目标
- ❌ 把记忆中的 prompt 原封不动复制给 B 去生成，而不根据当前需求修改

正确使用方式：
- ✅ 从记忆中提取**写作技巧**（如"Z-Image 对光影描述响应好，应该写'柔和自然光+伦勃朗光影'这种句式"），应用到当前需求的 prompt
- ✅ 从记忆中提取**通用模块**（如负向提示词中的"手指畸形、不对称眼睛"），这类跨场景通用
- ✅ 从记忆中提取**踩坑经验**（如"赛博朋克场景 guidance 不要超过 4，否则霓虹会过曝"）
- ✅ 记忆提示：**最终交付给用户的图，用户应该能看出这就是他要求的，而不是另一个相似的东西**

如果你的记忆中没有任何与当前需求真正匹配的内容，**宁可不用记忆，从零开始写 prompt**。
用错记忆比不用记忆更糟糕。

### 如何在检查阶段使用记忆
- 浏览已加载的检查项记忆
- 从通用检查项中挑选与当前 prompt 相关的
- 如涉及人物，必须从人像检查项中选取手部、面部相关项
- 检查用户反馈积累项中是否有与当前场景相关的
- 转化为具体的 InspectionTask（不要直接把检查项的标题发给C）

### 何时写入记忆
Session 结束时，评估以下情况：
- **值得保存的场景**: 经过多轮调试终于写出好 prompt → 写提示词记忆
- **新发现的检查项**: 用户指出你没检查到的东西 → 写用户反馈记忆
- **有效的技巧**: 发现某个负向提示词组合特别有效 → 写技巧记忆
- **明确的教训**: 某个问题尝试多次无法解决 → 写 failure 记忆

写入记忆时：
- 确保格式符合对应文件的规范（参考已有条目）
- 标签要准确，方便后续匹配
- 不要写无价值的泛泛记录（如"这张图还行"）
```

### 10.9 记忆加载的上下文管理

记忆文件可能很大，全加载浪费 token。设计多层加载策略：

```
Level 0: index.md (始终加载, ~200 tokens)
  → Agent 获得所有记忆的概览

Level 1: 按需加载相关文件 (~500-1500 tokens/file)
  → Agent 根据需求关键词匹配，调用 load_memory
  → 例如: 用户需求含"人物"→加载 portraits.md + _builtin_portrait.md

Level 2: 搜索特定内容 (~200-500 tokens/result)
  → 当 Level 1 的文件仍然太大或不精确时
  → Agent 调用 search_memory("关键词") 获取精确匹配

Level 3: 写入 (无 token 开销)
  → Agent 在 session 结束时调用 save_memory
  → 写入操作不占用上下文 token
```

**加载决策流程**：

```python
# Agent A 在 session 开始时的典型行为：
# (这些行为由 system prompt 引导，而非硬编码)

1. 读取 index.md
2. 分析用户需求: "画一个穿汉服的少女在樱花树下"
3. 关键词提取: 人物, 汉服 (传统服饰), 户外, 樱花
4. 匹配记忆:
   - prompts/portraits.md (人物相关)
   - prompts/landscapes.md (户外场景)
   - inspections/_builtin_portrait.md (人像检查)
   - inspections/user_feedback.md (有"传统服饰"相关反馈)
5. 加载以上 4 个文件 (总计 ~3-5K tokens)
6. 在提示词编写时，发现 portraits.md 中有"亚洲女性写实肖像"记忆
   → 以该记忆的 prompt 为蓝本，修改: 加入汉服描述、加入樱花场景
7. 在检查规划时，从 _builtin_portrait.md 选择 5 个相关项，
   从 user_feedback.md 选择"传统服饰结构检查"
   → 生成 6 个 InspectionTask
```

### 10.10 记忆分类的自动演化

Agent 可以在需要时自主创建新的分类文件：

```python
# Agent 发现"产品摄影"类记忆越来越多，目前散落在不同文件中
# Agent 自主创建新文件:

# 1. 写入新记忆
save_memory(
    category="prompts/product_photography",
    content="""---
## [记忆] 白色耳机产品照 (白底, 影楼光)
...
"""
)

# 2. 更新索引
update_index(
    category="prompts/product_photography",
    summary="产品摄影提示词",
    entry_count=1
)
```

**分类策略**：
- 初始提供预设分类（portraits / landscapes / objects / concepts / animals）
- Agent 可以创建新分类（如 "food_photography"、"sci_fi_concepts"）
- 如果某个分类文件条目过多（>20条），Agent 可以建议拆分为子文件
- 用户也可以手动在文件系统中创建/编辑/删除记忆文件

### 10.11 与未来扩展的衔接

| 阶段 | 存储后端 | 检索方式 | 备注 |
|------|---------|---------|------|
| **Phase 1** (当前) | Markdown 文件 | 关键词匹配 + LLM 阅读理解 | 简单够用 |
| **Phase 2** | Markdown + SQLite 索引 | 全文搜索 + 标签过滤 | 加速检索 |
| **Phase 3** | Vector DB (Chroma/Qdrant) | Embedding 语义搜索 | 精准匹配 |
| **Phase 4** | 知识图谱 | 关系推理 | 深层复用 |

Phase 1 的设计已经为后续升级留好接口：`search_memory` 方法签名不变，底层实现可替换。

---

### 10.12 Session 数据持久化

除了记忆模块，每个 session 的运行数据也需要持久化（同 v1.0 设计，保持）。

```python
class Session:
    id: str                          # 唯一会话 ID
    created_at: datetime
    updated_at: datetime
    state: SessionState              # 当前状态
    original_request: str            # 用户原始需求
    
    # 迭代记录
    iterations: List[Iteration]
    
    # 中断处理
    pending_action: Optional[UserAction]
    interrupt_flag: asyncio.Event
    
    # 上下文
    context_epoch: int
    compacted_history: Optional[CompactedHistory]
    
    # 记忆引用 (新增)
    loaded_memories: List[str]       # 本次 session 加载了哪些记忆文件
    memory_writes_pending: List[MemoryWrite]  # 待写入的记忆条目

class Iteration:
    index: int
    prompt: str
    negative_prompt: str
    params: dict
    seeds: List[int]                 # 使用的种子 (v2.0 新增)
    images: List[ImageRef]
    inspection_plan: Optional[InspectionPlan]  # (v2.0 新增)
    inspection_results: List[InspectionObservation]  # (v2.0 新增)
    quality_decision: Optional[QualityDecision]      # (v2.0 新增)
    user_feedback: Optional[str]
    timestamp: datetime

class MemoryWrite:
    """待写入的记忆条目"""
    category: str                    # 目标分类 (e.g. "prompts/portraits")
    content: str                     # Markdown 内容
    reason: str                      # A 决定写入的原因 (用于审计)
    created_at: datetime
```

### 10.13 持久化文件布局

```
~/.drawagent/
├── config.yaml                     # 全局配置
├── memory/                         # 记忆模块 (Markdown)
│   ├── index.md
│   ├── prompts/...
│   ├── inspections/...
│   ├── techniques/...
│   └── failures/...
├── sessions/                       # SQLite 会话数据
│   └── sessions.db
└── outputs/                        # 生成的图像文件
    └── {session_id}/
        ├── iter_001/
        │   ├── prompt.txt
        │   ├── params.json
        │   ├── image_001.png
        │   ├── image_002.png
        │   ├── inspection_plan.json
        │   └── inspection_results.json
        ├── iter_002/...
        └── session.json
```

---

## 11. UI 设计

### 11.1 设计思路

参考 `D:\Code\Z-Image\webui_v6.html` 的 Chat-Style UI，进行以下增强：

**保留的设计**：
- 左侧会话列表
- 中间聊天区域
- 右侧/底部参数面板（可折叠）
- 图片查看器（全屏、前后导航）
- localStorage 缓存

**新增的设计**：
- **迭代状态指示器**：显示当前在第几轮迭代，每轮状态
- **审核反馈面板**：以卡片形式展示审核结果（问题列表+评分）
- **中断按钮**：显著的"停止并查看"按钮，随时可用
- **提示词对比**：展示每轮提示词的变化diff
- **版本选择器**：可以在迭代版本之间切换，选择最佳版本
- **进度预估**：显示当前操作的预估剩余时间

### 11.2 UI 布局

```
┌──────────────────────────────────────────────────────────────────────────┐
│ [侧边栏]  │                    [主聊天区域]                    │ [面板]    │
│           │                                                    │           │
│ 会话 1    │  ┌──────────────────────────────────────────────┐ │  参数     │
│ 会话 2    │  │ System: 开始第 1 轮图像生成                   │ │  ────    │
│ 会话 3 ● │  │ Agent:  我已理解您的需求，准备生成...          │ │  宽/高   │
│           │  │                                              │ │  步数    │
│ + 新会话  │  │ ┌──────┐ ┌──────┐                           │ │  ...     │
│           │  │ │ 图1  │ │ 图2  │  ← 生成结果               │ │           │
│ ⚙ 设置   │  │ └──────┘ └──────┘                           │ │  迭代    │
│           │  │                                              │ │  ────    │
│           │  │ System: 审核完成，评分 7.2/10                │ │ 第 2/5 轮│
│           │  │ ┌──────────────────────────┐                 │ │           │
│           │  │ │ 审核反馈卡片              │                 │ │  审核    │
│           │  │ │ ⚠ 头发颜色偏红           │                 │ │  ────    │
│           │  │ │ ✓ 构图符合要求           │                 │ │ 评分:7.2 │
│           │  │ │ ⚠ 背景缺少星空           │                 │ │ 元素 ○  │
│           │  │ │ 建议: 加强蓝色调，添加.. │                 │ │ 风格 ✓  │
│           │  │ └──────────────────────────┘                 │ │ 细节 ⚠  │
│           │  │                                              │ │           │
│           │  │ Agent: 已根据反馈修改提示词，正在重新生成... │ │           │
│           │  │                                              │ │           │
│           │  ├──────────────────────────────────────────────┤ │           │
│           │  │ [停止并查看] [修改方向] [接受当前]            │ │           │
│           │  │                                              │ │           │
│           │  │ ┌────────────────────────────────┐           │ │           │
│           │  │ │ 输入您的需求...         [发送] │           │ │           │
│           │  │ └────────────────────────────────┘           │ │           │
└──────────────────────────────────────────────────────────────────────────┘
```

### 11.3 WebSocket 事件驱动的 UI 更新

```javascript
// 前端 WebSocket 事件处理
ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    
    switch (msg.type) {
        case 'state_change':
            updateStatusBar(msg.state);       // 更新状态栏
            break;
        case 'iteration_start':
            addIterationCard(msg.iteration);  // 添加迭代卡片
            break;
        case 'prompt_refined':
            showPromptDiff(msg.before, msg.after);  // 显示提示词变化
            break;
        case 'image_generated':
            displayImages(msg.images);        // 显示生成的图像
            enableInterruptButtons();         // 启用操作按钮
            break;
        case 'review_complete':
            showReviewCard(msg.review);        // 显示审核结果卡片
            break;
        case 'loop_complete':
            showFinalResult(msg.result);       // 显示最终结果
            break;
        case 'error':
            showError(msg.message);
            break;
    }
};
```

---

## 12. 未来扩展计划

### 12.1 Phase 1: 核心功能（当前）

- [x] 基础三 Agent 架构
- [x] 生成-审核迭代循环
- [x] 用户中断控制
- [x] 配置化模型切换
- [x] Chat UI

### 12.2 Phase 2: Skill 系统

参考 OpenCode 的 Skill 机制，允许通过 Skill 扩展 Agent A 的能力：

```yaml
# skills/character_design.yaml
name: character_design
description: 角色设计专项技能，提供角色一致性提示词模板
prompt_template: |
  在为角色 "{character_name}" 生成图像时，请确保：
  - 面部特征一致：{face_description}
  - 服装风格：{outfit_style}
  - 体型特征：{body_type}
  - 保持与参考图的风格统一
```

Skills 可以在配置中指定，也可以由 Agent A 按需动态加载。

### 12.3 Phase 3: MCP 集成

通过 MCP (Model Context Protocol) 接入外部工具：

```yaml
extensions:
  mcp_servers:
    - name: comfyui
      command: ["python", "-m", "comfyui_mcp"]
      type: local
    - name: midjourney_api
      url: https://api.example.com/mcp
      type: remote
```

这允许接入 ComfyUI 工作流、其他图像生成 API、图库搜索等。

### 12.4 Phase 4: 高级功能

- **多图并行生成**：同一 prompt 生成多个变体，通过投票选择最佳
- **图像编辑链**：支持 inpainting、outpainting、局部修改
- **风格迁移**：提供参考图，Agent 自动提取风格并应用到新生成
- **批量生产**：批量处理多个 prompt，适合游戏素材等场景
- **角色一致性保持**：跨多个生成保持同一角色的外观一致
- **知识库**：积累成功的提示词模式，加速后续生成

---

## 13. 待讨论问题与已决策事项

### 已决策

| 问题 | 决策 | 理由 |
|------|------|------|
| 质检归属 | **A 主导，C 辅助** | A 智能更强，C 作为观察工具。A 不被 C 的能力边界限制 |
| C 的角色 | **纯 Observer**（只描述不评分） | A 是唯一的判断者，C 不产出 pass/fail/score |
| 技术栈 | **Python FastAPI + 纯 HTML** | 简洁高效，保持前后端解耦 |
| Agent 框架 | **不用 LangChain/CrewAI** | 三层抽象过重，直接 API 调用更可控 |
| 循环驱动方式 | **程序驱动的状态机** | 画图流程步骤确定，程序驱动更可控 |
| 终止策略 | **多维 LLM 主导 + 硬性上限** | 不以单一阈值判定，LLM 灵活判断 |
| 多图策略 | **轮次递减：首轮 2-4，后续 1-2** | 探索→利用的策略平衡 |
| 提示词修改 | **默认增量修改，允许 A 判断重写** | 平衡稳定性和改进幅度 |
| 前后端关系 | **完全解耦的 HTTP + WS API** | 可支持 Web/CLI/Electron 多种客户端 |

### 仍需讨论

1. **Z-Image 提示词最佳实践**：Z-Image 使用 Qwen chat template + `enable_thinking=True`，这对 prompt 设计有什么特殊要求？是否需要中英混合？是否有已知的 prompt 结构（如 tag 格式 vs 自然语言）效果更好？建议先做一些 prompt 格式的 A/B 测试来确定。

2. **框架优先策略的具体实现**：当用户要求大量变体时，"先优化一个再泛化"的框架优先策略需要 Agent A 具备"保存 prompt 模板"和"替换变量"的能力。这应该在 A 的 system prompt 中引导，还是需要专门的代码逻辑（如 PromptTemplate 类）来辅助？

3. **A 的模型选择权衡**：如果用 GPT-4o 做 A，单次 session 可能消耗 $1-3（多次迭代的 token 费用）。如果用较便宜但够用的模型（如 DeepSeek-V3、Qwen-Max），性能差距多大？是否支持 A 也配置为本地模型以降低成本？

4. **C 的回退策略**：如果 C 的观察置信度很低（如 `confidence < 0.6`），A 应该怎么处理？让 C 换个角度再看？用另一个 C 模型交叉验证？还是直接告诉用户"我不确定这个细节"？

5. **UI 的迭代版本浏览器**：当用户看到"第 2 轮比第 1 轮好，但第 3 轮不如第 2 轮"时，需要一个版本浏览器来比较和回退。这个 UI 组件的交互设计需要仔细考虑。

---

## 14. 参考

- [Building Effective Agents - Anthropic](https://www.anthropic.com/engineering/building-effective-agents)
- [OpenCode](https://github.com/sst/opencode) — Agent framework architecture reference
- [CrewAI Agents Documentation](https://docs.crewai.com/concepts/agents)
- [Model Context Protocol (MCP)](https://modelcontextprotocol.io/)
- Z-Image webui_v6.html — UI reference at `D:\Code\Z-Image\webui_v6.html`

---

> **文档版本**: v2.1 | **日期**: 2026-06-27 | **状态**: 第三轮设计，新增记忆模块
