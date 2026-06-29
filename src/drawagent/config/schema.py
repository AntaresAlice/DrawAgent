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

    default_params: dict = Field(default_factory=lambda: {
        "width": 1024,
        "height": 1024,
        "steps": 8,
        "guidance": 3.5,
        "seed": -1,
    })
    prompt_format: str = "zimage"


class AgentCConfig(BaseModel):
    """Agent C (vision inspector) configuration."""

    provider: str = "openai"
    model: str = "gpt-4o"
    api_base: str = "https://api.openai.com/v1"
    api_key: Optional[str] = None
    temperature: float = 0.3
    max_tokens: int = 2048


class LoopConfig(BaseModel):
    """Inner loop configuration."""

    max_iterations: int = 7
    auto_accept_threshold: float = 8.0
    compaction_threshold_tokens: int = 20000
    keep_recent_iterations: int = 2


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
