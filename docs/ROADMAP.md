# DrawAgent 路线图

> 已积累的未来开发计划。按优先级分短期/中期/长期。

---

## 短期优化 (性能瓶颈)

### 1. MCP 模型冷启动消除

**现状:** keep_alive=false 导致每个迭代间 MCP 被杀再重启，Z-Image 模型重载 GPU 每次耗时 ~260s。
3次迭代 = 2次冷启动 = ~520s 白白浪费。

**方案:**
- keep_alive 改为迭代间保持 (仅在迭代完成 / Agent C 需要 GPU 时才释放)
- 或: Phase 4 inspection 期间 MCP stay alive，Phase 3 直接复用
- Phase transition 时智能管理: Generation 阶段 MCP 常驻 → Inspection 阶段 MCP 可释放

**预期收益:** 60min → ~42min (省 ~30%)

### 2. 工具并行调用

**现状:** Phase 4 每张图的每次检查是 `DeepSeek → qwen → DeepSeek` 三段式串行往返。
74次 DeepSeek + 70次 qwen 全部顺序执行。

**方案:**
- Agent A 在一次 turn 中连续发出多个 inspect_image (如 batch 3张)
- DeepSeek 只需发一次令 → qwen 并行或队列执行3张 → DeepSeek 一次收结果
- 74次 DeepSeek 调度调用 → ~25次

**预期收益:** DeepSeek 调用砍 2/3，Phase 4 从 ~32min → ~15min

### 3. Inspection 预算控制

**现状:** 每轮检查 ALL 图片 × ALL 维度 (6张×5维度=30次)，其中很多检查冗余。

**方案:**
- System prompt 中添加"每轮每维度最多检查 3 张图 (best/worst/random)"
- 或: Phase 1 设计检查计划时，Agent A 根据图片质量自行决定重点查哪几张
- 后期检查加 compare_images 批量对比 (不用逐张 VLM)

### 4. 非交互模式跳过 Phase 0

**现状:** Phase 0 有 120s 的 `asyncio.wait_for` 等待用户确认，非交互模式下白白浪费2分钟。

**方案:** 非交互模式 (e2e_run / CLI --non-interactive) 直接跳过 Phase 0 的 clarify 调用。

### 5. VLM 上下文优化

**现状:** 384px resize + keep_alive=0 缓解了 qwen3.5:9b 的空响应，但仍有 ~20% 的空响应率。

**方案:**
- 换用更大上下文的视觉模型 (qwen2.5-vl:72b 或本地部署的更大模型)
- 或: 将 qwen 升级到 qwen3:14b (有 128K 上下文)

### 6. 系统提示词增强：变体识别 + 模糊指令展开

**现状:** Agent A 只在提示词中出现 `/` (斜杠) 时才拆分为多个变体生成。遇到自然语言的"或者"、"或是"、"要么...要么"不会拆分。同时，"自拟"、"细节化"、"自由发挥"等模糊指令也不会主动展开补充。

**症状:**
- 用户写"挤坐在酒桌旁闲聊或者转头温柔地看镜头" → Agent A 判定为"无变体"，只生成一种姿势
- 用户写"背景自拟细节化" → Agent A 原样保留，不加具体细节
- 两种能力缺失导致生成的图片缺乏多样性和丰富性

**这种能力是 Agent A 的核心价值**——LLM 应该能理解自然语言的组合语义，并将模糊需求转化为具体的、可执行的画面描述。

**方案:**
- **自然语言变体识别**: system prompt 教会 Agent A 识别中文中的隐含变体标记：
  - `或者` / `或` → 和 `/` 同义，需要拆分组合
  - `要么...要么...` → 二选一或多选一
  - `可以...也可以...` → 多种选项
  - 枚举列表 (`A、B、C`) → 多个独立选项
- **模糊指令展开**: system prompt 教会 Agent A 将模糊指令变为具体画面描述：
  - `自拟` / `自由发挥` → 选择具体风格、元素、构图并写入 prompt
  - `细节化` → 补充材质、光影、环境等具体描写
  - `有氛围感` → 添加具体的光影、色调描述
- 在 prompt refine 阶段（Phase 2），Agent A 应主动检查和修正这些问题

**文件:** `src/drawagent/agents/prompts.py` BASE_SYSTEM_PROMPT

---

## 中期特性

### 6. Agent Skill 系统

**参照:** opencode 的 skill 架构

**方案:**
- `skills/` 目录结构，Markdown + YAML frontmatter
- SkillLoader 发现和解析
- `load_skill` 工具 (Agent A 按需加载)
- System prompt 注入可用技能列表
- 首批技能: `Z-Image.md`, `portrait-inspection.md`, `scene-inspection.md`

### 7. MCP 多模型支持

**方案:**
- MCP server 支持 `--model` 参数 (Z-Image vs Z-Image-Turbo)
- TOOL_SCHEMA 根据加载模型动态调整
- MCP resource: `get_model_info` → Agent A 查询可用模型和推荐参数

### 8. MCP info/status 接口

**方案:**
- MCP resource: `get_model_info` — 模型名、版本、推荐参数
- MCP resource: `get_status` — 空闲/忙碌/异常
- DrawAgent session 开始时查询 model info

### 9. 提示词模板库 (Memory System 演进)

**方案:**
- 积累有效的提示词模板 (portrait, landscape, product, ...)
- 积累成功的 negative_prompt 组合
- 积累检查维度清单 (per-domain)
- Memory system 自动推荐相关模板

---

## 长期架构

### 10. 多模态用户输入 (用户可输入图片+文字)

**背景:** 用户输入一张图 + 文字描述，要求生成类似但不同的人/场景/风格。

**根据模型配置的三种路径:**

| 场景 | Agent A | Agent B | 流程 |
|------|---------|---------|------|
| A纯文字, B纯生成 | 仅文字 | 仅生成 | A → C(VLM看图) → A理解 → 写prompt → B生成 → C检查 |
| A纯文字, B支持输入+编辑 | 仅文字 | 支持img2img | A → B(直接传图生成) → C检查 |
| A支持图片输入 | 多模态 | 任意 | A 自行看图理解 → 编排生成 → A 自行看图检查(跳过C) |

**实现要点:**
- Agent A provider 抽象层支持图片输入 (当前仅文本)
- `LLMMessage` 支持 content 为 `list[dict]` (OpenAI vision 格式)
- Loop 支持 `initial_images` 参数传入用户图片
- Phase 0 clarifiation 阶段: 如有输入图片，Agent A 看图后提问

### 11. Vision-capable Agent A (跳过 Agent C)

**背景:** 如果 Agent A 是 GPT-4V / Claude / Gemini 等多模态模型，可以：
- 直接看用户输入的图片
- 直接检查生成的图片 (不需要 Agent C / qwen)
- 消除 `DeepSeek调度 → qwen分析 → DeepSeek读结果` 三段式往返

**收益:**
- 消除 Agent C 的 70次 qwen VLM 调用 (~9 min)
- 消除 74次 DeepSeek 调度调用 (~9 min)
- Inspection 从 ~30 min → Agent A 一次看多图 (< 1 min)
- 检查更精准: Agent A 知道 prompt 意图，判断"是否匹配"比 VLM 更强
- 架构从 3-agent 简化为 2-agent (A多模态 + B生成)

**实现要点:**
- `OpenAICompatibleProvider.analyze_image()` 已存在 (可复用)
- Agent A 的 `run_turn` 需要支持 vision content
- Loop 的 inspection 阶段: 直接调 `agent_a.run_turn(images=[...], instruction="检查这几张图")`
- Agent C 作为 fallback (当 Agent A 不支持 vision 时)

### 12. 多 Agent B 支持 (多生成模型)

**背景:** 同时支持 Z-Image, Z-Image-Turbo, SD3, ComfyUI, ...

**方案:**
- Agent B 统一接口 (MCP 或 HTTP)
- `AgentBRegistry` 管理多个 B 实例
- Agent A 根据任务选择: "人像用 Z-Image，风景用 SD3"
- 工具名 `generate_image` → `generate_image_zimage` / `generate_image_sd3`

---

## 优先级排序

```
P0 (本周):   系统提示词增强(变体识别+模糊展开) + MCP冷启动消除 + 非交互模式跳过Phase0
P1 (下周):   工具并行调用 + Inspection预算控制
P2 (本月):   Skill系统 + MCP多模型
P3 (季度):   多模态输入 + Vision-capable Agent A
P4 (远期):   多Agent B + Memory模板库
```
