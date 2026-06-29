# DrawAgent CLI 使用文档

## 概述

DrawAgent 提供了两个入口命令：

| 命令 | 用途 |
|------|------|
| `drawagent serve` | 启动 FastAPI Web 服务器（配合前端 UI 使用） |
| `drawagent cli` | 启动交互式命令行，适合调试和开发 |

---

## 一、`drawagent serve` — Web 服务器模式

### 基本用法

```bash
python -m drawagent serve
```

### 参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--port` | 8000 | 监听端口 |
| `--host` | 127.0.0.1 | 监听地址 |
| `--output-dir` | ./outputs | 生成图片保存目录 |
| `--config` | (自动发现) | 指定配置文件路径 |

### 示例

```bash
# 默认启动，浏览器打开 http://127.0.0.1:8000
python -m drawagent serve

# 自定义端口
python -m drawagent serve --port 8080

# 允许局域网访问 + 指定输出目录
python -m drawagent serve --host 0.0.0.0 --port 8080 --output-dir D:\images
```

### 启动后的行为

1. 启动时 **不检查** API Key — 服务器可以正常启动
2. 浏览器打开 `http://127.0.0.1:8000` 看到 Web UI
3. 用户发送第一条消息时，才检查 API Key：
   - 如果未配置 → 前端显示错误卡片："API 配置错误，请在系统设置中配置 API Key"
   - 如果配置正确 → 正常生成
4. 前端"系统设置"中修改 API Key/Base URL 会实时推送到后端，无需重启

### 配置文件

配置文件按优先级自动发现（后者覆盖前者）：
1. 包内置默认 `drawagent.default.yaml`
2. 用户全局 `~/.drawagent/config.yaml`
3. 项目目录 `.drawagent.yaml`
4. 环境变量 `${VAR_NAME}` 会在配置值中被替换

最小配置示例（`.drawagent.yaml`）：
```yaml
agent_a:
  api_key: sk-your-key-here
  api_base: https://api.deepseek.com/v1
  model: deepseek-chat

agent_c:
  api_key: sk-your-key-here
  api_base: https://api.deepseek.com/v1
  model: deepseek-chat

agent_b:
  api_base: http://localhost:8000  # Z-Image 服务器地址
```

---

## 二、`drawagent cli` — 交互命令行模式

### 基本用法

```bash
python -m drawagent cli
```

### 所有参数

#### 基础参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--output-dir` | ./outputs | 生成图片保存目录 |
| `--config` | (自动发现) | 指定配置文件路径 |

#### 持久化参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--db` | (不启用) | SQLite 数据库路径，启用后 session 会自动保存 |

#### 恢复参数（需要同时指定 `--db`）

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--resume SESSION_ID` | 无 | 从数据库恢复指定 session 继续执行 |
| `--from-iteration N` | 0 (自动) | 从第 N 轮开始恢复（跳过前 N-1 轮） |
| `--rerun-last` | false | 恢复时重新执行最后一轮（不改提示词重跑） |

#### 单步执行参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--step` | false | 启用单步执行模式，每轮迭代后暂停等待用户操作 |

---

## 三、交互命令

### 全局命令（所有模式）

| 命令 | 说明 |
|------|------|
| `/quit` | 退出程序 |
| `/help` | 显示帮助 |
| `/status` | 显示当前 session 的状态和已完成迭代 |
| 输入普通文本 | 作为图像生成需求，启动生成流程 |

### 单步模式命令（`--step` 时有效）

当 `--step` 启用时，每轮迭代结束会显示：

```
[Step] Iteration 2 complete — waiting for user
  /next (Enter) | /accept | /steer <msg> | /rollback | /quit | /status
  >
```

| 命令 | 说明 |
|------|------|
| Enter 或 `/next` | 继续下一轮迭代 |
| `/accept` | 接受当前结果，结束生成 |
| `/steer <msg>` | 修改方向，下一轮按新指令生成 |
| `/rollback` | 回退到上一轮，重新生成 |
| `/quit` | 退出步进模式，保留已完成迭代 |
| `/status` | 显示当前进度（等效于继续） |

---

## 四、使用场景与示例

### 场景1：快速开始（无持久化，无步进）

最简单的使用方式，每轮迭代自动执行直到结束：

```bash
python -m drawagent cli
```

交互流程：
```
============================================================
  DrawAgent CLI v0.1.0
  Agent A: gpt-4o
  Agent B: Z-Image-Turbo @ http://localhost:8000
  Agent C: gpt-4o
============================================================

Describe the image you want, and I'll generate it.
Commands: /quit, /help, /status

> a beautiful sunset over mountains

Processing: "a beautiful sunset over mountains"
----------------------------------------
  >>> Iteration 1 started
  [Generate] Calling Agent B...
  [Image] gen_1719000000_01_42.png (seed=42, 1024x1024)
  [Inspect PASS] check_quality
  [Quality PASS] All checks passed, image meets quality requirements.
  *** Loop ended: quality_passed ***
Result: quality_passed
Iterations: 1
Final images:
  D:\Code\DrawAgent\outputs\gen_1719000000_01_42.png
----------------------------------------

> /quit
Goodbye!
```

**注意**：此模式下 session 不持久化，退出后无法恢复。如果需要断点继续，请使用 `--db`。

---

### 场景2：持久化调试（`--db`）

启用数据库持久化，每次生成都会保存到 SQLite：

```bash
python -m drawagent cli --db ~/.drawagent/debug.db
```

```bash
# 第一次执行
> a cat sitting on a windowsill, golden sunlight
Processing: "a cat sitting on a windowsill, golden sunlight"
----------------------------------------
  >>> Iteration 1 started  [...]
  >>> Iteration 2 started  [...]
  *** Loop ended: quality_passed ***
----------------------------------------

> /status
Session: cli-20260629-153022
State: idle
Iterations: 2
  Iter 1: FAIL | a cat sitting on a windowsill...
  Iter 2: PASS | a cat sitting on a windowsill, improved lighting...

> /quit
```

---

### 场景3：断点恢复（`--resume`）

继续上次未完成的 session：

```bash
# 查看有哪些 session 可以恢复（先启动看看输出，或直接用 --resume 不存在的 ID 会列出所有）
python -m drawagent cli --db ~/.drawagent/debug.db --resume not-exist

# 显示:
# Session not-exist not found in database
# Available sessions:
#   cli-202606... | draw a cat... | 2 iterations | state=idle

# 恢复指定 session（自动从下一轮继续）
python -m drawagent cli --db ~/.drawagent/debug.db --resume cli-20260629-153022
```

启动输出：
```
============================================================
  DrawAgent CLI v0.1.0
  Agent A: gpt-4o
  Agent B: Z-Image-Turbo @ http://localhost:8000
  Agent C: gpt-4o
  Resume: cli-20260629-153022
============================================================

Resumed session: cli-202606...
  User request: a cat sitting on a windowsill, golden sunlight...
  Completed iterations: 2
    Iteration 1: FAIL | a cat sitting on a windowsill...
    Iteration 2: PASS | a cat sitting on a windowsill, improved...
  Auto-resuming from iteration 3

Describe the image you want, and I'll generate it.
```

此时输入新需求，会从第 3 轮继续（不再重复前 2 轮）。

---

### 场景4：从指定轮数恢复（`--from-iteration`）

如果需要回到某个中间状态重新执行：

```bash
# 恢复到迭代 2 之前的状态（丢弃迭代 2+），从迭代 2 重新开始
python -m drawagent cli --db ~/.drawagent/debug.db --resume <id> --from-iteration 2
```

流程：
1. 加载 session，读取所有 iterations
2. `--from-iteration 2`：保留 iteration 1，丢弃 iteration 2 及之后
3. 从 iteration 2 开始重新执行

```bash
# 重新执行最后一轮（调试用，不改提示词重跑）
python -m drawagent cli --db ~/.drawagent/debug.db --resume <id> --rerun-last
```

`--rerun-last` ≈ `--from-iteration (len-1)`，效果是保留前 N-2 轮，从倒数第二轮开始重新生成。

---

### 场景5：单步执行（`--step`）

边看边调，每轮结束后手动决定下一步：

```bash
python -m drawagent cli --step
```

交互流程：

```
> a warrior princess portrait, oil painting style

Processing: "a warrior princess portrait, oil painting style"
----------------------------------------
  >>> Iteration 1 started
  [Generate] Calling Agent B...
  [Image] gen_1719000000_01_42.png (seed=42, 1024x1024)
  [Inspect PASS] check_composition
  [Inspect FAIL] check_anatomy
  [Quality FAIL] Hand anatomy is distorted, needs correction.

  [Step] Iteration 1 complete — waiting for user
  /next (Enter) | /accept | /steer <msg> | /rollback | /quit | /status
  >                                    # 按 Enter — 继续下一轮

  >>> Iteration 2 started
  [Refine] Prompt updated
  [Generate] Calling Agent B...
  [Image] gen_1719000001_02_43.png (seed=43, 1024x1024)
  [Inspect PASS] check_composition
  [Inspect PASS] check_anatomy
  [Quality PASS] All checks passed.

  [Step] Iteration 2 complete — waiting for user
  /next (Enter) | /accept | /steer <msg> | /rollback | /quit | /status
  > /accept                             # 接受结果，结束生成
  *** Loop ended: user_accepted ***

Result: user_accepted
Iterations: 2
Final images:
  D:\Code\DrawAgent\outputs\gen_1719000001_02_43.png
----------------------------------------
```

---

### 场景6：单步 + 持久化（调试最强组合）

```bash
python -m drawagent cli --db ~/.drawagent/debug.db --step
```

效果：
- 每次生成自动持久化到 SQLite
- 每轮暂停，可以看到 AI 质量判断后手动操作
- 不满意可以 `/steer <新方向>` 或 `/rollback` 回退
- 退出后下次可以 `--resume` 继续

---

### 场景7：单步中修改方向（`/steer`）

```
  [Step] Iteration 2 complete — waiting for user
  > /steer make the lighting more dramatic and add a dark background

  >>> Iteration 3 started
  [Refine] Prompt updated
  [Generate] Calling Agent B...
  ...
```

`/steer` 的效果：下轮迭代的提示词会融入用户补充的要求，同时 Agent A 会根据检查结果自动 refinement。

---

### 场景8：单步中回退（`/rollback`）

```
  [Step] Iteration 3 complete — waiting for user
  > /rollback

  >>> Iteration 2 started       # 回退到上一轮重新生成
  ...
```

`/rollback` 的效果：丢弃当前轮的结果，回到上一轮状态重新生成。

---

## 五、循环事件输出说明

CLI 运行时，每轮迭代会打印以下事件：

```
  >>> Iteration 1 started           # 迭代开始
  [Refine] Prompt updated           # 提示词被优化（仅迭代 2+）
  [Generate] Calling Agent B...     # 调用图像生成
  [Image] filename (seed=42, 1024x1024)  # 生成完成，保存路径
  [Inspect PASS/FAIL] task_name     # 每个检查项的结果
  [Quality PASS/FAIL] reasoning     # Agent A 的质量判断
  *** Loop ended: reason ***        # 循环结束原因
```

结束原因（`terminated_reason`）可能是：
- `quality_passed` — 质量达标
- `auto_accepted` — 置信度超过阈值自动接受
- `user_accepted` — 用户在步进模式中手动接受
- `max_iterations` — 达到最大迭代次数
- `generation_error` — 生成过程出错
- `generation_failed` — Agent B 无输出
- `awaiting_user` — 等待用户确认
- `user_quit` — 用户退出

---

## 六、与前端 UI 的对应关系

CLI 中每个操作在前端 UI 中的对应位置：

| CLI 操作 | 前端操作 |
|----------|---------|
| 输入需求文本 | 底部输入框 + 发送按钮 |
| `/step` 步进模式 | 系统设置 → 尚未实现 UI 按钮（可通过 CLI 调试） |
| `/steer <msg>` | 生成中 → "修改方向" 按钮 |
| `/accept` | 生成中 → "接受" 按钮 |
| `/rollback` | 对比视图 → "回退到此" 按钮 |
| `/status` | 侧边栏 → 会话信息 |
| `/quit` | 关闭浏览器标签 |
| `--resume` | 侧边栏 → 点击已有会话 |
| 每轮事件输出 | 前端 WebSocket → 消息卡片 |

---

## 七、配置文件完整参考

```yaml
# .drawagent.yaml — 完整配置示例

# Agent A: 主 LLM（写提示词、规划检查、质量评估）
agent_a:
  provider: openai           # 提供商（任意 OpenAI 兼容 API）
  model: gpt-4o              # 模型名
  api_base: https://api.openai.com/v1
  api_key: ${OPENAI_API_KEY} # 支持环境变量替换
  temperature: 0.7
  max_tokens: 4096

# Agent B: 图像生成（HTTP API 或 MCP）
agent_b:
  type: http                 # http 或 mcp
  provider: local_zimage
  model: Z-Image-Turbo
  api_base: http://localhost:8000
  endpoint: /api/generate
  # MCP 模式：
  # type: mcp
  # mcp_command: ["python", "D:\\Code\\Z-Image-MCP\\mcp_server.py"]
  default_params:
    width: 1024
    height: 1024
    steps: 8
    guidance: 3.5
    seed: -1

# Agent C: 视觉审查（多模态 LLM）
agent_c:
  provider: openai
  model: gpt-4o
  api_base: https://api.openai.com/v1
  api_key: ${OPENAI_API_KEY}
  temperature: 0.3
  max_tokens: 2048

# 控制循环行为
loop:
  max_iterations: 7
  auto_accept_threshold: 8.0     # 置信度 ≥ 8.0 自动接受
  compaction_threshold_tokens: 20000  # 上下文压缩阈值
  keep_recent_iterations: 2      # 压缩后保留最近 N 轮
  step_mode: false               # 是否默认启用单步执行

# 记忆模块
memory:
  base_dir: ~/.drawagent/memory
  auto_load: true
  auto_save: false
```
