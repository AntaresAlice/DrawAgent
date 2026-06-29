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

## 一、`drawagent run` — 非交互式一次性生成

接收提示词和参数，自动完成"解析→生成→检查→评估→输出"全流程后退出。
适合脚本、CI/CD、批量生成。

### 基本用法

```bash
drawagent run "a beautiful sunset over mountains"
```

### 所有参数

#### 提示词

| 参数 | 说明 |
|------|------|
| `prompt` (位置参数) | 生成需求文本 |
| `--prompt TEXT` | 同上（显式方式，脚本友好） |
| `--negative-prompt TEXT` | 负面提示词 |

#### 通用

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--config PATH` | 自动发现 | 配置文件路径 |
| `--output-dir PATH` | ./outputs | 图片输出目录 |
| `--db PATH` | 不启用 | SQLite 数据库路径 |

#### 恢复

| 参数 | 说明 |
|------|------|
| `--resume SESSION_ID` | 从数据库恢复指定 session |
| `--from-iteration N` | 从第 N 轮开始（0=自动从最后继续） |
| `--rerun-last` | 重新执行最后一轮 |

#### 生成参数（覆盖配置文件）

| 参数 | 默认 | 范围 |
|------|------|------|
| `--max-iterations N` | 7 | 1-20 |
| `--width PX` | 1024 | 512-2048 |
| `--height PX` | 1024 | 512-2048 |
| `--steps N` | 8 | 1-50 |
| `--guidance N` | 3.5 | 0-20 |
| `--seed N` | -1 | -1=随机 |
| `--num-images N` | 2 | 1-4 |

#### Agent 参数（覆盖配置文件）

| 参数 | 对应字段 |
|------|---------|
| `--model-a TEXT` | agent_a.model |
| `--api-key-a TEXT` | agent_a.api_key |
| `--api-base-a URL` | agent_a.api_base |
| `--temperature-a N` | agent_a.temperature |
| `--model-c TEXT` | agent_c.model |
| `--api-key-c TEXT` | agent_c.api_key |
| `--api-base-c URL` | agent_c.api_base |
| `--temperature-c N` | agent_c.temperature |
| `--agent-b-type http\|mcp` | agent_b.type |
| `--agent-b-url URL` | agent_b.api_base |
| `--agent-b-endpoint PATH` | agent_b.endpoint |
| `--mcp-command TEXT` | agent_b.mcp_command |

### 示例

```bash
# 最简单
drawagent run "a cat sitting on a windowsill"

# 使用 DeepSeek（命令行覆盖所有配置）
drawagent run "a cat" \
  --api-key-a sk-deepseek-xxx \
  --api-base-a https://api.deepseek.com/v1 \
  --model-a deepseek-chat \
  --api-key-c sk-deepseek-xxx \
  --api-base-c https://api.deepseek.com/v1 \
  --model-c deepseek-chat \
  --width 512 --height 512 --steps 4 --max-iterations 2

# 使用配置文件 + 命令行覆盖部分
drawagent run "a cat" --config deepseek.yaml --width 768

# 恢复未完成的 session
drawagent run --db ~/.drawagent/debug.db --resume cli-20260629-153022

# 从特定轮恢复
drawagent run --db ~/.drawagent/debug.db --resume <id> --from-iteration 3

# 脚本批量生成
for prompt in "a red car" "a blue sky" "a green forest"; do
    drawagent run "$prompt" --output-dir ./batch --max-iterations 2
done
```

### 输出格式

```
Generating: "a cat sitting on a windowsill"
  Agent A: gpt-4o @ https://api.openai.com/v1
  Agent B: http @ http://localhost:8000/api/generate
  Agent C: gpt-4o @ https://api.openai.com/v1
  Max iterations: 7
  Image: 1024x1024, steps=8, guidance=3.5
--------------------------------------------------
Result: quality_passed
Iterations: 2
Images:
  D:\Code\DrawAgent\outputs\gen_1719000001_02_43.png
```

退出码：成功=0，失败=1

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
| 交互方式 | 非交互，命令行参数 | 交互式 REPL |
| 参数来源 | 命令行 flags | 配置文件 + 终端输入 |
| 配置覆盖 | `--model-a` 等 14 个 flags | 通过配置文件 |
| 持久化 | `--db` 可选 | `--db` 可选 |
| 恢复 | `--resume` + `--from-iteration` | 同上 |
| 步进 | 不支持 | `--step` |
| 批量/脚本 | ✓ | ✗ |
| 调试/探索 | ✗ | ✓ |
| 退出码 | 0/1 | N/A（交互式） |

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
