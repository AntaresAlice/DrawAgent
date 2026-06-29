# DrawAgent CLI 使用文档

## 概述

DrawAgent 提供三个入口命令：

| 命令 | 用途 | 交互方式 |
|------|------|---------|
| `drawagent run` | 非交互式一次性生成 | 命令行参数传入 |
| `drawagent cli` | 交互式命令行 REPL | 终端逐条输入 |
| `drawagent serve` | 启动 FastAPI Web 服务器 | 浏览器前端 UI |

---

## 通用选项：`--config`

**所有命令**都支持 `--config PATH`，指定一个 YAML 配置文件（最高优先级覆盖）：

```bash
drawagent serve --config my_config.yaml
drawagent cli --config my_config.yaml
drawagent run "a cat" --config my_config.yaml
```

配置加载优先级（后者覆盖前者）：
1. 包内置默认 `drawagent.default.yaml`
2. 用户全局 `~/.drawagent/config.yaml`
3. 项目目录自动发现 `.drawagent.yaml`
4. `--config` 指定的文件（最高 YAML 优先级）
5. `run` 命令的 CLI `--xxx` 参数（最高总体优先级，覆盖 YAML 所有值）

---

## 一、`drawagent run` — 非交互式单步/多步执行（调试核心）

设计目标：类似 gdb，精确定位到任意 session 的任意迭代，执行可控步数，
注入用户指令，Fork 分支探索。

### 核心语义（消除歧义）

**执行顺序永远是：Fork（可选）→ Trim 迭代 → 注入指令 → Execute 步数**

| 操作 | 作用对象 | 说明 |
|------|---------|------|
| `--resume <id>` | 加载已有 session | 从 DB 加载，不指定 `--steps` 时默认执行 **1 步** |
| `--fork` | 要求 `--resume` | 从原 session **复制**出新 session，原 session **不动** |
| `--from-iteration N` | 目标 session | 裁掉迭代 N 及之后的内容 |
| `--user-input TEXT` | 目标 session | 在下一轮注入用户指令，LLM 重新解析 |
| `--steps N` | 目标 session | 执行 N 轮（0=不限） |

**关键规则**：
- `--fork` 不加 `--steps` → **只 Fork 不执行**（0 步）
- `--fork` 加 `--steps N` → **先 Fork，再在 Fork 出的 session 上执行 N 步**
- 不加 `--fork` → **直接操作原 session**
- `--steps 0` → 不限步数，直到终止

### 完整参数列表

见 `drawagent run --help`。包含以上执行控制参数，以及：
- 基础参数：`--config`, `--db`, `--output-dir`
- 恢复参数：`--resume`
- 生成参数：`--width`, `--height`, `--steps-param`, `--guidance`, `--seed`, `--num-images`, `--max-iterations`, `--negative-prompt`
- Agent 参数：`--model-a/c`, `--api-key-a/c`, `--api-base-a/c`, `--temperature-a/c`, `--agent-b-type/url/endpoint`, `--mcp-command`

> 注意：扩散步数用 `--steps-param`（区别于执行步数的 `--steps`）

### 典型调试工作流

```bash
# 1. 生成一次
drawagent run "a warrior princess portrait" --db debug.db

# 2. 回到第2轮（裁掉2+），注入新指令，只跑1步看 LLM 如何调整
drawagent run --db debug.db --resume run-xxx --from-iteration 2 \
  --user-input "make armor more ornate"

# 3. 从第2轮 Fork 新 session 再跑（原 session 被保护）
drawagent run --db debug.db --resume run-xxx --from-iteration 2 \
  --fork --steps 1

# 4. Fork 一个新 session 并立即注入指令跑 2 步
drawagent run --db debug.db --resume run-xxx --fork \
  --user-input "change to nighttime scene" --steps 2

# 5. 纯 Fork（不执行）— 得到一个分叉点，稍后再操作
drawagent run --db debug.db --resume run-xxx --fork
# 输出: Forked: run-20260629... -> fork-run-2026...
#       Fork complete. No steps executed.

# 6. 在 Fork 出的 session 上继续
drawagent run --db debug.db --resume fork-run-2026... --steps 1
```

### `--user-input` 工作原理

```
drawagent run --db debug.db --resume <id> --user-input "make it darker"
```

1. 加载 session，设置 `session.pending_action = "steer"`
2. 设置 `session.steer_message = "make it darker"`
3. Loop 在下一轮迭代开始前检测到 steer 指令
4. 将 `current_prompt` 替换为用户的新指令
5. Agent A 基于新指令 + 历史观察结果，refine 提示词
6. Agent B 用新提示词生成

输出示例：
```
Session: run-20260629...
Prompt:  "a warrior princess portrait"
  Start:  iteration 2
  Steps:  1 iteration(s)
User input: "make it darker"
--------------------------------------------------
  >>> Iteration 2 started
  [Generate] Calling Agent B...
  [Image] gen_xxx.png (seed=99, 1024x1024)
  [Inspect PASS] check_lighting
  [Quality PASS] Lighting improved, matches user request.
  *** Loop ended: step_limit_reached ***

Result: step_limit_reached
Iterations completed: 2
Images:
  D:\Code\DrawAgent\outputs\gen_xxx.png
```

### `--fork` 工作原理

```
drawagent run --db debug.db --resume <id> --fork --steps 1
```

1. 加载原始 session A，复制其 iterations
2. 创建新 session B（ID: `fork-<A的ID前12位>-<时间戳>`）
3. 将 B 持久化到数据库（A 不受影响）
4. 对 B 执行生成

这样可以在不破坏原始 session 的情况下探索不同方向。

---

## 二、`drawagent cli` — 交互式命令行

启动 REPL 循环：输入需求→生成→看结果→继续输入。

### 基本用法

```bash
drawagent cli
```

### 所有参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--config PATH` | 自动发现 | 配置文件路径 |
| `--output-dir PATH` | ./outputs | 图片输出目录 |
| `--db PATH` | 不启用 | SQLite 持久化 |
| `--resume SESSION_ID` | 无 | 恢复指定 session |
| `--from-iteration N` | 0=自动 | 从第 N 轮恢复 |
| `--rerun-last` | false | 重跑最后一轮 |
| `--step` | false | 单步执行模式 |

### 交互命令

#### 全局

| 命令 | 说明 |
|------|------|
| `/quit` | 退出 |
| `/help` | 帮助 |
| `/status` | 显示 session 状态和已完成迭代列表 |
| 普通文本 | 作为图像生成需求启动全流程 |

#### 单步模式（需 `--step`）

```
  [Step] Iteration 2 complete — waiting for user
  /next (Enter) | /accept | /steer <msg> | /rollback | /quit | /status
  >
```

| 命令 | 说明 |
|------|------|
| Enter 或 `/next` | 继续下一轮 |
| `/accept` | 接受当前结果并结束 |
| `/steer <msg>` | 修改方向，下一轮融入新指令 |
| `/rollback` | 回退上一轮重新生成 |
| `/quit` | 退出步进，保留已完成迭代 |
| `/status` | 显示当前进度 |

### 使用场景

```bash
# 快速开始（无持久化）
drawagent cli

# 持久化（session 存入 SQLite，支持断点恢复）
drawagent cli --db ~/.drawagent/debug.db

# 单步调试
drawagent cli --step

# 单步 + 持久化（最强调试）
drawagent cli --db ~/.drawagent/debug.db --step

# 恢复上次的 session
drawagent cli --db ~/.drawagent/debug.db --resume <session_id>

# 从第二轮重新开始
drawagent cli --db ~/.drawagent/debug.db --resume <id> --from-iteration 2
```

### 循环事件输出

```
  >>> Iteration 1 started              # 迭代开始
  [Refine] Prompt updated              # 提示词优化（迭代 2+）
  [Generate] Calling Agent B...        # 调用图像生成
  [Image] filename (seed=42, 1024x1024)  # 生成完成
  [Inspect PASS/FAIL] task_name        # 逐项检查结果
  [Quality PASS/FAIL] reasoning        # Agent A 综合质量判断
  *** Loop ended: reason ***           # 结束原因
```

结束原因可能值：
`quality_passed` / `auto_accepted` / `user_accepted` / `user_quit` / `max_iterations` / `generation_error` / `generation_failed` / `awaiting_user`

---

## 三、`drawagent serve` — Web 服务器

启动 FastAPI 服务器，浏览器打开前端 UI。

### 基本用法

```bash
drawagent serve
# 打开 http://127.0.0.1:8000
```

### 参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--port N` | 8000 | 监听端口 |
| `--host HOST` | 127.0.0.1 | 监听地址 |
| `--output-dir PATH` | ./outputs | 图片输出目录 |
| `--config PATH` | 自动发现 | 配置文件路径 |

### 示例

```bash
drawagent serve
drawagent serve --port 8080 --config deepseek.yaml
drawagent serve --host 0.0.0.0 --port 8080
```

### 启动行为

- 启动时 **不检查 API Key**（服务器正常启动）
- 第一条用户消息到达时才按需创建 Provider
- API Key 未配→前端显示错误卡片
- 前端"系统设置"→`PUT /api/config`→后端实时更新，无需重启

---

## 四、`run` vs `cli` 对比

| 维度 | `run` | `cli` |
|------|-------|-------|
| 交互方式 | 非交互，命令即出 | REPL 逐行输入 |
| 步进控制 | `--steps N` 精确控制迭代数 | `--step` 每轮暂停手动确认 |
| 默认步数 | 新 session=全部, resume=1 | 全部 |
| 迭代定位 | `--from-iteration N` | 无（需从开始） |
| Fork | `--fork` 创建分支 session | 无 |
| 注入指令 | `--user-input TEXT` 程序化注入 | `/steer msg` 手动输入 |
| 详细输出 | 每轮事件打印 | 每轮事件打印 |
| 批量/脚本 | ✓ | ✗ |
| 调试探索 | ✓（单步+注入+fork） | ✓（REPL 交互式） |
| 退出码 | 0/1 | N/A |

---

## 五、配置文件完整参考

```yaml
# .drawagent.yaml — 完整配置示例

agent_a:
  provider: openai
  model: gpt-4o
  api_base: https://api.openai.com/v1
  api_key: ${OPENAI_API_KEY}      # 支持环境变量
  temperature: 0.7
  max_tokens: 4096

agent_b:
  type: http                      # http 或 mcp
  provider: local_zimage
  model: Z-Image-Turbo
  api_base: http://localhost:8000
  endpoint: /api/generate
  # MCP 模式：
  # type: mcp
  # mcp_command: ["python", "mcp_server.py"]
  # mcp_keep_alive: false        # false = 每次生成后关闭 MCP 释放显存（与本地 Ollama 共用 GPU 时推荐）
  default_params:
    width: 1024
    height: 1024
    steps: 8
    guidance: 3.5
    seed: -1

agent_c:
  provider: openai
  model: gpt-4o
  api_base: https://api.openai.com/v1
  api_key: ${OPENAI_API_KEY}
  temperature: 0.3
  max_tokens: 2048

loop:
  max_iterations: 7
  auto_accept_threshold: 8.0
  compaction_threshold_tokens: 20000
  keep_recent_iterations: 2
  step_mode: false

memory:
  base_dir: ~/.drawagent/memory
  auto_load: true
  auto_save: false
```
