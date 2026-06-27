# DrawAgent 工程开发计划 v1.0

> 基于 DESIGN.md v2.1 | 参考 opencode 代码模式 | 参考 webui_v6.html UI 模式

---

## 0. 开发总览

### 0.1 里程碑

| 里程碑 | 目标 | 预计工期 | 可交付 |
|--------|------|---------|--------|
| **M1: Foundation** | 项目骨架 + 配置 + 工具注册 + Provider | 5-7 天 | 可运行的 tool registry + 单个 provider 调用 |
| **M2: Core Loop** | Agent A + 内/外层循环 + 中断 | 5-7 天 | CLI 下跑通"需求→生成→审核→修改"完整一轮 |
| **M3: Memory** | 记忆存储/加载/搜索 + 内置检查项 | 3-4 天 | 记忆接入 loop，跨会话提示词复用 |
| **M4: API + UI** | FastAPI + WebSocket + 前端 | 5-7 天 | 完整的 Chat UI，可实际使用 |
| **M5: Polish** | 测试 + 文档 + 打包 | 3-5 天 | 可发布的 v0.1 |

### 0.2 技术栈

| 层面 | 技术 | 版本 |
|------|------|------|
| 语言 | Python | 3.11+ |
| 包管理 | uv / pip | latest |
| Web 框架 | FastAPI + uvicorn | 0.115+ |
| 异步 | asyncio + anyio | stdlib |
| 数据校验 | Pydantic v2 | 2.x |
| LLM 调用 | httpx + openai SDK (可选) | latest |
| 持久化 | aiosqlite | 0.20+ |
| 图像处理 | Pillow | 10.x |
| 前端 | 纯 HTML/CSS/JS (无框架) | — |
| 日志 | structlog | 24.x |

### 0.3 编码规范

参考 opencode 的 `AGENTS.md` 中的原则，适配 Python：

1. **单一职责**：每个函数只做一件事。不创建只用一次的私有 helper。
2. **类型标注**：所有公开接口完整标注类型；内部函数可用 `# type: ignore` 豁免。
3. **异步优先**：所有 I/O 操作（LLM 调用、文件读写、DB 查询）使用 `async/await`。
4. **dataclass > dict**：结构化数据用 `@dataclass` 或 Pydantic `BaseModel`，不用裸 dict。
5. **异常明确**：自定义异常类层次，不用 `except Exception` 宽泛捕获。
6. **日志可观测**：关键决策点（prompt 修改、质量判断、中断处理）必须打结构化日志。
7. **不可变优先**：函数返回值新建对象，不修改入参。内部状态用显式 `Session` 对象管理。
8. **依赖注入**：不直接 import 具体实现，通过函数参数或简易 DI 容器注入.

---

## 1. 项目结构

```
DrawAgent/
├── pyproject.toml
├── README.md
├── DESIGN.md                       # 设计文档
├── DEVEL.md                        # 本文件
├── .drawagent.default.yaml         # 默认配置模板
│
├── src/drawagent/
│   ├── __init__.py
│   ├── main.py                     # 入口: CLI + FastAPI 启动
│   │
│   ├── config/                     # ── 配置系统 ──
│   │   ├── __init__.py
│   │   ├── schema.py               # Pydantic 配置模型
│   │   └── loader.py               # 多层配置加载 + 合并
│   │
│   ├── core/                       # ── 核心类型与事件 ──
│   │   ├── __init__.py
│   │   ├── types.py                # Session, Iteration, Image, 所有 dataclass
│   │   ├── events.py               # 事件枚举 + 事件 dataclass
│   │   └── errors.py               # 自定义异常层次
│   │
│   ├── orchestrator/               # ── Agent Loop 引擎 ──
│   │   ├── __init__.py
│   │   ├── session.py              # Session 生命周期管理
│   │   ├── loop.py                 # 内层循环 (state machine)
│   │   └── interrupt.py            # 用户中断处理
│   │
│   ├── agents/                     # ── Agent 定义 ──
│   │   ├── __init__.py
│   │   ├── agent_a.py              # Agent A: LLM 调用 + 推理逻辑
│   │   └── prompts.py              # System prompts (含记忆使用指南)
│   │
│   ├── tools/                      # ── 工具系统 ──
│   │   ├── __init__.py
│   │   ├── base.py                 # Tool 基类 + ToolRegistry
│   │   ├── generate_image.py       # Agent B 封装
│   │   ├── inspect_image.py        # Agent C 封装
│   │   └── human_input.py          # ask_user 工具
│   │
│   ├── providers/                  # ── 模型提供者抽象 ──
│   │   ├── __init__.py
│   │   ├── base.py                 # Provider 抽象接口
│   │   ├── openai_compat.py        # OpenAI-compatible (GPT-4o, Qwen, DeepSeek...)
│   │   └── factory.py              # Provider 工厂
│   │
│   ├── memory/                     # ── 记忆模块 ──
│   │   ├── __init__.py
│   │   ├── store.py                # Markdown 文件读写
│   │   ├── index.py                # 索引管理
│   │   └── tools.py                # load_memory / search_memory / save_memory
│   │
│   ├── context/                    # ── 上下文管理 ──
│   │   ├── __init__.py
│   │   ├── assembler.py            # LLM 上下文组装
│   │   └── compaction.py           # 上下文压缩
│   │
│   ├── persistence/                # ── 持久化 ──
│   │   ├── __init__.py
│   │   ├── database.py             # SQLite 初始化 + 迁移
│   │   └── models.py               # ORM 模型 (轻量, 原生 SQL)
│   │
│   ├── api/                        # ── HTTP + WebSocket API ──
│   │   ├── __init__.py
│   │   ├── app.py                  # FastAPI 应用工厂
│   │   ├── routes.py               # REST 路由
│   │   ├── websocket.py            # WebSocket 事件推送
│   │   └── schemas.py              # API 请求/响应 Pydantic 模型
│   │
│   └── ui/                         # ── 前端静态文件 ──
│       └── static/
│           ├── index.html          # 主页面
│           ├── css/
│           │   └── style.css       # 样式
│           └── js/
│               ├── app.js          # 主应用逻辑 (AppState)
│               ├── api.js          # HTTP + WebSocket 通信
│               ├── renderer.js     # UI 渲染 (消息、图片、面板)
│               ├── viewer.js       # 图片查看器
│               └── events.js       # 事件监听与用户交互
│
├── memory/                         # ── 内置记忆文件 ──
│   ├── index.md
│   ├── prompts/
│   │   ├── portraits.md
│   │   ├── landscapes.md
│   │   ├── objects.md
│   │   └── concepts.md
│   └── inspections/
│       ├── _builtin_common.md
│       ├── _builtin_portrait.md
│       └── _builtin_scene.md
│
├── tests/
│   ├── conftest.py                 # Fixtures (tmp session, mock providers)
│   ├── test_config.py
│   ├── test_tools.py
│   ├── test_loop.py
│   ├── test_memory.py
│   └── test_integration.py
│
└── outputs/                        # 运行时输出 (gitignore)
```

---

## 2. M1: Foundation — 基础设施

**目标**: 项目可运行，配置可加载，工具可注册，Provider 可调用。

### 2.1 任务清单

| # | 任务 | 产出文件 | 参考 opencode |
|---|------|---------|-------------|
| 1.1 | 创建 `pyproject.toml`，定义依赖和项目元数据 | `pyproject.toml` | `packages/opencode/package.json` |
| 1.2 | 实现配置 schema + 加载器 | `config/schema.py`, `config/loader.py` | `packages/core/src/config.ts` |
| 1.3 | 实现核心类型定义 | `core/types.py`, `core/events.py`, `core/errors.py` | `packages/schema/src/session-message.ts` |
| 1.4 | 实现 Provider 抽象层 | `providers/base.py`, `providers/openai_compat.py`, `providers/factory.py` | `packages/llm/src/provider.ts` + `providers/` |
| 1.5 | 实现 Tool 基类 + ToolRegistry | `tools/base.py` | `packages/opencode/src/tool/tool.ts` + `registry.ts` |
| 1.6 | 实现 SQLite 持久化层 | `persistence/database.py`, `persistence/models.py` | `packages/core/src/session/` Drizzle schemas |

### 2.2 关键实现细节

#### 2.2.1 Config Schema (`config/schema.py`)

```python
from pydantic import BaseModel, Field
from typing import Optional, Literal

class AgentAConfig(BaseModel):
    provider: str = "openai"           # openai | anthropic | local
    model: str = "gpt-4o"
    api_base: str = "https://api.openai.com/v1"
    api_key: Optional[str] = None      # None = 从环境变量读
    temperature: float = 0.7
    max_tokens: int = 4096
    system_prompt: str = "default"     # "default" | path/to/custom.md

class AgentBConfig(BaseModel):
    provider: str = "local_zimage"
    model: str = "Z-Image-Turbo"
    api_base: str = "http://localhost:8000"
    endpoint: str = "/api/generate"
    default_params: dict = Field(default_factory=lambda: {
        "width": 1024, "height": 1024,
        "steps": 8, "guidance": 3.5, "seed": -1
    })
    prompt_format: str = "zimage"      # zimage | sd | dalle | flux

class AgentCConfig(BaseModel):
    provider: str = "openai"
    model: str = "gpt-4o"
    api_base: str = "https://api.openai.com/v1"
    api_key: Optional[str] = None
    temperature: float = 0.3           # 审核需要低温度
    max_tokens: int = 2048

class LoopConfig(BaseModel):
    max_iterations: int = 7
    auto_accept_threshold: float = 8.0
    compaction_threshold_tokens: int = 20000
    keep_recent_iterations: int = 2

class MemoryConfig(BaseModel):
    base_dir: str = "~/.drawagent/memory"
    auto_load: bool = True             # Session start 时自动 load index
    auto_save: bool = False            # 是否自动保存 (Phase 1 关闭，A 显式调用)

class AppConfig(BaseModel):
    agent_a: AgentAConfig = Field(default_factory=AgentAConfig)
    agent_b: AgentBConfig = Field(default_factory=AgentBConfig)
    agent_c: AgentCConfig = Field(default_factory=AgentCConfig)
    loop: LoopConfig = Field(default_factory=LoopConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    output_dir: str = "./outputs"
```

#### 2.2.2 Config Loader (`config/loader.py`)

参考 opencode 的多层发现 + latest-wins 模式：

```python
import os
import yaml
from pathlib import Path
from .schema import AppConfig

class ConfigLoader:
    """多层配置加载，later wins"""
    
    DISCOVERY_NAMES = [".drawagent.yaml", ".drawagent.yml", "drawagent.yaml"]
    
    @classmethod
    async def load(cls, project_dir: Path | None = None) -> AppConfig:
        configs: list[AppConfig] = []
        
        # Layer 1: 全局默认 (包内模板)
        default_path = Path(__file__).parent.parent.parent / ".drawagent.default.yaml"
        if default_path.exists():
            configs.append(cls._load_file(default_path))
        
        # Layer 2: 用户全局 (~/.drawagent/config.yaml)
        user_config = Path.home() / ".drawagent" / "config.yaml"
        if user_config.exists():
            configs.append(cls._load_file(user_config))
        
        # Layer 3: 项目目录 (从 project_dir 向上搜索)
        if project_dir:
            for parent in [project_dir, *project_dir.parents]:
                for name in cls.DISCOVERY_NAMES:
                    f = parent / name
                    if f.exists():
                        configs.append(cls._load_file(f))
                        break
        
        # Merge: later configs override earlier ones
        return cls._deep_merge(configs)
    
    @staticmethod
    def _load_file(path: Path) -> AppConfig:
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        # 环境变量替换: ${VAR_NAME}
        data = ConfigLoader._resolve_env_vars(data)
        return AppConfig(**data)
```

#### 2.2.3 Tool 基类 + Registry (`tools/base.py`)

参考 opencode 的 `Tool.define()` 模式（三段式：register → materialize → settle）：

```python
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable

@dataclass
class ToolResult:
    """工具执行结果"""
    tool_call_id: str
    name: str
    output: str                    # LLM 可读的文本结果
    metadata: dict = field(default_factory=dict)
    error: str | None = None

@dataclass
class ToolDefinition:
    """面向 LLM 的工具描述 (OpenAI function-calling 格式)"""
    name: str
    description: str
    parameters: dict               # JSON Schema

class BaseTool(ABC):
    """工具基类 — 参考 opencode Tool.define()"""
    
    name: str
    description: str
    parameters_schema: dict        # JSON Schema for function calling
    
    @abstractmethod
    async def execute(self, args: dict, ctx: "ToolContext") -> ToolResult:
        """执行工具。ctx 包含 session_id, agent 等上下文"""
        ...
    
    def to_openai_schema(self) -> dict:
        """转为 OpenAI function-calling 格式"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters_schema,
            }
        }
    
    def format_output_for_llm(self, result: ToolResult) -> str:
        """格式化工具结果供 LLM 阅读, 参考 opencode 的 XML-tag 格式"""
        if result.error:
            return f"<tool_error name='{self.name}'>{result.error}</tool_error>"
        return f"<tool_result name='{self.name}'>{result.output}</tool_result>"

@dataclass
class ToolContext:
    """工具执行上下文 — 参考 opencode 的 Tool.Context"""
    session_id: str
    agent: str
    message_id: str | None = None
    tool_call_id: str | None = None

@dataclass
class ToolMaterialization:
    """工具物化结果 — 参考 opencode 的 materialize() 返回值"""
    definitions: list[dict]        # OpenAI tool definitions
    settle: Callable[..., Awaitable[list[ToolResult]]]

class ToolRegistry:
    """工具注册中心 — 参考 opencode ToolRegistry"""
    
    def __init__(self):
        self._tools: dict[str, BaseTool] = {}
    
    def register(self, tool: BaseTool):
        self._tools[tool.name] = tool
    
    def materialize(self, enabled_tools: set[str] | None = None) -> ToolMaterialization:
        """
        物化工具：生成 LLM definitions + settle 函数
        参考 opencode: 此阶段做权限过滤
        """
        active = {
            name: tool for name, tool in self._tools.items()
            if enabled_tools is None or name in enabled_tools
        }
        
        definitions = [t.to_openai_schema() for t in active.values()]
        
        async def settle(tool_calls: list[dict], ctx: ToolContext) -> list[ToolResult]:
            results = []
            for call in tool_calls:
                tool = active.get(call["function"]["name"])
                if not tool:
                    results.append(ToolResult(
                        tool_call_id=call["id"],
                        name=call["function"]["name"],
                        output="",
                        error=f"Unknown tool: {call['function']['name']}"
                    ))
                    continue
                try:
                    args = json.loads(call["function"]["arguments"])
                except json.JSONDecodeError as e:
                    results.append(ToolResult(
                        tool_call_id=call["id"],
                        name=tool.name,
                        output="",
                        error=f"Invalid JSON arguments: {e}"
                    ))
                    continue
                ctx.tool_call_id = call["id"]
                result = await tool.execute(args, ctx)
                results.append(result)
            return results
        
        return ToolMaterialization(definitions=definitions, settle=settle)
```

#### 2.2.4 Provider 抽象 (`providers/base.py` + `providers/openai_compat.py`)

参考 opencode 的 `Protocol` + `Route` 设计，简化版：

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncIterator, Literal

@dataclass
class LLMMessage:
    role: Literal["system", "user", "assistant", "tool"]
    content: str | list[dict]     # str for text, list[dict] for multimodal
    tool_call_id: str | None = None
    name: str | None = None       # Tool name (for tool role)

@dataclass
class LLMStreamEvent:
    """参考 opencode LLMEvent 的简化版"""
    type: Literal["text_delta", "tool_call_start", "tool_call_args", "step_finish", "error"]
    content: str = ""
    tool_name: str | None = None
    tool_call_id: str | None = None
    finish_reason: str | None = None  # "stop" | "tool_calls" | "length"
    usage: dict | None = None

class LLMProvider(ABC):
    """LLM Provider 抽象 — 参考 opencode Provider + Protocol"""
    
    @abstractmethod
    async def chat_stream(
        self,
        messages: list[LLMMessage],
        tools: list[dict] | None = None,
        tool_choice: str | None = None,
        **kwargs
    ) -> AsyncIterator[LLMStreamEvent]:
        """流式对话 — 返回标准化事件流"""
        ...
    
    @abstractmethod
    async def chat(
        self,
        messages: list[LLMMessage],
        tools: list[dict] | None = None,
        **kwargs
    ) -> dict:
        """非流式对话 — 返回完整响应"""
        ...

class VisionProvider(ABC):
    """多模态视觉 Provider"""
    
    @abstractmethod
    async def analyze_image(
        self,
        image_data: bytes,           # PNG/JPEG 二进制
        question: str,
        context: str | None = None,
        **kwargs
    ) -> str:
        """分析图像并返回文字描述"""
        ...
```

OpenAI-compatible 实现 (`providers/openai_compat.py`)：

```python
import httpx
from .base import LLMProvider, LLMMessage, LLMStreamEvent

class OpenAICompatibleProvider(LLMProvider, VisionProvider):
    """
    OpenAI-compatible API provider
    支持: OpenAI, Anthropic (via OpenAI-compat proxy),
          Qwen, DeepSeek, 本地 vLLM/Ollama
    """
    
    def __init__(self, api_base: str, api_key: str, model: str):
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key
        self.model = model
        self._client = httpx.AsyncClient(timeout=120.0)
    
    async def chat_stream(self, messages, tools=None, tool_choice=None, **kwargs):
        body = {
            "model": self.model,
            "messages": [self._format_message(m) for m in messages],
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            body["tools"] = tools
        if tool_choice:
            body["tool_choice"] = tool_choice
        
        async with self._client.stream(
            "POST", f"{self.api_base}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json=body,
        ) as response:
            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                if line == "data: [DONE]":
                    break
                data = json.loads(line[6:])
                yield from self._parse_stream_chunk(data)
    
    async def analyze_image(self, image_data, question, context=None, **kwargs):
        """调用 vision API"""
        import base64
        b64 = base64.b64encode(image_data).decode()
        messages = [{
            "role": "user",
            "content": [
                {"type": "text", "text": question},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}
            ]
        }]
        resp = await self._client.post(
            f"{self.api_base}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"model": self.model, "messages": messages, "max_tokens": 2048},
        )
        return resp.json()["choices"][0]["message"]["content"]
```

---

## 3. M2: Core Loop — Agent 引擎

**目标**: Agent A 能接收用户需求、调用工具、运行完整的生成-审核迭代循环。

### 3.1 任务清单

| # | 任务 | 产出 | 参考 opencode |
|---|------|------|-------------|
| 2.1 | 实现 Session 状态管理 | `orchestrator/session.py` | `packages/core/src/session/` message-v2.ts |
| 2.2 | 实现 Agent A 的 LLM 推理循环 | `agents/agent_a.py` | `packages/opencode/src/session/prompt.ts` |
| 2.3 | 实现 generate_image 工具 | `tools/generate_image.py` | — (HTTP client to Z-Image) |
| 2.4 | 实现 inspect_image 工具 | `tools/inspect_image.py` | — (VisionProvider) |
| 2.5 | 实现内层循环 (state machine) | `orchestrator/loop.py` | `packages/core/src/session/runner/llm.ts` |
| 2.6 | 实现用户中断处理 | `orchestrator/interrupt.py` | Steer 机制 |
| 2.7 | 实现上下文组装器 | `context/assembler.py` | `packages/core/src/session/context-epoch.ts` |
| 2.8 | 实现事件广播 | (集成到 loop.py) | EventV2 服务 |

### 3.2 关键实现细节

#### 3.2.1 Session 状态管理 (`orchestrator/session.py`)

```python
from dataclasses import dataclass, field
from enum import Enum
import asyncio
from datetime import datetime

class SessionState(Enum):
    IDLE = "idle"                    # 等待用户输入
    REFINING = "refining"            # A 与用户交流需求
    PLANNING = "planning"            # A 制定检查计划
    GENERATING = "generating"        # B 生成中
    INSPECTING = "inspecting"        # C 审核中
    ANALYZING = "analyzing"          # A 评估质量
    INTERRUPTED = "interrupted"      # 用户中断
    COMPLETED = "completed"          # 已交付

@dataclass
class Session:
    id: str
    created_at: datetime = field(default_factory=datetime.now)
    state: SessionState = SessionState.IDLE
    
    # 用户需求
    user_request: str = ""
    
    # 迭代历史
    iterations: list["Iteration"] = field(default_factory=list)
    
    # 中断控制
    interrupt_event: asyncio.Event = field(default_factory=asyncio.Event)
    pending_action: str | None = None   # "steer" | "accept" | "modify" | "rollback"
    steer_message: str | None = None
    
    # 配置引用
    max_iterations: int = 7
    
    # 记忆引用
    loaded_memories: list[str] = field(default_factory=list)
```

#### 3.2.2 Agent A 推理循环 (`agents/agent_a.py`)

参考 opencode 的 `run_turn()` — LLM 流式调用 + 工具调用并行处理：

```python
import json
from drawagent.tools.base import ToolRegistry, ToolMaterialization, ToolContext, ToolResult
from drawagent.providers.base import LLMProvider, LLMMessage, LLMStreamEvent
from drawagent.core.types import Session, Iteration

class AgentA:
    """Agent A — 主控 LLM 的推理引擎"""
    
    def __init__(
        self,
        provider: LLMProvider,
        tool_registry: ToolRegistry,
        system_prompt: str,
    ):
        self.provider = provider
        self.registry = tool_registry
        self.system_prompt = system_prompt
    
    async def run_turn(
        self,
        session: Session,
        messages: list[LLMMessage],
        enabled_tools: set[str] | None = None,
    ) -> "TurnResult":
        """
        执行一次 Agent A 推理 turn
        参考 opencode runTurn(): stream LLM → 收集 tool_calls → 并行 settle → 继续
        
        与 opencode 的关键差异: Agent A 的 turn 由程序驱动（state machine），
        不是 LLM 自主驱动。A 只在指定状态下被调用。
        """
        materialization = self.registry.materialize(enabled_tools)
        
        # 构建消息列表
        full_messages = [
            LLMMessage(role="system", content=self.system_prompt),
            *messages,
        ]
        
        # 流式调用 LLM
        tool_calls: list[dict] = []
        text_output: list[str] = []
        finish_reason = None
        
        async for event in self.provider.chat_stream(
            messages=full_messages,
            tools=materialization.definitions,
        ):
            if event.type == "text_delta":
                text_output.append(event.content)
                # 可以 yield 给 UI (实时打字效果)
            
            elif event.type == "tool_call_start":
                # 收集 tool call 信息
                pass
            
            elif event.type == "tool_call_args":
                # 累积 tool call arguments
                pass
            
            elif event.type == "step_finish":
                finish_reason = event.finish_reason
        
        text = "".join(text_output)
        
        # 如果有 tool calls，并行执行
        tool_results: list[ToolResult] = []
        if tool_calls:
            tool_results = await materialization.settle(
                tool_calls,
                ctx=ToolContext(session_id=session.id, agent="A")
            )
            
            # 工具结果注入消息列表
            for tr in tool_results:
                full_messages.append(LLMMessage(
                    role="tool",
                    content=tr.output,
                    tool_call_id=tr.tool_call_id,
                    name=tr.name,
                ))
            
            # 递归调用: LLM 处理工具结果后继续推理
            continuation = await self.provider.chat(
                messages=full_messages,
                tools=materialization.definitions,
            )
            text += "\n" + continuation.get("content", "")
        
        return TurnResult(
            text=text,
            tool_calls=tool_calls,
            tool_results=tool_results,
            finish_reason=finish_reason,
        )
```

#### 3.2.3 内层循环 (`orchestrator/loop.py`)

这是系统的核心 — 程序驱动的状态机，参考 opencode 双层循环但改为确定性的阶段推进：

```python
import asyncio
from drawagent.core.types import Session, Iteration, SessionState
from drawagent.core.events import DrawEvent, EventBus
from drawagent.agents.agent_a import AgentA
from drawagent.agents.prompts import PROMPT_REFINE, PROMPT_EVALUATE

class InnerLoop:
    """
    内层循环 — 程序驱动的状态机
    
    与 opencode 的差异: 
    - opencode: LLM 自主决定何时调用工具、何时停止
    - DrawAgent: 程序按固定阶段推进，A 在每个阶段做局部决策
    
    这减少了 LLM 的"自由度"，换来更可预测的行为和更低的 token 消耗。
    """
    
    def __init__(self, session: Session, agent_a: AgentA, event_bus: EventBus):
        self.session = session
        self.agent_a = agent_a
        self.events = event_bus
    
    async def run(self, initial_prompt: str) -> list[dict]:
        """
        执行内层循环直到终止
        返回: 最终图像列表
        """
        iteration = 0
        current_prompt = initial_prompt
        observations_history = []
        images_history = []
        
        while True:
            # ── 检查中断 ──
            if self.session.interrupt_event.is_set():
                action = await self._handle_interrupt()
                if action == "accept":
                    return images_history[-1] if images_history else []
                if action == "steer":
                    current_prompt = self.session.steer_message
                    self.session.interrupt_event.clear()
                # 其他 action 在 _handle_interrupt 中处理
            
            iteration += 1
            if iteration > self.session.max_iterations:
                await self.events.emit(DrawEvent.LOOP_TERMINATED, 
                    reason="max_iterations")
                return self._pick_best(images_history)
            
            await self.events.emit(DrawEvent.ITERATION_STARTED, iteration=iteration)
            
            # ── Phase 1: REFINE (仅第2轮起) ──
            if iteration > 1:
                refinement = await self._refine_prompt(
                    current_prompt, observations_history
                )
                current_prompt = refinement
                await self.events.emit(DrawEvent.PROMPT_REFINED, 
                    prompt=current_prompt)
            
            # ── Phase 2: PLAN ──
            inspection_plan = await self._plan_inspections(
                current_prompt, observations_history
            )
            await self.events.emit(DrawEvent.INSPECTION_PLAN_READY, 
                plan=inspection_plan)
            
            # ── Phase 3: GENERATE ──
            self.session.state = SessionState.GENERATING
            await self.events.emit(DrawEvent.GENERATION_STARTED)
            
            gen_params = await self._select_generation_params(iteration)
            images = await self._generate_images(current_prompt, gen_params)
            
            await self.events.emit(DrawEvent.IMAGES_READY, images=images)
            
            # ── Phase 4: INSPECT ──
            self.session.state = SessionState.INSPECTING
            inspection_results = []
            for task in inspection_plan:
                result = await self._inspect_image(images, task)
                inspection_results.append(result)
                await self.events.emit(DrawEvent.INSPECTION_TASK_DONE,
                    task=task, result=result)
            
            # ── Phase 5: EVALUATE ──
            self.session.state = SessionState.ANALYZING
            decision = await self._evaluate_quality(
                current_prompt, inspection_results, iteration
            )
            await self.events.emit(DrawEvent.QUALITY_DECISION, 
                decision=decision)
            
            if decision.passed:
                await self.events.emit(DrawEvent.LOOP_TERMINATED,
                    reason="quality_passed")
                return images
            
            # 记录本轮观察
            observations_history.append({
                "iteration": iteration,
                "prompt": current_prompt,
                "inspection_results": inspection_results,
                "decision": decision,
            })
        
    # ── 各 Phase 的私有方法 ──
    
    async def _refine_prompt(self, prompt, history) -> str:
        """调用 Agent A 修改提示词"""
        messages = [
            LLMMessage(role="system", content=PROMPT_REFINE),
            LLMMessage(role="user", content=f"""
原始需求: {self.session.user_request}
当前提示词: {prompt}
历史问题: {json.dumps(history[-1] if history else {}, ensure_ascii=False)}

请分析问题并输出修改后的提示词。
"""),
        ]
        result = await self.agent_a.provider.chat(messages)
        # 从 result 中提取新 prompt
        return self._extract_prompt(result["content"])
    
    # ... 更多方法
```

#### 3.2.4 中断处理 (`orchestrator/interrupt.py`)

```python
class InterruptHandler:
    """
    用户中断处理 — 参考 opencode Steer 机制
    
    opencode 的 steer 是文本消息 ("use Python instead")，
    DrawAgent 用具名 Action 更精确：
    """
    
    VALID_ACTIONS = {
        "pause": "暂停执行",
        "resume": "恢复执行",
        "accept_current": "接受当前图像",
        "steer": "修改方向 (附新需求)",
        "modify_prompt": "手动修改提示词",
        "rollback": "回退到指定迭代",
    }
    
    async def handle(self, session: Session, action: str, data: dict | None = None):
        """处理用户中断"""
        if action == "pause":
            session.state = SessionState.INTERRUPTED
            # 不设置 interrupt_event，等待 resume
        
        elif action == "resume":
            session.state = SessionState.GENERATING
            session.interrupt_event.clear()
        
        elif action == "accept_current":
            session.pending_action = "accept"
            session.interrupt_event.set()
        
        elif action == "steer":
            session.pending_action = "steer"
            session.steer_message = data.get("message", "")
            session.interrupt_event.set()
        
        elif action == "modify_prompt":
            session.pending_action = "modify"
            session.steer_message = data.get("prompt", "")
            session.interrupt_event.set()
        
        elif action == "rollback":
            session.pending_action = "rollback"
            session.steer_message = str(data.get("target_iteration", 0))
            session.interrupt_event.set()
```

#### 3.2.5 上下文组装器 (`context/assembler.py`)

参考 opencode 的 Context Epoch 三层模型：

```python
class ContextAssembler:
    """
    上下文组装器
    
    组装顺序:
    1. SystemContext   (固定 — A 的 system prompt)
    2. MemoryContext   (来自记忆模块加载的相关内容)
    3. CompactedHistory (如果有压缩过的历史)
    4. RecentIterations (最近 2 轮完整迭代)
    5. CurrentMessages  (当前 turn 的消息)
    """
    
    async def assemble(
        self,
        session: Session,
        compacted: CompactedHistory | None,
        current_messages: list[LLMMessage],
    ) -> list[LLMMessage]:
        messages = []
        
        # 1. System prompt (
        messages.append(LLMMessage(
            role="system",
            content=await self._build_system_prompt(session)
        ))
        
        # 2. Memory context (注入已加载的记忆)
        if session.loaded_memories:
            for memory_file in session.loaded_memories:
                content = await self._load_memory_content(memory_file)
                if content:
                    messages.append(LLMMessage(
                        role="system",
                        content=f"<memory source='{memory_file}'>\n{content}\n</memory>"
                    ))
        
        # 3. Compacted history
        if compacted:
            messages.append(LLMMessage(
                role="system",
                content=compacted.to_context_string()
            ))
        
        # 4. Recent iterations (保留最近 N 轮完整信息)
        for iter_record in session.iterations[-2:]:
            messages.append(LLMMessage(
                role="system",
                content=iter_record.to_context_string()
            ))
        
        # 5. Current conversation
        messages.extend(current_messages)
        
        return messages
    
    async def _build_system_prompt(self, session: Session) -> str:
        """构建 Agent A 的完整 system prompt"""
        from drawagent.agents.prompts import BASE_SYSTEM_PROMPT, MEMORY_USAGE_GUIDE
        
        parts = [BASE_SYSTEM_PROMPT]
        
        # 注入当前模型信息
        parts.append(f"\n## 当前画图模型: {session.agent_b_model}")
        parts.append(f"\n{session.agent_b_prompt_format_guide}")
        
        # 注入记忆使用指南
        parts.append(f"\n{MEMORY_USAGE_GUIDE}")
        
        return "\n".join(parts)
```

---

## 4. M3: Memory — 记忆模块

**目标**: 记忆系统完整接入 loop，支持跨会话提示词复用和检查项积累。

### 4.1 任务清单

| # | 任务 | 产出 |
|---|------|------|
| 3.1 | 实现 Markdown 文件读写 | `memory/store.py` |
| 3.2 | 实现索引管理 (index.md) | `memory/index.py` |
| 3.3 | 实现记忆工具 (load/save/search) | `memory/tools.py` |
| 3.4 | 编写内置检查项 markdown 文件 | `memory/inspections/_builtin_*.md` |
| 3.5 | 编写内置提示词模板 markdown 文件 | `memory/prompts/*.md` |
| 3.6 | 接入 Agent A system prompt | `agents/prompts.py` |

### 4.2 关键实现细节

#### 4.2.1 Memory Store (`memory/store.py`)

```python
import re
from pathlib import Path

class MemoryStore:
    """Markdown 记忆文件读写"""
    
    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir).expanduser().resolve()
    
    def _safe_path(self, category: str) -> Path:
        """安全检查：确保路径在 base_dir 内，防止目录穿越"""
        # category 只能是字母/数字/下划线/斜杠/连字符
        if not re.match(r'^[a-zA-Z0-9_/\-]+$', category):
            raise ValueError(f"Invalid category name: {category}")
        path = (self.base_dir / f"{category}.md").resolve()
        if not str(path).startswith(str(self.base_dir)):
            raise ValueError(f"Path traversal detected: {category}")
        return path
    
    async def read(self, category: str) -> str | None:
        """读取整个记忆文件"""
        path = self._safe_path(category)
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8")
    
    async def write(self, category: str, content: str, append: bool = True):
        """写入记忆文件"""
        path = self._safe_path(category)
        path.parent.mkdir(parents=True, exist_ok=True)
        
        if append and path.exists():
            existing = path.read_text(encoding="utf-8")
            # 确保分隔
            if not existing.endswith("\n\n"):
                content = "\n\n" + content
            content = existing + content
        
        path.write_text(content, encoding="utf-8")
    
    async def search(self, query: str) -> list[dict]:
        """
        简单关键词搜索 (Phase 1)
        Phase 2/3 可升级为 SQLite 索引或向量搜索
        """
        results = []
        keywords = query.lower().split()
        
        for md_file in self.base_dir.rglob("*.md"):
            if md_file.name == "index.md":
                continue
            try:
                content = md_file.read_text(encoding="utf-8")
            except Exception:
                continue
            
            # 计算匹配分
            score = sum(1 for kw in keywords if kw in content.lower())
            if score > 0:
                # 提取相关片段
                results.append({
                    "file": str(md_file.relative_to(self.base_dir)),
                    "score": score,
                    "snippet": content[:500],  # 首 500 字符
                })
        
        results.sort(key=lambda r: r["score"], reverse=True)
        return results[:5]  # 返回 top-5
```

#### 4.2.2 记忆工具注册 (`memory/tools.py`)

```python
from drawagent.tools.base import BaseTool, ToolContext, ToolResult
from drawagent.memory.store import MemoryStore
from drawagent.memory.index import MemoryIndex

class LoadMemoryTool(BaseTool):
    name = "load_memory"
    description = "加载指定类别的记忆文件。类别名如 'prompts/portraits' 或 'inspections/_builtin_portrait'。"
    parameters_schema = {
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "description": "记忆类别, e.g. 'prompts/portraits', 'inspections/user_feedback'"
            }
        },
        "required": ["category"]
    }
    
    def __init__(self, store: MemoryStore):
        self.store = store
    
    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        content = await self.store.read(args["category"])
        if content is None:
            return ToolResult(
                tool_call_id=ctx.tool_call_id,
                name=self.name,
                output=f"<memory_not_found category='{args['category']}'>记忆文件不存在</memory_not_found>"
            )
        # 截断过长的记忆 (参考 opencode 输出截断)
        if len(content) > 8000:
            content = content[:8000] + "\n\n(记忆过长，已截断。使用 search_memory 可精确检索。)"
        return ToolResult(
            tool_call_id=ctx.tool_call_id,
            name=self.name,
            output=f"<memory category='{args['category']}'>\n{content}\n</memory>"
        )

class SearchMemoryTool(BaseTool):
    name = "search_memory"
    description = "在所有记忆中搜索与查询相关的内容"
    parameters_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索关键词"}
        },
        "required": ["query"]
    }
    
    def __init__(self, store: MemoryStore):
        self.store = store
    
    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        results = await self.store.search(args["query"])
        if not results:
            return ToolResult(
                tool_call_id=ctx.tool_call_id,
                name=self.name,
                output="<search_results>未找到匹配的记忆</search_results>"
            )
        
        output = "<search_results>\n"
        for r in results:
            output += f"  <hit file='{r['file']}' score='{r['score']}'>\n"
            output += f"    {r['snippet'][:300]}\n"
            output += f"  </hit>\n"
        output += "</search_results>"
        
        return ToolResult(
            tool_call_id=ctx.tool_call_id,
            name=self.name,
            output=output
        )

class SaveMemoryTool(BaseTool):
    name = "save_memory"
    description = "将经验保存到记忆系统。Agent A 应在 session 结束时评估哪些值得保存。"
    parameters_schema = {
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "description": "目标类别, e.g. 'prompts/portraits'"
            },
            "content": {
                "type": "string",
                "description": "Markdown 格式的记忆条目"
            },
            "reason": {
                "type": "string",
                "description": "保存原因 (用于日志审计)"
            }
        },
        "required": ["category", "content"]
    }
    
    def __init__(self, store: MemoryStore, index: MemoryIndex):
        self.store = store
        self.index = index
    
    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        await self.store.write(args["category"], args["content"], append=True)
        
        # 更新索引
        await self.index.update_from_file(args["category"])
        
        return ToolResult(
            tool_call_id=ctx.tool_call_id,
            name=self.name,
            output=f"<memory_saved category='{args['category']}'>记忆已保存</memory_saved>",
            metadata={"reason": args.get("reason", "")}
        )
```

---

## 5. M4: API + UI — 交互层

**目标**: 完整的 Web 应用，用户可通过 Chat UI 完成整个画图流程。

### 5.1 任务清单

| # | 任务 | 产出 |
|---|------|------|
| 4.1 | 实现 FastAPI 应用工厂 | `api/app.py` |
| 4.2 | 实现 REST 路由 | `api/routes.py` |
| 4.3 | 实现 WebSocket 事件推送 | `api/websocket.py` |
| 4.4 | 实现 API 请求/响应 schema | `api/schemas.py` |
| 4.5 | 改写 webui_v6.html 为 DrawAgent UI | `ui/static/` |
| 4.6 | 实现实时进度展示 (迭代卡片、审核面板) | `ui/static/js/renderer.js` |
| 4.7 | 实现中断控制按钮 | `ui/static/js/events.js` |
| 4.8 | 实现图片查看器 | `ui/static/js/viewer.js` |

### 5.2 关键实现细节

#### 5.2.1 REST API (`api/routes.py`)

```python
from fastapi import APIRouter, HTTPException
from .schemas import (
    CreateSessionRequest, CreateSessionResponse,
    SendMessageRequest, SendMessageResponse,
    InterruptRequest, SessionHistoryResponse,
)

router = APIRouter(prefix="/api")

@router.post("/sessions", response_model=CreateSessionResponse)
async def create_session(req: CreateSessionRequest):
    """创建新画图会话"""
    session = await session_manager.create(req.config_override)
    return CreateSessionResponse(session_id=session.id)

@router.post("/sessions/{session_id}/message", response_model=SendMessageResponse)
async def send_message(session_id: str, req: SendMessageRequest):
    """发送用户消息，触发画图流程"""
    session = await session_manager.get(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    
    # 将用户消息加入队列，启动内层循环
    result = await outer_loop.enqueue(session_id, req.text)
    return SendMessageResponse(
        session_id=session_id,
        accepted=True,
        message_id=result.message_id,
    )

@router.post("/sessions/{session_id}/interrupt")
async def interrupt_session(session_id: str, req: InterruptRequest):
    """中断当前会话"""
    await interrupt_handler.handle(session_id, req.action, req.data)

@router.get("/sessions/{session_id}/history", response_model=SessionHistoryResponse)
async def get_history(session_id: str):
    """获取会话完整历史 (含图片引用)"""
    session = await session_manager.get(session_id)
    return SessionHistoryResponse.from_session(session)

@router.get("/images/{image_ref}")
async def serve_image(image_ref: str):
    """提供图像文件"""
    path = resolve_image_path(image_ref)
    return FileResponse(path, media_type="image/png")
```

#### 5.2.2 WebSocket 事件推送 (`api/websocket.py`)

参考 opencode 的 Event Sourcing，前端通过 WebSocket 实时订阅 session 事件：

```python
from fastapi import WebSocket, WebSocketDisconnect
import json
import asyncio

class WebSocketManager:
    """WebSocket 连接管理"""
    
    def __init__(self):
        self._connections: dict[str, list[WebSocket]] = {}  # session_id → [ws, ...]
    
    async def connect(self, session_id: str, ws: WebSocket):
        await ws.accept()
        if session_id not in self._connections:
            self._connections[session_id] = []
        self._connections[session_id].append(ws)
    
    async def disconnect(self, session_id: str, ws: WebSocket):
        if session_id in self._connections:
            self._connections[session_id].remove(ws)
    
    async def broadcast(self, session_id: str, event_type: str, **data):
        """向某个 session 的所有 WebSocket 连接广播事件"""
        if session_id not in self._connections:
            return
        message = json.dumps({"type": event_type, **data}, ensure_ascii=False)
        dead = []
        for ws in self._connections[session_id]:
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._connections[session_id].remove(ws)

# 路由
@router.websocket("/ws/sessions/{session_id}")
async def session_websocket(ws: WebSocket, session_id: str):
    await ws_manager.connect(session_id, ws)
    try:
        while True:
            # 接收客户端消息 (中断指令等)
            data = await ws.receive_text()
            msg = json.loads(data)
            if msg.get("type") == "interrupt":
                await interrupt_handler.handle(
                    session_id,
                    msg["action"],
                    msg.get("data")
                )
    except WebSocketDisconnect:
        await ws_manager.disconnect(session_id, ws)
```

#### 5.2.3 前端状态管理 (`ui/static/js/app.js`)

参考 webui_v6.html 的 AppState 模式，扩展到支持 DrawAgent 的事件流：

```javascript
const AppState = {
    // ── 会话 ──
    currentSessionId: null,
    sessions: {},                // { session_id: { messages[], iterations[] } }
    
    // ── UI 状态 ──
    isLoading: false,            // 是否正在生成
    currentIteration: 0,         // 当前迭代轮次
    loopStatus: null,            // null | "iterating" | "completed"
    
    // ── 用户设置 (localStorage) ──
    settings: {
        serverUrl: 'http://localhost:8000',
        generationParams: {
            width: 1024, height: 1024,
            numImages: 2,
            steps: 8,
            guidance: 3.5,
            seed: -1,
        },
        autoAccept: false,       // 质量达标后自动接受
        showIntermediate: true,  // 展示中间版本
    },
    
    // ── 图片查看器 ──
    viewer: {
        isOpen: false,
        currentIndex: 0,
        images: [],
    }
};
```

#### 5.2.4 WebSocket 事件处理 (`ui/static/js/api.js`)

```javascript
const WSClient = {
    ws: null,
    sessionId: null,
    
    connect(sessionId) {
        this.sessionId = sessionId;
        const url = `${AppState.settings.serverUrl.replace('http', 'ws')}/ws/sessions/${sessionId}`;
        this.ws = new WebSocket(url);
        
        this.ws.onmessage = (event) => {
            const msg = JSON.parse(event.data);
            EventRouter.dispatch(msg);
        };
        
        this.ws.onclose = () => {
            console.log('WebSocket disconnected');
        };
    },
    
    sendInterrupt(action, data = {}) {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify({
                type: 'interrupt',
                action: action,
                data: data
            }));
        }
    },
    
    disconnect() {
        if (this.ws) this.ws.close();
    }
};

const EventRouter = {
    /**
     * 将后端事件分发到对应的 UI 更新函数
     * 参考 opencode EventV2 事件类型
     */
    dispatch(event) {
        console.debug('[Event]', event.type, event);
        
        switch (event.type) {
            // ── 外层循环事件 ──
            case 'agent.question':
                UI.addSystemMessage(event.text);
                UI.showInputPrompt(event.text);
                break;
            
            // ── 内层循环事件 ──
            case 'iteration.started':
                UI.addIterationCard(event.iteration);
                AppState.currentIteration = event.iteration;
                break;
            
            case 'prompt.refined':
                UI.addPromptDiff(event.before, event.after, event.changes);
                break;
            
            case 'generation.started':
                UI.showGenerationProgress(event.num_images);
                break;
            
            case 'generation.progress':
                UI.updateGenerationProgress(event.step, event.total);
                break;
            
            case 'images.ready':
                UI.displayImages(event.images, event.iteration);
                break;
            
            case 'inspection.task_done':
                UI.addInspectionCard(event.task, event.result);
                break;
            
            case 'inspection.complete':
                UI.showInspectionSummary(event.results);
                break;
            
            case 'quality.decision':
                UI.showQualityDecision(event.decision);
                if (event.decision.passed && AppState.settings.autoAccept) {
                    UI.showNotification('质量达标，已自动接受', 'success');
                }
                break;
            
            case 'loop.terminated':
                UI.showLoopResult(event.reason);
                AppState.loopStatus = 'completed';
                UI.hideGenerationProgress();
                break;
            
            case 'error':
                UI.showError(event.message);
                break;
        }
    }
};
```

#### 5.2.5 新增 UI 组件概述

| 组件 | 说明 | 来源 |
|------|------|------|
| 迭代卡片 | 每轮迭代的折叠面板，显示 "第N轮 → prompt → 图片 → 审核 → 判断" | **新增** |
| 审核面板 | 以卡片形式展示 C 的观察结果 + A 的质量判断 | **新增** |
| 提示词 Diff | 展示每轮 prompt 的变化 (红色删除 + 绿色新增) | **新增** |
| 中断按钮组 | "停止并查看" / "修改方向" / "接受当前" / "回退版本" | **新增** |
| 迭代进度条 | 显示当前第几轮/最大几轮 | **新增** |
| 图片查看器 | 点击放大，前后导航，键盘操作 | 参考 webui_v6.html |
| 左侧会话列表 | 历史会话切换、新建、删除 | 参考 webui_v6.html |
| 参数面板 | 宽度、高度、张数、步数、引导力等滑块 | 参考 webui_v6.html |

---

## 6. M5: Polish — 测试与发布

### 6.1 任务清单

| # | 任务 |
|---|------|
| 5.1 | 单元测试: Config, Tools, Memory |
| 5.2 | 集成测试: 完整 loop 流程 (Mock Provider) |
| 5.3 | CLI 模式: `python -m drawagent --cli` |
| 5.4 | 配置文件模板 + 使用文档 |
| 5.5 | pyproject.toml scripts: `drawagent serve` / `drawagent cli` |

### 6.2 测试示例

```python
# tests/test_loop.py
import pytest
from drawagent.orchestrator.loop import InnerLoop
from drawagent.core.types import Session
from drawagent.tools.base import ToolRegistry
from drawagent.providers.base import LLMProvider

class MockLLMProvider(LLMProvider):
    """Mock LLM 用于测试 loop 逻辑"""
    def __init__(self, responses: list[str]):
        self.responses = responses
        self.call_count = 0
    
    async def chat(self, messages, **kwargs):
        response = self.responses[self.call_count % len(self.responses)]
        self.call_count += 1
        return {"content": response}

@pytest.mark.asyncio
async def test_basic_loop_completes():
    """测试基础 loop 能正常完成一轮迭代"""
    mock = MockLLMProvider([
        # Prompt refinement
        "好的，我来优化提示词...",
        # Inspection plan
        "检查项: 1) 手指数量 2) 发型",
        # Quality evaluation
        '{"passed": true, "confidence": 0.95, "reasoning": "所有检查项通过"}'
    ])
    
    registry = ToolRegistry()
    # 注册 mock tools...
    
    agent_a = AgentA(mock, registry, "test system prompt")
    session = Session(id="test-1", user_request="画一个女孩")
    loop = InnerLoop(session, agent_a, mock_event_bus)
    
    result = await loop.run("test prompt")
    assert result is not None
```

---

## 7. 依赖关系图

```
Phase 1 (Foundation)
  config ──► core/types
  providers ──► core/types
  tools/base ──► core/types
  persistence ──► core/types

Phase 2 (Core Loop)  
  agents/agent_a ──► providers + tools/base
  tools/generate_image ──► providers (HTTP to B)
  tools/inspect_image ──► providers (Vision)
  orchestrator/loop ──► agents/agent_a + tools + core/events
  orchestrator/interrupt ──► orchestrator/session
  context/assembler ──► agents/prompts + memory

Phase 3 (Memory)
  memory/store ──► (独立)
  memory/tools ──► tools/base + memory/store
  agents/prompts ──► memory (MEMORY_USAGE_GUIDE)

Phase 4 (API + UI)
  api/routes ──► orchestrator + persistence
  api/websocket ──► orchestrator + core/events
  ui/static ──► api (HTTP + WS)
```

---

## 8. 关键设计决策记录

| 决策 | 选择 | 理由 |
|------|------|------|
| Loop 驱动方式 | 程序状态机 | 画图流程步骤确定，程序驱动更可控、更省 token |
| Agent A turn 模型 | 非流式为主，流式可选 | 需要完整解析 JSON 判断结果，cost 优先于 latency |
| 工具执行 | 串行 settle | 画图工具的调用有依赖顺序（先生成再审核），不需要并发 settle |
| 前端框架 | 纯 JS | webui_v6.html 已证明从零写 Chat UI 可行，无需引入 React 复杂度 |
| LLM Provider | OpenAI-compat 优先 | 几乎所有模型服务都提供 OpenAI-compatible 端点 |
| 图像传输 | HTTP 文件服务 + 引用 | 不在 WebSocket 中传 base64，避免阻塞和内存问题 |
| 记忆存储 | Markdown 文件 | Agent 和人类都可读写，无需额外数据库 |

---

> **文档版本**: v1.0 | **日期**: 2026-06-27 | **状态**: 待确认后开始 M1
