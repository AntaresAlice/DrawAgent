from pydantic import BaseModel, Field
from typing import Literal, Optional


class AgentAConfig(BaseModel):
    """Agent A (main LLM) configuration."""

    provider: str = "openai"
    model: str = "gpt-4o"
    api_base: str = "https://api.openai.com/v1"
    api_key: Optional[str] = None
    temperature: float = 0.7
    max_tokens: int = 4096
    system_prompt: str = "default"


class AgentBConfig(BaseModel):
    """Agent B (image generator) configuration.

    Supports two backends:
    - http: Direct HTTP API POST with JSON body
    - mcp: Model Context Protocol server (stdio or remote)
    """

    type: Literal["http", "mcp"] = "http"
    provider: str = "local_zimage"
    model: str = "Z-Image-Turbo"
    api_base: str = "http://localhost:8000"
    endpoint: str = "/api/generate"

    # MCP mode
    mcp_command: list[str] | None = None
    mcp_url: str | None = None
    mcp_tool_name: str = "generate_image"
    mcp_keep_alive: bool = True  # False = close MCP after generation (frees VRAM, reconnects next iter)

    default_params: dict = Field(default_factory=lambda: {
        "width": 1024,
        "height": 1024,
        "steps": 30,
        "guidance": 7.0,
        "cfg_truncation": 0.6,
        "max_sequence_length": 512,
        "seed": -1,
    })

    # Model-specific hints injected into Agent A's system prompt.
    # Contains recommended params, prompt writing tips, known limitations.
    model_hints: str = ""
    prompt_format: str = "zimage"


class AgentCConfig(BaseModel):
    """Agent C (vision inspector) configuration."""

    provider: str = "openai"
    model: str = "gpt-4o"
    api_base: str = "https://api.openai.com/v1"
    api_key: Optional[str] = None
    temperature: float = 0.3
    max_tokens: int = 2048


class AgenticCompactionConfig(BaseModel):
    """Compaction settings for agentic mode (LLM-driven summarization)."""

    enabled: bool = True
    buffer_tokens: int = 20480
    keep_tokens: int = 8000
    summary_max_tokens: int = 4096


class AgenticLearningConfig(BaseModel):
    """Experience accumulation settings for agentic mode."""

    enabled: bool = True
    max_lessons: int = 10


class AgenticLoopConfig(BaseModel):
    """Agentic mode configuration (LLM-driven loop, coexisting with classic)."""

    max_tool_rounds: int = 10
    max_agentic_rounds: int = 20
    max_finalize_rejections: int = 3
    context_window: int = 65536
    output_buffer: int = 8192
    max_images_per_inspection: int = 0  # 0 = no limit; >0 injects VLM throttle instruction
    compaction: AgenticCompactionConfig = Field(default_factory=AgenticCompactionConfig)
    learning: AgenticLearningConfig = Field(default_factory=AgenticLearningConfig)


class LoopConfig(BaseModel):
    """Inner loop configuration."""

    engine: Literal["classic", "agentic"] = "classic"
    max_iterations: int = 7
    auto_accept_threshold: float = 8.0
    compaction_threshold_tokens: int = 20000
    keep_recent_iterations: int = 2
    step_mode: bool = False
    agentic: AgenticLoopConfig = Field(default_factory=AgenticLoopConfig)


class MemoryConfig(BaseModel):
    """Memory module configuration."""

    base_dir: str = "~/.drawagent/memory"
    auto_load: bool = True
    auto_save: bool = False


class AppConfig(BaseModel):
    """Top-level application configuration."""

    agent_a: AgentAConfig = Field(default_factory=AgentAConfig)
    agent_b: AgentBConfig = Field(default_factory=AgentBConfig)
    agent_c: AgentCConfig = Field(default_factory=AgentCConfig)
    loop: LoopConfig = Field(default_factory=LoopConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    output_dir: str = "./outputs"
