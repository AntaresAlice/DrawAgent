# DrawAgent Implementation Record

> 项目交付文档 — 记录每个功能点的设计决策、实现细节、已知限制

---

## 2026-07-01: 多图对比工具 (compare_images)

### 背景
用户要求 Agent C (vision model) 能够同时对比两张图片，回答"新图是否比旧图更清晰""新图添加了什么元素"等比较性问题。

### 调研结论
- Ollama qwen3.5:9b 的 OpenAI-compatible API **支持单次请求多图**
- 模型能**正确区分 Image 1 vs Image 2**（基于 content 数组顺序）
- 模型能回答比较性问题（清晰度、复杂度、风格差异）
- **上下文窗口瓶颈**：两张 1.6MB 原图耗尽 32K 上下文，`finish: length, 0 chars`

### 实现方案

#### 新增抽象方法
`VisionProvider.compare_images(image_data_1, image_data_2, questions, context) -> str`
- 文件: `src/drawagent/providers/base.py`

#### OpenAICompatibleProvider 实现
- 文件: `src/drawagent/providers/openai_compat.py`
- **临时权宜之计**: 发送前将图片压缩到 max 512px (LANCZOS)
  - 压缩后每张约 340KB base64
  - 为小型上下文模型 (32K) 预留输出空间
  - 标记为 `TODO`: 切换到大上下文视觉模型后移除压缩
- Prompt 结构: 先说明"Image 1 first, then Image 2"，再放两张图
- max_tokens=1024, temperature=0.3, timeout=180s
- 集成 VerboseLog

#### CompareImagesTool
- 文件: `src/drawagent/tools/compare_images.py`
- 参数: `image_path_1`, `image_path_2`, `comparison_questions`, `context`
- 注册到 ToolRegistry (main.py 三处 + walkthrough_pipeline.py)
- Agent A 在 inspection 阶段可调用（enabled_tools 加入 `compare_images`）
- loop.py 第 324 行: `enabled_tools={"inspect_image", "compare_images"}`

### 测试结果
| 测试场景 | 图片对 | res | 结果 | 说明 |
|---------|--------|-----|------|------|
| 跨类别识别 | 苹果 + 教堂 | 384 | ✅ 1073 chars | "Image 1: apple, Image 2: church" |
| 清晰度对比 (A) | 清晰少女 + 模糊教堂 | 384 | ✅ 998 chars | "Image 1 is significantly sharper" |
| 清晰度对比 (B) | 模糊教堂 + 清晰少女 | 384 | ✅ 1077 chars | 顺序调换后仍正确识别 "Image 2 is sharper" |
| 同类别细节对比 | 教堂A + 教堂B | 384 | ✅ 298 chars | "Image 1: side view with spires; Image 2: twin towers with rose window" |
| 同类别简化提问 | 教堂A + 教堂B | 384 | ⚠️ 0 chars | 冷启动时首调用可能空响应 |

### 已知限制
1. **压缩是权宜之计** (openai_compat.py MAX_DIM=384): 降低图像质量换取可用上下文。TODO: 模型升级后移除。
2. **Ollama 冷启动**: `keep_alive=0` 卸载后首次多图调用可能因模型重载延迟返回空响应。生产环境建议保持模型常驻 (keep_alive > 0)。
3. **qwen3.5:9b 上下文 32K**: 两张复杂场景图即使 384px 压缩也可能接近上下文上限。
4. **部分文本重复**: qwen3.5 有时按非对称方式处理两张图，会重复描述其中一张，忽略另一张。

---

## 2026-07-01: 详细日志系统 (--verbose)

### 背景
用户要求看到 Agent A/B/C 之间原始通信内容，而非加工后的摘要。

### 实现方案
- 新建模块: `src/drawagent/core/verbose_log.py`
- 全局单例 `VerboseLog`，通过 `--verbose` 或 `DRAWAGENT_VERBOSE=1` 启用
- 输出到 stderr，不干扰 JSON-RPC 通道

### 日志类型
| 方法 | 用途 | 输出内容 |
|------|------|----------|
| `llm_request()` | Agent A API 调用前 | 完整 messages + tools |
| `llm_chunk()` | 流式响应 | 每个 streaming chunk |
| `llm_final()` | 流式完成后 | 最终 tool_calls + finish_reason |
| `vision_request()` | Agent C 调用前 | 图片路径 + 问题 |
| `vision_response()` | Agent C 响应 | 完整 observation |
| `mcp_request()` | Agent B MCP 调用 | method + params |
| `mcp_response()` | Agent B MCP 响应 | result (图片 base64 只显示长度) |
| `tool_call()` | 工具调用 | 工具名 + 参数 |
| `tool_result()` | 工具结果 | 成功/失败 + 输出摘要 |

### 集成点
- `openai_compat.py`: chat_stream() + analyze_image() + compare_images()
- `inspect_image.py`: execute()
- `mcp_provider.py`: generate()
- `main.py`: --verbose CLI flag → VerboseLog.enable()

---

## 2026-07-01: Z-Image 默认参数修正

### 背景
MCP server 的 TOOL_SCHEMA 描述误写为 "Z-Image-Turbo"，实际加载的是 Z-Image 完整版。默认参数 (steps=8, guidance=0.0) 是 Turbo 的参数，对完整版严重偏低。

### 修正

**MCP Server** (`D:\Code\Z-Image-MCP\mcp_server.py`):
| 参数 | 旧值 | 新值 | 依据 |
|------|------|------|------|
| 模型描述 | "Z-Image-Turbo" | "Z-Image (full version)" | 实际加载路径 |
| steps 默认 | 8 | 30 | 用户 params.json |
| guidance 默认 | 0.0 | 7.0 | 用户 params.json |
| cfg_truncation 默认 | 1.0 | 0.6 | 用户 params.json |
| 参数描述 | 基础 | 增加了推荐范围 (steps=20-40, guidance=5-8, cfg_truncation=0.5-0.7) | |

**DrawAgent** (`config/schema.py`, `config.example.yaml`, `tools/generate_image.py`):
| 参数 | 旧值 | 新值 |
|------|------|------|
| default_params.steps | 8 | 30 |
| default_params.guidance | 3.5 | 7.0 |
| default_params.cfg_truncation | 1.0 | 0.6 |
| generate_image 工具 schema defaults | 同步 | |

---

## 2026-07-01: model_hints 配置字段

### 背景
Agent A 需要知道当前生成模型的特点（推荐参数、提示词写法、已知弱点），以便写出更好的 prompt 和检查项。

### 实现
- `AgentBConfig` 新增 `model_hints: str = ""` 字段
- `ContextAssembler._build_system_prompt()` 在 system prompt 中注入 `## Model-Specific Knowledge` 段
- 未被启用时为空，不产生任何输出
- config.example.yaml 有注释示例

### 使用方式
```yaml
agent_b:
  model_hints: |
    ## Z-Image Model Tips
    - Recommended params: steps=20-40, guidance=5-8, cfg_truncation=0.5-0.7
    - Known weaknesses: complex hands, small faces, text rendering
    - Strengths: architectural details, landscapes, portraits, mood/lighting
```

---

## 2026-07-01: 检查计划提示词增强

### 背景
上一轮 pipeline 只检查了"元素是否存在"（建筑风格、光线、构图），未检查"图片质量"（模糊、噪声），导致模糊图片被判 PASS。

### 修改
`PROMPT_INSPECTION_PLAN` (`src/drawagent/agents/prompts.py`):
- 添加了 8 项检查清单（非强制内置，只是提醒）:
  - Critical content, Spatial accuracy, Detail integrity, Visual quality,
    Lighting & color, Style fidelity, Composition, No anomalies
- 强调"Include at least one visual-quality check (sharpness, noise, render quality)"

---

## 2026-07-01: Z-Image MCP 多模型支持 (计划)

### 背景
Z-Image 有两个模型:
- Z-Image-Turbo: 速度快，质量好，调参空间小
- Z-Image (完整版): 调参空间大，多样性好

MCP 当前只加载一个模型。需支持两个模型暴露给 Agent 选择。

### 计划
- [ ] MCP server 支持 `--model` 参数切换 Z-Image vs Z-Image-Turbo
- [ ] TOOL_SCHEMA 根据加载模型动态调整描述和默认参数
- [ ] DrawAgent 侧通过 MCP resource: `get_model_info` 获知可用模型

---

## 2026-07-01: MCP info/status 接口 (计划)

### 背景
MCP server 应能返回:
- 当前模型信息 (名称、参数、推荐配置)
- 服务状态 (空闲 / 忙碌 / 异常)
- 多用户场景下的队列状态

### 计划
- [ ] MCP resource: `get_model_info` — 返回模型名、版本、推荐参数
- [ ] MCP resource: `get_status` — 返回服务状态、当前请求数、预估等待时间
- [ ] DrawAgent Agent A 在 session 开始时查询 model info

---

## 2026-07-01: Agent Skill 系统 (计划)

### 背景
参照 opencode 的 skill 架构，让 Agent A 能按需加载模型特定知识、领域特定提示词技巧、检查清单模板。

### opencode Skill 架构参考
- Skill 文件: Markdown + YAML frontmatter (`SKILL.md`)
- 发现: 目录扫描 / URL 拉取 / 嵌入式
- 注入: `<available_skills>` XML 块 → system prompt
- 加载: Agent 调用 `skill` 工具按名加载
- 文件结构: `skills/{skill-name}/SKILL.md`

### 计划
- [ ] 创建 `skills/` 目录结构
- [ ] 实现 SkillLoader (解析 YAML frontmatter + markdown body)
- [ ] 创建 `load_skill` 工具 (Agent A 按需加载)
- [ ] System prompt 注入可用技能列表
- [ ] 首批技能:
  - `Z-Image.md`: 模型参数推荐 + 提示词技巧
  - `Z-Image-Turbo.md`: Turbo 专用参数
  - `portrait-inspection.md`: 人像专项检查清单
  - `scene-inspection.md`: 场景专项检查清单

---

## 2026-07-01: DeepSeek v4 流式工具调用修复

### Bug #1: Tool call ID 在后续 chunk 为空
**现象**: DeepSeek v4 流式响应中，tool_call 的 `id` 字段仅首 chunk 有值，后续参数 chunk 的 `id: null`
**影响**: `openai_compat.py` 用 `tc_id` 做 key 导致参数无法累积
**修复**: 改用 `tc.get("index", 0)` 做累积 key，首 chunk 的 `id` 仅用于 yield 事件

### Bug #2: 缺少 `type: "function"` 字段
**现象**: `agent_a.py` 构建 tool_calls 数组时只含 `id` 和 `function`，缺 `type`
**影响**: DeepSeek API 严格校验 OpenAI tool_call 格式，缺少 type 导致拒绝
**修复**: tool_calls_accumulated 条目添加 `"type": "function"`

### Bug #3: 缺少 assistant 消息
**现象**: 工具结果作为 `tool` role 消息直接 append，中间缺少 `assistant` role 的 tool_calls 消息
**影响**: DeepSeek API 要求 tool 消息前必须有 assistant 消息声明 tool_calls
**修复**: `agent_a.py` run_turn() 在 tool_results 前插入 assistant 消息

### 文件
- `src/drawagent/providers/openai_compat.py`
- `src/drawagent/agents/agent_a.py`

---

## 2026-07-01: Windows MCP stdio 兼容性修复

### Bug #1: connect_read_pipe OSError(6)
**修复**: MCP server 端 `run_in_executor(sys.stdin.readline)` 替代 `connect_read_pipe`
**原理**: Windows ProactorEventLoop 对 pipe 的 asyncio.connect_read_pipe 有已知 bug

### Bug #2: 导入时 stdout 污染
**修复**: zimage 导入期间 `sys.stdout = sys.stderr`
**原因**: `attention.py` 在 import 时执行 PyTorch 版本检查 print()

### Bug #3: Pipeline 生成时 stdout 污染
**修复**: `_generate()` 中临时 `sys.stdout = sys.stderr`
**原因**: Z-Image pipeline 的 print()/tqdm 输出会破坏 JSON-RPC 通道

### Bug #4: GBK 编码错误
**修复**: `encoding="utf-8"` + `PYTHONIOENCODING=utf-8`
**原因**: Windows 中文版默认 GBK 编码无法处理 emoji

### Bug #5: torch.Generator device 不匹配
**修复**: `"cuda" if torch.cuda.is_available() else "cpu"`
**原因**: 硬编码 `"cpu"` 在 CUDA 张量上创建 Generator 导致错误

### Bug #6: Loader device="cpu" 正确性
**结论**: `load_from_local_dir(device="cpu")` 是正确的
**原因**: Pipeline 动态管理 GPU 分配 (Text Encoder→CPU, DiT→GPU, VAE→GPU→CPU offload)。先加载到 CPU 再由 pipeline 分配更灵活。

### Bug #7: stderr 管道死锁
**修复**: `stderr=subprocess.DEVNULL` in MCPProvider
**原因**: stderr pipe 缓冲区满 → 子进程阻塞 → 死锁。stderr 无协议数据，可安全丢弃。

### 文件
- `D:\Code\Z-Image-MCP\mcp_server.py`
- `src/drawagent/providers/mcp_provider.py`

---

## 2026-07-01: MCPProvider 重写

### 背景
`asyncio.create_subprocess_exec` 在 Windows 上有 pipe 兼容性问题。

### 方案
- `subprocess.Popen` + `run_in_executor` 替代 asyncio 子进程
- stdin 写入: `run_in_executor(proc.stdin.write + flush)`
- stdout 读取: `run_in_executor(proc.stdout.readline)`
- 非 JSON 行跳过 (最多 50 行，用于启动噪音)

---

## 2026-07-01: mcp_keep_alive 功能

### 背景
Z-Image MCP 和 Ollama qwen3.5:9b 共享 GPU。需要在 Agent B 生成完成后释放 VRAM。

### 实现
- `AgentBConfig.mcp_keep_alive: bool = True`
- `GenerateImageTool.execute()` 在 batch 生成后检查: 若 `mcp_keep_alive=False`，关闭 MCP 子进程
- 仅影响 stdio 模式 (HTTP MCP 无子进程生命周期控制)
- 下次迭代需要时自动重连

---

## 2026-07-01: --gen-params CLI 标志 + gen_presets/

### 实现
- `--gen-params PATH`: 加载 YAML 预设 → 合并进 `config.agent_b.default_params`
- `gen_presets/`: high-quality.yaml, fast-preview.yaml, seed-sweep.yaml, portrait.yaml

---

## 2026-07-01: 生成参数扩展

### 新增参数
- `cfg_truncation` (0.0-1.0, default 1.0): CFG 截断率
- `max_sequence_length` (128-1024, default 512): Tokenizer 序列长度

### 集成链
TOOL_SCHEMA → MCPProvider.generate() → pipeline.generate()

---

## 2026-07-01: MCP 测试套件

### 文件
- `tests/test_mcp_gen.py`: 28 个 mock 测试 (MCPProvider 握手、生成、keep_alive、解析、错误)
- `tests/test_mcp_integration.py`: 5 个真实集成测试 (标记 @pytest.mark.integration)
