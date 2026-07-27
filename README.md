# DrawAgent — 你的 AI 画图总监

> 说出想法，剩下的交给 Agent。DrawAgent 让 LLM 像一位真正的艺术总监，理解你的需求、撰写提示词、调度图像生成、审视结果、主动迭代优化，直到生成令你满意的作品。

---

## 为什么需要 DrawAgent？

当前 AI 图像生成看似强大，实际使用中却处处碰壁：

| 痛点 | 现状 | DrawAgent 的做法 |
|------|------|------------------|
| **提示词难写** | 不知道如何精确描述想要的画面；写了"细节化"、"氛围感"这种模糊词，模型无动于衷 | LLM 自动将模糊需求转化为专业、具体的画面描述，补齐光照、材质、构图等细节 |
| **提示词不可复用** | Midjourney 的好提示词换到 SD 就失效，每个模型方言不同 | Agent 掌握各模型的"方言"，自动适配，提示词知识通过记忆系统固化，跨会话复用 |
| **等待时间太长** | 生成 → 不满意 → 改提示词 → 再生成 → 再改……反复坐在电脑前等待 | Agent 自动完成生成→审图→修正→再生成的闭环，你只需在旁边看着，随时插话 |

**一句话总结**：DrawAgent 把你从"提示词工程师"的角色中解放出来，你只需要用自然语言描述想法，AI 自动搞定剩下的专业工作。

---

## 核心特色

### 1. LLM 主 Agent + 工具驱动，自动化迭代优化

DrawAgent 的核心架构是一个 LLM 主 Agent，它掌控图像生成的全局。它拥有多个可调用的工具：

```
                    ┌── generate_image ──→ 图像生成模型 (HTTP / MCP)
你 ──→ [LLM 主 Agent] ──┼── inspect_image ──→ 视觉模型 (Vision LLM)
                    ├── compare_images ──→ 视觉模型 (双图对比)
                    └── load/search/save_memory ──→ 记忆系统
```

- **generate_image**：调用图像生成模型（Z-Image、SD、DALL·E 等），将提示词变为图片
- **inspect_image / compare_images**：调用视觉模型审视生成的图片，逐项检查是否满足需求
- **记忆工具**：加载历史经验、搜索相关模板、保存有效的提示词知识

在每次生成中，Agent 遵循一个五阶段的自动迭代闭环：

```
规划质检任务 → 优化提示词 → 生成图片 → 视觉检查 → 综合评估
    ↑                                                      │
    └────────── 发现不足，自动进入下一轮迭代 ────────────────┘
```

Agent 调用视觉模型检查图片后，会精确识别问题——"左手比划正确吗？"、"光影方向对吗？"、"背景细节够吗？"——然后有针对性地修正提示词，调用图像生成模型重新生成。这个闭环全程自动运行，直到图像质量达标或达到迭代上限。

### 2. 智能提示词分解：变体自动拆分

扩散模型对复杂并列语义的理解能力有限。当你输入"穿着 T 恤 / 衬衫 / 短袖"时，模型往往不知所措——要么随机选一个，要么把三种元素全塞进一张图。

DrawAgent 的 LLM 会智能识别自然语言中的并列关系：

- 识别 `/`（斜杠）、"或者"、"要么……要么……"、"可以……也可以……"等并列标记
- 自动拆分为多张独立图片，每张专注于一组确定的元素组合
- 例如输入"马尾/短发 + T恤衫/吊带衫"，Agent 会自动生成 2×2 = 4 张图，覆盖所有组合

### 3. 模糊语义补全：把"感觉"变成"画面"

非专业用户经常会写一些抽象的、感性的描述，比如"氛围感"、"细节化"、"精致一点"、"自由发挥"。图像生成模型面对这些词汇毫无头绪。

DrawAgent 的 LLM 会自动将这些模糊描述转化为具体的、模型能理解的画面描述：

- 用户写"教室背景，细节化" → Agent 展开为"教室后方是深绿色黑板，上方挂着国旗，窗边白色窗帘被微风吹起，阳光斜照在木质课桌表面"
- 用户写"有氛围感" → Agent 补充具体的光影、色调、构图描述
- 用户写"自拟" / "自由发挥" → Agent 选择具体的风格、元素、构图并写入 prompt

这就是 LLM 的核心价值——理解模糊语义，输出确定性的画面描述，弥合人类自然语言与模型 prompt 之间的鸿沟。

### 4. 持续学习：Skill 与 Agent 记忆系统

每次成功生成一张好图，DrawAgent 都会把相关经验沉淀下来：

- **提示词模板**：经过验证的有效提示词片段被保存为 Markdown 文档，分类存储（人像 / 风景 / 物体 / 概念艺术），下次遇到类似需求时自动加载
- **质检清单**：针对不同主题（通用、人像、场景）的检查维度，Agent 在审图时按清单逐项排查，不漏检
- **跨会话复用**：今天生成的人像提示词技巧，明天生成时自动可用——知识不会丢失

所有记忆文件均为纯 Markdown，人和 Agent 都可以直接阅读和编辑。

### 5. 对话式生成界面，实时掌控

DrawAgent 提供了一个用户友好的对话式生成界面，你可以：

- **实时观察**：Agent 写提示词、调度生成、审图评估的过程以流式卡片呈现，一目了然
- **随时介入**：看到满意或不满意的方向，可以直接发送指令——"突出人物主体"、"把天气改为雨天"、"左边那只手有点怪，修一下"——Agent 立即响应调整
- **单步控制**（Step 模式）：每轮迭代后暂停，由你决定 `继续 / 接受 / 修正 / 回退`
- **分支探索**（Fork）：从某个中间状态分叉出新的分支，探索不同方向，原始分支不受影响
- **断点恢复**：所有 session 持久化到 SQLite，随时可以恢复之前的工作

---

## 支持的模型

DrawAgent 不绑定任何特定模型。所有组件均通过 OpenAI 兼容 API 接入：

| 组件 | 支持的模型类型 | 已验证的模型 |
|------|---------------|-------------|
| LLM 主 Agent | 任何 OpenAI 兼容 API | DeepSeek v4, GPT-4o, Qwen, Ollama |
| 图像生成 (generate_image) | HTTP API / MCP 协议 | Z-Image, SD 系列, DALL·E |
| 视觉模型 (inspect/compare) | 任何支持 Vision 的 OpenAI 兼容 API | GPT-4o, Qwen VL, Ollama |

配置文件的每一处都可以用环境变量 `${ENV_VAR}` 引用，敏感信息不落地。

---

## 快速上手

### 环境要求

- Python 3.11+
- 至少一个可用的 LLM API（DeepSeek / OpenAI / 本地 Ollama 等）
- （可选）一个图像生成 API 或本地部署的图像模型

### 安装

```bash
git clone https://github.com/yourorg/DrawAgent.git
cd DrawAgent
pip install -e .
```

### 配置

在项目根目录创建 `.drawagent.yaml`，参考项目自带的 `.drawagent.default.yaml` 模板。配置文件加载优先级（后者覆盖前者）：

> 内置默认 → `~/.drawagent/config.yaml` → 项目目录 `.drawagent.yaml` → `--config` 参数 → CLI 参数

### 启动 Web 界面

```bash
drawagent serve --port 8000
# 浏览器打开 http://127.0.0.1:8000
```

在输入框中描述你想要的画面，剩下的交给 Agent。

---

## 使用指南

DrawAgent 提供三种运行模式，适合不同使用场景。

### `drawagent serve` — Web 服务

启动带 Web UI 的 FastAPI 服务器，适合日常使用。

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--port N` | 8000 | 监听端口 |
| `--host HOST` | 127.0.0.1 | 监听地址 |
| `--output-dir PATH` | ./outputs | 图片输出目录 |
| `--config PATH` | 自动发现 | 配置文件路径 |

```bash
drawagent serve                        # 默认启动
drawagent serve --port 8080            # 指定端口
drawagent serve --host 0.0.0.0 --port 8080  # 允许局域网访问
```

### `drawagent cli` — 交互式命令行

在终端中进行对话式生成，适合服务器环境或偏好命令行的用户。

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--output-dir PATH` | ./outputs | 图片输出目录 |
| `--config PATH` | 自动发现 | 配置文件路径 |
| `--db PATH` | 无 | 启用 SQLite 持久化 |
| `--step` | false | 单步模式，每轮暂停确认 |
| `--resume ID` | 无 | 恢复指定 session |
| `--from-iteration N` | 0 | 从第 N 轮恢复 |
| `--rerun-last` | false | 重跑最后一轮 |

**交互命令（普通模式）**：

| 命令 | 说明 |
|------|------|
| 普通文本 | 作为需求启动全流程 |
| `/quit` | 退出 |
| `/help` | 帮助 |
| `/status` | 查看当前 session 状态 |

**交互命令（单步模式，需 `--step`）**：

| 命令 | 说明 |
|------|------|
| 回车 或 `/next` | 继续下一轮迭代 |
| `/accept` | 接受当前结果并结束 |
| `/steer <消息>` | 修改方向，调整后续生成 |
| `/rollback` | 回退到上一轮 |
| `/quit` | 退出 |

```bash
drawagent cli                                   # 快速开始
drawagent cli --db ~/.drawagent/sessions.db     # 持久化，支持恢复
drawagent cli --step                            # 单步调试模式
drawagent cli --db ~/.drawagent/sessions.db --step  # 最强调试组合
```

### `drawagent run` — 非交互式执行

面向调试和脚本化场景，类 GDB 风格的精确定位控制。

| 参数 | 说明 |
|------|------|
| `PROMPT` | 图像生成需求（位置参数） |
| `--config PATH` | 配置文件 |
| `--db PATH` | SQLite 数据库路径 |
| `--resume ID` | 恢复指定 session |
| `--from-iteration N` | 从第 N 轮开始（裁掉 N 之后的） |
| `--fork` | 从原 session 复制新分支，原分支不受影响 |
| `--user-input TEXT` | 注入用户指令，模拟 steer |
| `--steps N` | 执行 N 轮（0 = 不限，直到终止） |
| `--gen-params PATH` | 加载生成参数预设（YAML） |
| `--width PX` / `--height PX` | 图片尺寸 |
| `--steps-param N` | 扩散步数 |
| `--guidance N` | CFG guidance scale |
| `--seed N` | 随机种子（-1 为随机） |
| `--num-images N` | 每轮生成图片数 |
| `--model-a/c MODEL` | 覆盖 Agent A/C 的模型 |
| `--api-key-a/c KEY` | 覆盖 API Key |
| `--agent-b-type http\|mcp` | Agent B 的协议类型 |

```bash
# 一次性生成
drawagent run "a warrior princess portrait, cinematic lighting"

# 从第 2 轮恢复并注入新指令，只执行 1 步（观察 LLM 如何调整）
drawagent run --db debug.db --resume run-xxx \
  --from-iteration 2 --user-input "make the armor more ornate" --steps 1

# Fork 出一个新分支，注入指令，执行 3 步
drawagent run --db debug.db --resume run-xxx --fork \
  --user-input "change to nighttime scene" --steps 3

# 纯 Fork（不执行），得到一个分叉点
drawagent run --db debug.db --resume run-xxx --fork

# 在 Fork 出的 session 上继续
drawagent run --db debug.db --resume fork-run-2026... --steps 1
```

### 生成参数预设

`gen_presets/` 目录下提供了四个预设文件：

| 预设 | 分辨率 | 扩散步数 | Guidance | 图片数 | 适用场景 |
|------|--------|---------|----------|--------|---------|
| `high-quality.yaml` | 1280×1280 | 30 | 7.0 | 1 | 最终出图 |
| `fast-preview.yaml` | 768×768 | 4 | 3.5 | 2 | 快速预览 |
| `portrait.yaml` | 960×1280 | 30 | 7.0 | 4 | 人像 |
| `seed-sweep.yaml` | 1024×1024 | 8 | 3.5 | 4 | 种子探索 |

在 `run` 模式中使用预设：

```bash
drawagent run "a cat in a garden" --gen-params gen_presets/fast-preview.yaml
```

---

## 项目架构

```
DrawAgent/
├── src/drawagent/
│   ├── config/           # Pydantic 配置模型 + 多层加载器
│   ├── core/             # Session, Iteration, EventBus, 错误体系
│   ├── providers/        # LLM / Vision 抽象层 + OpenAI 兼容实现
│   ├── tools/            # 工具系统 (register → materialize → settle)
│   ├── agents/           # 主 Agent 推理引擎 + System Prompts
│   ├── orchestrator/     # SessionManager, 5 阶段状态机, InterruptHandler
│   ├── context/          # 5 层上下文组装, 迭代压缩
│   ├── memory/           # Markdown 记忆存储 + 索引 + 搜索
│   ├── persistence/      # aiosqlite 数据库持久化
│   ├── api/              # FastAPI + WebSocket 实时事件推送
│   ├── ui/static/        # 纯 HTML/CSS/JS 前端 (零框架依赖)
│   └── main.py           # CLI 入口
├── memory/               # 内置提示词模板与质检清单
├── gen_presets/          # 生成参数预设
├── tests/                # 测试套件 (14 个测试文件)
├── docs/                 # 设计文档、路线图等
└── outputs/              # 生成图片输出 (gitignored)
```

### 记忆系统

DrawAgent 的记忆系统以 Markdown 文件形式存储，人机可读：

```
~/.drawagent/memory/
├── index.md                   # 自动维护的索引
├── prompts/                   # 提示词模板库
│   ├── portraits.md
│   ├── landscapes.md
│   ├── objects.md
│   └── concepts.md
└── inspections/               # 质检清单库
    ├── _builtin_common.md
    ├── _builtin_portrait.md
    └── _builtin_scene.md
```

### API 端点一览

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/status` | 服务器健康检查 |
| POST | `/api/sessions` | 创建会话 |
| GET | `/api/sessions` | 列出所有会话 |
| POST | `/api/sessions/{id}/message` | 发送用户消息 |
| POST | `/api/sessions/{id}/interrupt` | 中断控制 (pause/steer/accept/rollback) |
| GET | `/api/sessions/{id}/history` | 获取会话历史 |
| DELETE | `/api/sessions/{id}` | 删除会话 |
| GET | `/api/images/{filename}` | 获取生成图片 |
| GET / PUT | `/api/config` | 运行时读写配置 |
| GET | `/api/sessions/{id}/export` | 导出会话为 ZIP |
| WS | `/ws/sessions/{id}` | WebSocket 实时事件流 |

---

## 效果展示

### Workflow 演示

```
你: 画一个中国古代侠女，站在雨中，斗笠，红色披风，电影感

Agent: [理解需求] 你想画一位中国古风女侠——
       雨中场景、戴斗笠、红色披风、电影级光影
       [正在优化提示词...]
       古风侠女，头戴竹编斗笠，红色披风在雨中飘扬，
       雨水沿斗笠边缘滴落，冷色调背景，侧光打亮人物轮廓，
       cinematic lighting, 85mm lens, shallow depth of field

Agent: [调用 generate_image] 正在生成... gen_001.png ✓

Agent: [调用 inspect_image 逐项检查]
       ✅ 斗笠：清晰可见，竹编纹理明显
       ✅ 红色披风：颜色鲜明，雨中飘动自然
       ✅ 雨景：雨丝可见，地面有水洼反光
       ⚠️ 人物面部：表情略显僵硬，眼神不够锐利
       ⚠️ 光影：侧光效果不够强烈

Agent: [第 2 轮优化] 针对面部表情和光影，
       增强侧光对比度，强化眼神锐利度，
       补充："sharp determined gaze, dramatic side lighting,
       rain drops visible on face"……

Agent: [调用 generate_image] 正在生成... gen_002.png ✓

Agent: [调用 inspect_image] 所有维度达标 ✓

Agent: [交付] 经 2 轮迭代，图像质量达到要求
```

在 Web UI 中，这个过程以流式卡片实时呈现，每个阶段都有清晰的视觉反馈。

### Web UI 特性速览

- **会话侧边栏**：管理多个会话，随时切换
- **快速参数栏**：宽度、高度、数量、步数、guidance 等一键调整
- **图片浏览器**：全屏查看、前后翻页、下载、复制
- **迭代对比**：并排对比不同轮次的生成结果
- **中断控制**：生成过程中可以随时 Accept / Steer / Pause
- **系统设置**：实时修改 Provider / Model / API Key，无需重启
- **双语界面**：中文 / English 一键切换
- **键盘快捷键**：`Ctrl+Enter` 发送，`Esc` 关闭弹窗，`Ctrl+Shift+N` 新建会话

---

## 开发指南

```bash
# 安装开发依赖
pip install -e ".[dev]"

# 运行测试
pytest tests/ -v

# 代码风格检查
ruff check src/

# 类型检查
pyright src/
```

---

## 未来计划

- [ ] **MCP 冷启动消除** — 迭代间保持 MCP 存活，减少 GPU 模型重载带来的等待
- [ ] **工具并行调用** — 批量并发执行视觉检查，大幅缩减 Inspection 阶段耗时
- [ ] **Skill 系统** — 参照 OpenCode 的 skill 架构，按需加载领域专用技能模块
- [ ] **多模态用户输入** — 支持上传参考图 + 文字描述，风格迁移、以图生图
- [ ] **Vision-capable 主 Agent** — 当 LLM 自身支持视觉时，直接看图判断，省去外部视觉模型调用
- [ ] **多图像模型支持** — 同时接入多个图像生成模型，按任务类型自动选择
- [ ] **提示词模板库演进** — 积累更多领域模板，支持自动推荐

详见 [ROADMAP.md](docs/ROADMAP.md)。

---

## 常见问题

<details>
<summary><b>Q: 我没有 GPU，能用 DrawAgent 吗？</b></summary>

可以。LLM 和视觉模型均使用云端 API（DeepSeek / OpenAI / 任何 OpenAI 兼容服务），图像生成也可以使用云端 API（如 DALL·E 或远程部署的 Stable Diffusion）。你只需要 API Key，不需要本地 GPU。

</details>

<details>
<summary><b>Q: 如何接入本地 Ollama 模型？</b></summary>

在配置文件中设置：

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

注意：视觉模型需要较大的上下文窗口（建议 32K+），模型尺寸过小（如 9B 以下）可能导致 VLM 空响应。

</details>

<details>
<summary><b>Q: 图像生成如何使用 MCP 协议？</b></summary>

```yaml
agent_b:
  type: mcp
  mcp_command: ["python", "mcp_server.py"]
  mcp_keep_alive: false   # false = 每次生成后释放 GPU 显存
```

`mcp_keep_alive: false` 适合 GPU 需要被多个程序共用的场景（如 Ollama 与图像生成模型共享 GPU）。

</details>

<details>
<summary><b>Q: 如何调试一个特定的迭代？</b></summary>

使用 `drawagent run` 的精准控制能力：

```bash
# 加载 session，回到第 2 轮，注入 steer 指令，只执行 1 步
drawagent run --db debug.db --resume SESSION_ID \
  --from-iteration 2 --user-input "brighten the scene" --steps 1
```

配合 `--fork` 可以安全探索不同方向而不影响原始 session。

</details>

<details>
<summary><b>Q: 配置文件中的环境变量引用怎么写？</b></summary>

使用 `${ENV_VAR_NAME}` 语法，在加载时自动解析：

```yaml
api_key: ${OPENAI_API_KEY}
```

API Key 不会写入配置文件，只需设置对应的环境变量即可。

</details>

---

## 许可证

MIT

---

## 贡献

欢迎提交 Issue 和 Pull Request。在此之前，建议先阅读 [DESIGN.md](DESIGN.md) 了解项目架构设计，以及 [docs/ROADMAP.md](docs/ROADMAP.md) 了解当前开发计划。
