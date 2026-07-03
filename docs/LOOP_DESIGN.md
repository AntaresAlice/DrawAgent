# DrawAgent Loop 架构演进设计

> 基于 opencode 的 LLM 驱动 loop 思想，重新设计 DrawAgent 的对话与生成循环。
> 本文档记录设计方案，供讨论、批判、反复迭代后进入实现。

---

## 一、当前架构的问题

```
用户 → [Phase 0 澄清] → [Phase 1 规划] → [Phase 2 修改提示词]
     → [Phase 3 生图] → [Phase 4 逐图检查] → [Phase 5 评估]
     → (不合格 → 循环) / (合格 → 结束)
```

问题：

| # | 问题 | 表现 |
|---|------|------|
| 1 | **程序固定阶段，LLM 没有控制权** | Phase 4 逐图检查 30 分钟，LLM 看到了也没法跳 |
| 2 | **用户中断只能全局暂停，不能跳到指定阶段** | 用户说"跳过检查直接改提示词"，程序做不到 |
| 3 | **用户第二句话是"反馈"还是"新需求"，靠硬编码判断** | 不精确，且 LLM 没有被咨询 |
| 4 | **原始 user_request 被覆盖** | 发送第二条消息后，第一条的需求丢失 |
| 5 | **上下文只在 Phase 2 注入上一轮的 issues，LLM 看不到全貌** | LLM 不知道整个 session 发生了什么 |
| 6 | **没有"学习"(accumulate lessons)** | 第 1 轮发现"需要更细化"，第 2 轮又犯同样错误 |

---

## 二、opencode 的核心设计思想

opencode 没有固定阶段。它的 loop 模型是：

```
┌─────────────────────────────────────────────────────────┐
│                    Session Context                        │
│  [所有历史消息: 用户输入 + LLM 回复 + 工具结果 + 压缩摘要]     │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│              while (needs_continuation):                 │
│    LLM 流式推理 →                                        │
│      ├─ 返回 text → 展示给用户, 检查是否需要继续            │
│      └─ 返回 tool_calls → 执行工具 → 注入结果 → 继续循环    │
│                                                          │
│    User delivers "steer" → 注入为下一条 user 消息 → 继续   │
│    Context overflows → compaction → 压缩旧 turns 为摘要    │
└─────────────────────────────────────────────────────────┘
```

**关键设计:**

| 概念 | 说明 |
|------|------|
| LLM 全权决策 | LLM 自己决定调用什么工具、什么时候停下来、什么时候跟用户说话 |
| 消息历史永不覆盖 | 每条 user/assistant/tool 消息永久保留，压实是压缩为摘要而非删除 |
| steer vs queue | steer = 注入当前 loop（默认），queue = 等当前工作完后新开 |
| 上下文压缩 | token 超限时自动将旧 turns 压缩为 LLM 摘要，保留最近 N 轮完整内容 |
| 没有"阶段"概念 | 程序不强制要求 LLM 先 plan 后 generate，LLM 可以随时跳到任何步骤 |

---

## 三、用户场景推演

以下场景必须被设计覆盖，不能靠硬编码打补丁：

### 场景 1: 中途中断 + 跳到指定阶段

```
用户: "画一位穿着婚纱的少女"              → Agent 开始循环
Agent: [Phase 1] 规划检查项...           → 用户看日志
Agent: [Phase 3] 正在生成图片...          → 用户等不及了

用户中断: "快点，不要再检查了，根据已有检查结果修改提示词重新生成"

期望行为:
  Agent 理解: 当前在 Phase 3，但 Phase 2 的检查已经有结果
  Agent 跳过: Phase 3 剩余 + Phase 4 全部
  Agent 跳到: Phase 2 (refine prompt) → Phase 3 (regenerate)
```

### 场景 2: 用户中途发现提示词有遗漏

```
Agent: [Phase 3] 正在生成第 2/4 张图片...

用户中断: "哎呀，我提示词漏了'背景是江南水乡'，加上去"

期望行为:
  Agent 理解: 当前在 Phase 3 中段
  Agent 停止: 当前生成（已生成的图片保留但标记为旧）
  Agent 跳到: Phase 2 (修改提示词，加入"背景是江南水乡")
  Agent 继续: Phase 3 (重新生成)
```

### 场景 3: 用户不满意 LLM 的判断，要求重新检查

```
Agent: [Phase 5] 评估: 质量通过 (confidence 8/10)
  → 检查结论: "手部细节模糊" — 但已通过

用户中断: "不对，手指明显畸形，你没认真看。重新检查这张图"

期望行为:
  Agent 理解: Phase 5 结论被用户质疑
  Agent 跳到: Phase 4 (重新 inspection，focus on hand anatomy)
  Agent 继续: Phase 5 (重新评估)
```

### 场景 4: 用户完全换个话题

```
Agent: [Phase 5] 上一轮完成，展示婚纱少女图片

用户: "不错，现在帮我画一只在森林里的白虎"

期望行为:
  Agent 理解: 这是新请求，不是改进
  Agent 处理: 保留上一轮结果，开始新的生成循环
  上一轮的上下文对新的生成仍有参考价值（prompt 写法、参数选择）
```

### 场景 5: Agent 从历史中学习

```
第 1 轮: prompt 不够细化 → 检查发现"缺乏纹理细节"
第 2 轮: Agent 看到第 1 轮的问题 → 自动在 prompt 中加入"精细纹理、皮肤质感可见"
第 3 轮: 同样的问题又出现了 → Agent 应该意识到"细化"不只是加形容词，
          可能需要改变构图/光照 → 而不是重复同样的修补方式

期望行为:
  Agent 的 system prompt / 上下文包含一种"经验积累"机制
  - 检查维度可以动态调整（第 1 轮主要看构图，第 2 轮重点看纹理）
  - 失败的模式被记住（"加形容词不够，需要改变构图"）
  - 成功的策略被重用（"上次用侧逆光解决了皮肤的塑料感"）
```

---

## 四、新架构设计

### 核心理念: LLM 驱动的循环 + 程序提供 guardrails

```
                    ┌──────────────────────────┐
                    │     Session Context        │
                    │  ├─ 全部用户消息 (不覆盖)    │
                    │  ├─ 全部 Agent 回复         │
                    │  ├─ 全部工具调用结果         │
                    │  ├─ 压缩摘要 (旧 turns)      │
                    │  └─ 经验积累 (learned)       │
                    └──────────────────────────┘
                                ↓
┌─────────────────────────────────────────────────────────────────┐
│                       Agent Loop (LLM-driven)                     │
│                                                                    │
│   while True:                                                      │
│     ┌─ 检查是否有新的 steer/queue 用户消息                          │
│     ├─ 构建完整 system prompt (含当前状态 + 可用工具 + 经验)         │
│     ├─ 发送给 LLM 流式推理                                         │
│     ├─ LLM 返回:                                                   │
│     │   ├─ text → 展示, 检查 finish_reason                         │
│     │   └─ tool_calls → 执行工具 → 注入结果 → 继续                 │
│     ├─ 如果 finish="stop": 评估是否真正完成                         │
│     │   ├─ 图片已生成 + 质量合格 → 真正结束                          │
│     │   └─ 图片未生成/质量不够 → 重新触发 LLM (带反思)               │
│     └─ 用户中断到达 → 转为下一条 user 消息 (steer) → 继续循环        │
│                                                                    │
│   程序 Guardrails (不控制流程，只在危险时介入):                       │
│     ├─ max_iterations 上限 → 超过时询问用户                         │
│     ├─ token overflow → 触发压缩                                    │
│     ├─ 连续 N 次没生成有效图片 → 警告用户                           │
│     └─ API key 过期 / 网络错误 → 优雅退出                          │
└─────────────────────────────────────────────────────────────────┘
```

### 关键设计细节

#### 4.1 没有固定阶段，但有"状态标注"

不强制 LLM 走 Phase 1→2→3→4→5，但在 system prompt 中告诉它：

```
## Current Session State
- User request: "画一位穿婚纱的少女"
- Iterations completed: 2
- Last iteration result: 质量不通过 — 皮肤质感塑料 (confidence 6/10)
- Last iteration issues:
  [FAIL] texture_detail: 皮肤缺乏纹理细节，面部过于光滑像塑料
  [PASS] spatial_accuracy: 所有元素位置正确
  [PASS] composition: 构图良好
- Generated images: 4 images in output/iter_2/
- Pending user feedback: "换成侧逆光，皮肤要能看见毛孔"
```

LLM 看到这些状态标注后，自己决定下一步做什么。它应该自然地跳到"修改提示词 → 重新生成"，不需要程序命令它进入 Phase 2。

#### 4.2 用户消息模型 (借鉴 opencode)

```python
@dataclass
class UserMessage:
    id: str
    text: str
    delivery: Literal["steer", "queue"]  # steer=反馈, queue=新请求
    created_at: datetime

# Session 中
class Session:
    user_request: str  # 第一条消息，永远不变
    messages: list[UserMessage]  # 所有消息
    iterations: list[Iteration]
    learned_lessons: list[str]  # 经验积累
```

**delivery 如何决定:** Agent A 在收到新消息时，自己判断它是 steer 还是 queue。程序不替 LLM 做判断，但如果 LLM 判断为 queue，则重置生成上下文（保留对话历史）。

#### 4.3 中断机制

当前的中断只是 pause/resume。新的中断应该是：

```
用户输入 → 前端发送 {type: "interrupt", action: "steer", message: "跳过检查直接修改提示词"}
后端收到 → 转为一条新的 UserMessage(delivery="steer")
Agent Loop → 在当前 LLM 请求完成后，将新消息注入上下文
LLM → 看到新消息 + 当前状态 → 自己决定跳到哪个步骤
```

不再需要 `session.pending_action = "steer"` + `interrupt_event.set()` 这种复杂机制。就是一条普通消息，LLM 自己看着办。

#### 4.4 工具枚举

当 LLM 可以从任何入口点调用任何工具时，工具设计变得关键：

```
generate_image(prompt, negative_prompt, width, height, steps, guidance, seed, num_images)
  → 生成图片，返回图片路径列表

inspect_image(image_path, task_description)
  → 对单张图片执行检查，返回 Pass/Fail + observation

compare_images(image_path_1, image_path_2, questions)
  → 对比两张图片，返回比较结果

load_memory(category) / save_memory(category, data) / search_memory(query)
  → 记忆系统：积累经验、检索历史

# 新增工具：
finalize(accepted_images: list[str], reason: str)
  → LLM 明确告诉系统"我认为任务完成了，这是最终结果"
  → 程序据此退出 loop，而不是靠硬编码的 decision.passed
```

**所有工具在任何时候都可用**。LLM 可以先生成再检查，也可以先检查再生成，也可以一边生成一边检查。程序不再限制 `enabled_tools`。

#### 4.5 经验积累 (Learning)

```
[系统维护一个 learned_lessons 列表]

第 1 轮完成后:
  LLM 对本次生成做反思:
    "prompt 中缺乏对皮肤质感的描述导致塑料感"
  → 调用 save_memory("learned/skin_texture", "在 prompt 中加入具体的皮肤质感描述词,
      如'毛孔可见'、'自然肌肤纹理'，并用侧逆光增强立体感")
  → system prompt 中注入:
      ## Lessons Learned
      - skin_texture: 在 prompt 中加入具体的皮肤质感描述词...

第 2 轮:
  system prompt 包含 lessons learned
  LLM 看到 → 在写 prompt 时自动加入侧逆光 + 纹理描述
  → 生成的图片皮肤质感改善
```

#### 4.6 上下文压缩

借鉴 opencode 的 compaction 机制：

```
when token_count > threshold:
  取最老的 N 个 turns (user + assistant 对)
  发送给轻量级 LLM:
    "Summarize the following conversation while preserving:
     1. The original user request
     2. Key decisions made (prompt changes, parameter choices)
     3. What was tried and what worked/failed
     4. Any explicit user feedback"
  摘要存储为 CompactionPart
  保留最近 2 个 turn 的完整内容
```

---

## 五、场景覆盖验证

### 场景 1: 中途中断 + 跳到指定阶段

```
1. LLM 正在执行 generate_image (返回 tool_calls)
2. 用户 steer: "快点，不要再检查了，根据已有检查结果修改提示词重新生成"
3. 当前 LLM 请求完成 → 新 UserMessage(delivery="steer") 注入
4. LLM 看到:
   - 当前状态: 第3轮, 刚生成了4张图, 上一轮检查有 issues
   - 用户新消息: "不要再检查了，根据已有检查结果修改提示词"
   - 可用工具: generate_image, inspect_image, compare_images, finalize
5. LLM 自主决策:
   - 不调用 inspect_image (因为用户说不要检查)
   - 基于上一轮的 issues 写出改进的 prompt → 调用 generate_image
   - 生成完成后调用 finalize
```

### 场景 2: 漏了提示词内容

```
1. LLM 正在执行 generate_image(第2张/共4张)
2. 用户 steer: "漏了'背景是江南水乡'，加上去"
3. 当前 generate_image 完成后 → 已有 2 张图 (旧 prompt)
4. 新 UserMessage 注入
5. LLM 看到:
   - 当前状态: prompt 中缺少背景描述
   - 用户要求加入背景
6. LLM 自主决策:
   - 已生成的2张图标记为"旧 prompt 产物"
   - 构造新 prompt: 原 prompt + "背景是江南水乡，青砖白墙、小桥流水"
   - 调用 generate_image(新 prompt, num_images=4) 重新生成
```

### 场景 3: 质疑 LLM 判断

```
1. LLM 调用了 finalize(accepted_images=[img1, img2], reason="质量通过")
2. 但程序检查: 上一轮 inspection 中 anatomy 未通过
3. 程序拒绝 finalize → 注入一条 system 消息: "Cannot finalize: previous inspection failed on anatomy (手指畸形)"
4. 同时用户 steer: "手指明显畸形，重新检查"
5. LLM 看到: system 拒绝 + 用户要求 → 知道自己之前的判断有问题
6. LLM 自主决策: 调用 inspect_image(img1, "hand anatomy detail check")
   → 发现确实畸形 → 修改 prompt (加入 hand-specific negative prompt)
   → 调用 generate_image → 重新检查 → finalize
```

### 场景 5: Agent 从历史中学习

```
第 1 轮: issues = ["texture_detail: 皮肤缺乏纹理"]
  → LLM 写入 learned: "portrait: add 'natural skin texture, visible pores'"
第 2 轮: 同样 issues 出现但程度减轻
  → LLM 更新 learned: "portrait: texture needs more than adjectives; use side-lighting to enhance depth"
第 3 轮: system prompt 中包含 accumulated lessons
  → LLM 看到之前的尝试和反馈 → 换策略而不是重复同样的修补
  → 成功 → 标记此 lesson 为有效
```

---

## 六、实现路径

### 阶段 1: 消息模型重构 (P0)

- [ ] `Session` 增加 `messages: list[UserMessage]`，保留所有用户输入
- [ ] `Session.user_request` 永远不变（存第一条消息）
- [ ] 用户中断消息以 `UserMessage(delivery="steer")` 形式注入
- [ ] Agent A 在收到新消息时，LLM 判断 deliver="steer" or "queue"

### 阶段 2: LLM 驱动循环 (P0)

- [ ] 移除固定的 5-phase 状态机
- [ ] Agent loop 改为 `while True` 模式，LLM 全权决策
- [ ] 所有工具在所有时候可用 (`enabled_tools` 概念移除)
- [ ] 新增 `finalize` 工具，让 LLM 明确终止
- [ ] 程序 guardrails: max_iterations, token overflow compaction, error handling

### 阶段 3: 中断改造 (P1)

- [ ] 弃用 `pending_action` + `interrupt_event` 机制
- [ ] 中断转为普通的 UserMessage (delivery="steer")
- [ ] 前端"接受/暂停/修改方向"按钮改为发送 steer 消息

### 阶段 4: 经验积累 (P2)

- [ ] System prompt 注入 `## Lessons Learned` 段
- [ ] LLM 在每轮结束后调用 `save_memory` 写入经验
- [ ] 后续轮次的 system prompt 自动包含累计经验

### 阶段 5: 上下文压缩 (P2)

- [ ] 实现 opencode 风格的 compaction
- [ ] 自动检测 token overflow
- [ ] 发送旧 turns 给 LLM 生成摘要
- [ ] 摘要存储为 CompactionPart

---

## 七、风险与缓解

| 风险 | 缓解 |
|------|------|
| LLM 自主权太大，可能做出坏决策 | Guardrails 保留：max_iterations, token limit, 连续失败检测 |
| 移除 enabled_tools 后 LLM 可能乱调工具 | 工具描述中明确使用场景，LLM 本身有判断力 |
| LLM 不调 finalize 导致死循环 | max_iterations + 程序超时检测 |
| 上下文压缩导致关键信息丢失 | 保留最近 N 轮完整内容，压缩旧轮次前验证关键节点 |
| 经验积累可能引入偏见 | 经验的格式是"观察+成功策略"，不强制 LLM 遵守 |
