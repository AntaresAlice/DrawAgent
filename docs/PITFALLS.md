# DrawAgent 开发避坑纪要

> 记录踩过的坑、用户批评、设计原则。每次犯同样错误前先读一遍。

---

## 核心设计原则

### 1. 生成模型解耦合
- **工具 schema（代码）只描述参数是什么**——类型、含义。不写 "Recommended: 20-40"。
- **模型具体知识放 config**——model_hints / default_params，换模型只改 yaml 不改 .py。
- **MCP server 的 TOOL_SCHEMA 是模型侧的 truth**——客户端不应硬编码重复信息。
- 反面案例：把 Z-Image 的 steps=20-40 写死在 generate_image.py 的 schema 描述里。

### 2. 让 LLM 做决策，不要替它做
- Loop 指令应该用 "Generate images now. If variations exist, call multiple times"，而不是 "Call generate_image"（单数）。
- negative_prompt 应该由 LLM 根据具体场景组合——不是硬编码一个中文默认值。
- 用户提供的 params.json 是**参考**，不是**答案**。LLM 应根据上下文灵活调整。

### 3. 解决根因，不修症状
- 组合枚举失效→不是 system prompt 的问题，是 loop 指令把 LLM 框死了。
- negative_prompt 没生效→不是缺默认值，是 LLM 不知道推荐的基值是什么（应在 tool schema 描述或 model_hints 中说明）。
- 不要用户指一个 bug，你修一个补丁。从设计层看全貌。

---

## 踩过的具体坑

### verbose_log 浅拷贝污染
- `dict(result)` 是浅拷贝，共享 content list 中的 item dict。
- 修改 `item["data"]` 为 `<base64, N bytes>` 影响了调用方。
- 修：`copy.deepcopy(result)`。

### Ollama 多图上下文耗尽
- qwen3.5:9b 的 32K 上下文装不下两张 1.6MB 原图（base64 ~2.1M chars/张）。
- 384px resize + keep_alive=0 可缓解。
- 根因：视觉 token 编码效率问题，短期压缩+长期换大上下文模型。

### DeepSeek v4 streaming tool_calls
- `id` 字段仅首 chunk 有值，后续参数 chunk 的 `id: null`。
- 必须用 `index` 做 key 累积，首 chunk 的 `id` 只用于 yield 事件。
- 需要 assistant 消息（含 tool_calls）+ tool 消息的完整顺序。

### Windows MCP stdio
- `connect_read_pipe` 在 Windows 上 OSError(6)。
- 修：`run_in_executor(sys.stdin.readline)` + `subprocess.Popen`。
- stderr 必须 DEVNULL，否则 pipe buffer 满导致死锁。

---

## 用户批评要点
不要打补丁，要通盘 audit 后再改
---

## 关键文件职责

| 文件 | 职责 | 不负责 |
|------|------|--------|
| `generate_image.py` | 参数定义（名字、类型、含义） | 模型推荐值 |
| `config.example.yaml` model_hints | 模型特定知识（参数推荐、写法技巧、弱点） | 通用逻辑 |
| `loop.py` | 流程编排（阶段切换、指令发送） | 具体生成策略 |
| `agent_a.py` | LLM 对话管理（run_turn、tool settle） | 领域知识 |
| `prompts.py` | 通用行为规则（检查标准、写作规范） | 模型参数 |
| MCP `TOOL_SCHEMA` | 模型真实的参数约束和推荐 | 客户端逻辑 |

---

## 文档规范

- `docs/CHANGELOG.md`：实现文档，发布用。
- `temp/WALKTHROUGH_*.md`：测试记录（先原文后评论）。
- `temp/runs/`：原始日志文件。
- 不要往 docs/ 放测试记录。

---

## 新增发现 (2026-07-01 第二次运行)

### 5. 系统prompt没有被注入到loop的LLM调用

**症状:** log中 `Messages (1)` — loop发起的每次Agent A调用只含user消息，无system消息。
**根因:** loop直接构造 `[LLMMessage(role="user", content=...)]` 传给 `run_turn()`，完全绕过了
`ContextAssembler._build_system_prompt()` 构建的系统提示词。
**影响:**
- 语言匹配规则未生效（中文prompt→英文输出）
- model_hints（参数推荐、resolution建议）完全没用
- 所有prompt写作指南未传达给LLM
**修复方向:** loop应调用 `assembler.assemble_current_turn(session, instruction)` 来构建消息，
该方法会在user消息前插入system prompt（含BASE_SYSTEM_PROMPT + model_hints + MEMORY_USAGE_GUIDE）。

### 6. inspect_image逐张检查耗时爆炸

**症状:** 8张图×3个检查维度=24次vision调用，超时未完成1次迭代。
**改进方向:**
- 不检查全部图片——只检查"best"和"worst"各一张，或最多3张
- 使用compare_images来批量化质量对比
- 考虑让inspect_image一次传入多个图片路径

### 7. qwen3.5:9b连续空响应

**症状:** 多张图片的VISION RESPONSE为0 chars，尤其在后期spatial_low_angle和anatomy检查中。
**可能原因:** Ollama KV cache在多轮图片调用中耗尽（每个图片base64 ~1.7MB，远超上下文容量）。
**现有缓解:** 384px resize + keep_alive=0（仅用于compare_images），单图inspect仍用原图。

