<div align="center">

# DrawAgent

**Your AI Art Director**

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-green.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/fastapi-0.115%2B-teal.svg)](https://fastapi.tiangolo.com/)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](#contributing)

*LLM-driven agentic image generation pipeline. An AI art director autonomously translates user requests into prompts, drives multi-turn image generation, inspects outputs via vision models, evaluates quality, and iterates until passing standards — all through a structured tool-calling loop.*

[English](#english) | [中文](#中文)

</div>

---

<a name="english"></a>
## English

### Why DrawAgent?

| Pain Point | Without DrawAgent | With DrawAgent |
|-----------|-------------------|----------------|
| **Prompt engineering is hard** | Spend hours tweaking "detailed", "cinematic", "8K" with no effect | LLM translates vague intent into precise visual descriptions with lighting, texture, composition |
| **Prompts are not reusable** | Midjourney prompts fail on SD; every model speaks a different dialect | Agent learns each model's "dialect" and adapts automatically; knowledge persists across sessions |
| **Wait-compare-retry loop** | Generate → unhappy → tweak → generate → repeat... sitting at the keyboard | Agent runs the generate→inspect→fix→regenerate loop autonomously; you just watch and steer when needed |

**In short**: Describe what you want in natural language. The Agent handles prompt engineering, quality inspection, and iterative refinement for you.

### Architecture

```
You ──→ [LLM Agent A] ──┬── generate_image ──→ Image Model (HTTP / MCP)
                        ├── inspect_image  ──→ Vision Model (VLM)
                        ├── compare_images ──→ Vision Model (side-by-side)
                        └── load/search/save_memory ──→ Memory System
```

Agent A autonomously runs a five-stage loop per iteration:

```
Plan inspections → Write prompt → Generate images → Inspect → Evaluate
       ↑                                                          │
       └────────── Issues found — auto-iterate ───────────────────┘
```

### Features

- **Fully automated iteration** — LLM generates, a vision model inspects, the LLM decides whether to iterate or finalize. No manual prompt tweaking.
- **Smart prompt decomposition** — Detects alternatives in natural language (`"马尾/短发"`) and auto-generates all combinations across multiple images.
- **Fuzzy intent → concrete prompt** — "make it more atmospheric" becomes specific lighting, color palette, and composition instructions.
- **Persistent memory** — Effective prompts, inspection checklists, and model-specific tricks are saved as Markdown and reused across sessions.
- **Live conversational UI** — Streaming turn cards show what the agent is doing: planning, generating, inspecting, deciding. Intervene anytime with steer messages.
- **Web + CLI + script modes** — Full-featured Web UI, interactive CLI, and non-interactive `run` mode for debugging/automation.
- **Dual engine** — Classic 5-phase pipeline and OpenCode-inspired agentic tool-calling loop, toggleable at runtime.

### Quick Start

**Requirements**: Python 3.11+, an LLM API key (DeepSeek / OpenAI / Ollama), optionally an image generation endpoint.

```bash
git clone https://github.com/AntaresAlice/DrawAgent.git
cd DrawAgent
pip install -e .

# Create config file (see config.example.yaml)
# Start the web UI
drawagent serve --port 8000
```

Open `http://127.0.0.1:8000`, describe your image, and watch the agent work.

### Supported Models

| Component | Backend | Verified Models |
|-----------|---------|-----------------|
| LLM Agent A | OpenAI-compatible API | DeepSeek v4, GPT-4o, Qwen, Ollama |
| Image Gen (Agent B) | HTTP API / MCP protocol | Z-Image, SD series, DALL·E |
| Vision (Agent C) | OpenAI-compatible Vision API | GPT-4o, Qwen-VL, Ollama |

### CLI Modes

| Command | Use Case |
|---------|----------|
| `drawagent serve` | Full web UI |
| `drawagent cli` | Interactive terminal |
| `drawagent run "prompt"` | Non-interactive, scriptable |

### Project Structure

```
DrawAgent/
├── src/drawagent/
│   ├── config/           # Pydantic config models + multi-layer loader
│   ├── agents/           # Agent A inference engine + system prompts
│   ├── tools/            # Tool system (register → materialize → settle)
│   ├── providers/        # LLM / Vision abstraction layer
│   ├── orchestrator/     # Session manager, 5-phase state machine, agentic loop
│   ├── memory/           # Markdown memory storage + index + search
│   ├── persistence/      # aiosqlite database
│   ├── api/              # FastAPI + WebSocket real-time events
│   └── ui/static/        # Vanilla HTML/CSS/JS frontend (zero framework)
├── memory/               # Built-in prompt templates & inspection checklists
├── gen_presets/          # Generation parameter presets
├── tests/                # Test suite
└── outputs/              # Generated images (gitignored)
```

### Contributing

PRs welcome. See [DESIGN.md](DESIGN.md) for architecture details and [docs/ROADMAP.md](docs/ROADMAP.md) for planned features.

### License

MIT

---

<a name="中文"></a>
## 中文

### 为什么需要 DrawAgent？

| 痛点 | 现状 | DrawAgent 的做法 |
|------|------|------------------|
| **提示词难写** | 不知道如何精确描述想要的画面；写了"细节化"、"氛围感"这种模糊词，模型无动于衷 | LLM 自动将模糊需求转化为专业、具体的画面描述，补齐光照、材质、构图等细节 |
| **提示词不可复用** | Midjourney 的好提示词换到 SD 就失效，每个模型方言不同 | Agent 掌握各模型的"方言"，自动适配，提示词知识通过记忆系统固化，跨会话复用 |
| **等待时间太长** | 生成 → 不满意 → 改提示词 → 再生成 → 再改……反复坐在电脑前等待 | Agent 自动完成生成→审图→修正→再生成的闭环，你只需在旁边看着，随时插话 |

**一句话总结**：DrawAgent 把你从"提示词工程师"的角色中解放出来，你只需要用自然语言描述想法，AI 自动搞定剩下的专业工作。

### 核心架构

```
                      ┌── generate_image ──→ 图像生成模型 (HTTP / MCP)
你 ──→ [LLM 主 Agent] ──┼── inspect_image ──→ 视觉模型 (Vision LLM)
                      ├── compare_images ──→ 视觉模型 (双图对比)
                      └── load/search/save_memory ──→ 记忆系统
```

Agent 在每次迭代中自动运行五阶段闭环：

```
规划质检任务 → 优化提示词 → 生成图片 → 视觉检查 → 综合评估
    ↑                                                      │
    └────────── 发现不足，自动进入下一轮迭代 ────────────────┘
```

### 核心特色

- **全自动迭代** — LLM 写提示词、视觉模型审图、LLM 决策是否继续改，全程自动
- **智能提示词分解** — 识别自然语言中的并列关系（"马尾/短发 + T恤衫/吊带衫"），自动拆分生成多张图覆盖所有组合
- **模糊语义补全** — "有氛围感"自动展开为具体的光影、色调、构图描写
- **持续学习记忆** — 有效提示词和质检清单保存为 Markdown，跨会话复用
- **实时对话界面** — 流式卡片展示 Agent 的思考、生成、审图、决策过程，随时发送指令介入
- **三种运行模式** — Web UI、交互式 CLI、脚本化非交互 `run` 模式
- **双引擎** — 经典五阶段流水线 + OpenCode 风格 Agentic 工具调用循环，运行时切换

### 快速上手

**环境要求**：Python 3.11+, 可用的 LLM API（DeepSeek / OpenAI / 本地 Ollama），（可选）图像生成服务。

```bash
git clone https://github.com/AntaresAlice/DrawAgent.git
cd DrawAgent
pip install -e .

# 创建配置文件（参考 config.example.yaml）
# 启动 Web 界面
drawagent serve --port 8000
```

浏览器打开 `http://127.0.0.1:8000`，在输入框中描述你想要的画面，剩下的交给 Agent。

### 支持的模型

| 组件 | 接入方式 | 已验证模型 |
|------|----------|-----------|
| LLM 主 Agent | OpenAI 兼容 API | DeepSeek v4, GPT-4o, Qwen, Ollama |
| 图像生成 (Agent B) | HTTP API / MCP 协议 | Z-Image, SD 系列, DALL·E |
| 视觉模型 (Agent C) | 支持 Vision 的 OpenAI 兼容 API | GPT-4o, Qwen-VL, Ollama |

### 命令行模式

| 命令 | 适用场景 |
|------|----------|
| `drawagent serve` | 完整 Web 界面 |
| `drawagent cli` | 交互式命令行 |
| `drawagent run "需求描述"` | 非交互式，适合脚本/调试 |

### 项目架构

```
DrawAgent/
├── src/drawagent/
│   ├── config/           # Pydantic 配置模型 + 多层加载器
│   ├── agents/           # 主 Agent 推理引擎 + System Prompts
│   ├── tools/            # 工具系统 (register → materialize → settle)
│   ├── providers/        # LLM / Vision 抽象层 + OpenAI 兼容实现
│   ├── orchestrator/     # SessionManager, 五阶段状态机, Agentic 循环
│   ├── memory/           # Markdown 记忆存储 + 索引 + 搜索
│   ├── persistence/      # aiosqlite 数据库持久化
│   ├── api/              # FastAPI + WebSocket 实时事件推送
│   └── ui/static/        # 纯 HTML/CSS/JS 前端 (零框架依赖)
├── memory/               # 内置提示词模板与质检清单
├── gen_presets/          # 生成参数预设
├── tests/                # 测试套件
└── outputs/              # 生成图片输出 (gitignored)
```

### 常见问题

<details>
<summary><b>Q: 如何接入本地 Ollama 模型？</b></summary>

```yaml
agent_a:
  provider: openai
  model: qwen3:14b
  api_base: http://localhost:11434/v1
  api_key: ollama
agent_c:
  provider: openai
  model: qwen3-vl:latest
  api_base: http://localhost:11434/v1
  api_key: ollama
```

注意：视觉模型需要较大的上下文窗口（建议 32K+）。
</details>

<details>
<summary><b>Q: 图像生成如何使用 MCP 协议？</b></summary>

```yaml
agent_b:
  type: mcp
  mcp_command: ["python", "mcp_server.py"]
  mcp_keep_alive: false   # false = 每次生成后释放 GPU 显存
```
</details>

<details>
<summary><b>Q: 如何调试特定迭代？</b></summary>

```bash
# 加载 session，回到第 2 轮，注入指令，只执行 1 步
drawagent run --db debug.db --resume SESSION_ID \
  --from-iteration 2 --user-input "brighten the scene" --steps 1
```
</details>

### 贡献

欢迎提交 Issue 和 Pull Request。建议先阅读 [DESIGN.md](DESIGN.md) 了解架构设计，以及 [docs/ROADMAP.md](docs/ROADMAP.md) 了解开发计划。

### 许可证

MIT
