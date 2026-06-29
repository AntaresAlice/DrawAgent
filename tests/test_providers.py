"""Tests for provider creation, lazy loading, error handling, and inspect tool."""

import json
import os
from pathlib import Path

import httpx
import pytest

from drawagent.config.schema import AgentAConfig, AgentBConfig, AgentCConfig, AppConfig
from drawagent.core.errors import ConfigError, ImageGenerationError, ProviderError
from drawagent.core.events import EventBus, DrawEvent
from drawagent.core.types import Session
from drawagent.orchestrator.interrupt import InterruptHandler
from drawagent.orchestrator.session import SessionManager
from drawagent.providers.factory import ProviderFactory
from drawagent.providers.openai_compat import OpenAICompatibleProvider
from drawagent.tools.base import ToolRegistry, ToolContext
from drawagent.tools.generate_image import GenerateImageTool
from drawagent.tools.inspect_image import InspectImageTool


class TestProviderFactory:
    """Test that ProviderFactory validates API keys correctly."""

    def test_create_agent_a_missing_key_raises(self):
        cfg = AgentAConfig(api_key=None)
        if "OPENAI_API_KEY" in os.environ:
            saved = os.environ.pop("OPENAI_API_KEY")
            try:
                with pytest.raises(ConfigError, match="API key"):
                    ProviderFactory.create_agent_a(cfg)
            finally:
                os.environ["OPENAI_API_KEY"] = saved
        else:
            with pytest.raises(ConfigError, match="API key"):
                ProviderFactory.create_agent_a(cfg)

    def test_create_agent_a_with_key_succeeds(self):
        cfg = AgentAConfig(api_key="sk-test", api_base="https://test.local/v1")
        provider = ProviderFactory.create_agent_a(cfg)
        assert isinstance(provider, OpenAICompatibleProvider)
        assert provider.api_key == "sk-test"
        assert provider.model == "gpt-4o"

    def test_create_agent_c_missing_key_raises(self):
        cfg = AgentCConfig(api_key=None)
        if "OPENAI_API_KEY" in os.environ:
            saved = os.environ.pop("OPENAI_API_KEY")
            try:
                with pytest.raises(ConfigError, match="API key"):
                    ProviderFactory.create_agent_c(cfg)
            finally:
                os.environ["OPENAI_API_KEY"] = saved
        else:
            with pytest.raises(ConfigError, match="API key"):
                ProviderFactory.create_agent_c(cfg)

    def test_create_agent_c_with_key_succeeds(self):
        cfg = AgentCConfig(api_key="sk-test", api_base="https://test.local/v1")
        provider = ProviderFactory.create_agent_c(cfg)
        assert isinstance(provider, OpenAICompatibleProvider)
        assert provider.api_key == "sk-test"
        assert provider.model == "gpt-4o"

    def test_agent_c_default_config_has_all_fields(self):
        cfg = AgentCConfig()
        assert cfg.provider == "openai"
        assert cfg.model == "gpt-4o"
        assert cfg.api_base == "https://api.openai.com/v1"
        assert cfg.api_key is None
        assert cfg.temperature == 0.3
        assert cfg.max_tokens == 2048

    def test_agent_c_full_config(self):
        cfg = AgentCConfig(
            provider="local",
            model="gpt-4o-mini",
            api_base="http://localhost:11434/v1",
            api_key="ollama",
            temperature=0.1,
            max_tokens=1024,
        )
        assert cfg.api_base == "http://localhost:11434/v1"
        assert cfg.api_key == "ollama"
        assert cfg.temperature == 0.1

    def test_agent_a_config_does_not_leak_into_agent_c(self):
        cfg_a = AgentAConfig(api_key="sk-a", api_base="https://a.com/v1", model="gpt-4o")
        cfg_c = AgentCConfig(api_key="sk-c", api_base="https://c.com/v1", model="gpt-4o-mini")
        assert cfg_a.api_key != cfg_c.api_key
        assert cfg_a.api_base != cfg_c.api_base
        assert cfg_a.model != cfg_c.model


class TestOpenAICompatErrorHandling:
    """Test that OpenAI provider converts httpx errors to user-friendly messages."""

    def test_handle_401_error(self):
        provider = OpenAICompatibleProvider(
            api_base="https://api.example.com/v1",
            api_key="bad-key",
            model="test-model",
        )
        exc = httpx.HTTPStatusError(
            "401 Unauthorized",
            request=MagicMock(),
            response=MagicMock(status_code=401, text="Unauthorized"),
        )
        err = provider._handle_error(exc, "test-model")
        assert "API Key" in str(err)
        assert "无效" in str(err) or "401" in str(err)

    def test_handle_connect_error(self):
        provider = OpenAICompatibleProvider(
            api_base="http://nonexistent.local:9999/v1",
            api_key="sk-test",
            model="test-model",
        )
        exc = httpx.ConnectError("Connection refused")
        err = provider._handle_error(exc, "test-model")
        assert "无法连接" in str(err) or "connect" in str(err).lower()

    def test_handle_timeout_error(self):
        provider = OpenAICompatibleProvider(
            api_base="https://slow.api/v1",
            api_key="sk-test",
            model="test-model",
        )
        exc = httpx.TimeoutException("Request timed out")
        err = provider._handle_error(exc, "test-model")
        assert "超时" in str(err) or "timeout" in str(err).lower()

    def test_provider_error_has_status_code(self):
        e = ProviderError("test", provider="test-p", status_code=429)
        assert e.status_code == 429
        assert e.provider == "test-p"


class TestGenerateImageToolErrorHandling:
    """Test that generate_image tool provides helpful network error messages."""

    @pytest.mark.asyncio
    async def test_http_connection_refused(self, tmp_path):
        cfg = AgentBConfig(
            type="http",
            api_base="http://127.0.0.1:19999",
            endpoint="/api/generate",
        )
        tool = GenerateImageTool(config=cfg, output_dir=str(tmp_path))
        try:
            result = await tool.execute(
                {"prompt": "a cat", "num_images": 1, "seed": 42},
                ToolContext(session_id="test", agent="A"),
            )
            assert not result.success
            assert "error" in result.error or result.error
        finally:
            await tool.close()

    @pytest.mark.asyncio
    async def test_mcp_missing_command(self, tmp_path):
        cfg = AgentBConfig(
            type="mcp",
            mcp_command=None,
            mcp_url=None,
        )
        tool = GenerateImageTool(config=cfg, output_dir=str(tmp_path))
        try:
            with pytest.raises(ImageGenerationError, match="MCP"):
                await tool._ensure_mcp_connected()
        finally:
            await tool.close()


class TestInspectImageTool:
    """Test that inspect_image tool handles lazy provider initialization."""

    def test_accepts_none_provider(self):
        tool = InspectImageTool(vision_provider=None)
        assert tool.provider is None

    def test_set_provider_after_init(self):
        provider = OpenAICompatibleProvider(
            api_base="https://test.local/v1",
            api_key="sk-test",
            model="test-vision",
        )
        tool = InspectImageTool(vision_provider=None)
        tool.provider = provider
        assert tool.provider is not None
        assert tool.provider.api_key == "sk-test"

    @pytest.mark.asyncio
    async def test_execute_without_provider_returns_error(self, tmp_path):
        tool = InspectImageTool(vision_provider=None)
        img_path = tmp_path / "test.png"
        img_path.write_bytes(b"fake-png-data")

        result = await tool.execute(
            {"image_path": str(img_path), "task_description": "check quality"},
            ToolContext(session_id="test", agent="A"),
        )
        assert not result.success
        assert "not configured" in result.error.lower()


class TestServerRunnerLazyProviders:
    """Test that ServerRunner can be created without providers and creates them on demand."""

    def test_runner_init_without_providers(self, tmp_path):
        from drawagent.orchestrator.server_runner import ServerRunner

        cfg = AppConfig(
            agent_a=AgentAConfig(api_key="sk-test"),
            agent_c=AgentCConfig(api_key="sk-test"),
        )
        registry = ToolRegistry()
        registry.register(InspectImageTool(vision_provider=None))

        runner = ServerRunner(
            config=cfg,
            tool_registry=registry,
            session_manager=SessionManager(),
            interrupt_handler=InterruptHandler(),
            event_bus=EventBus(),
            output_dir=str(tmp_path),
        )
        assert runner._provider_a is None
        assert runner._provider_c is None

    @pytest.mark.asyncio
    async def test_runner_creates_providers_lazily(self, tmp_path):
        from drawagent.orchestrator.server_runner import ServerRunner

        cfg = AppConfig(
            agent_a=AgentAConfig(api_key="sk-test"),
            agent_c=AgentCConfig(api_key="sk-test"),
        )
        registry = ToolRegistry()
        inspect_tool = InspectImageTool(vision_provider=None)
        registry.register(inspect_tool)

        runner = ServerRunner(
            config=cfg,
            tool_registry=registry,
            session_manager=SessionManager(),
            interrupt_handler=InterruptHandler(),
            event_bus=EventBus(),
            output_dir=str(tmp_path),
        )

        provider_a, provider_c = await runner._get_or_create_providers()
        assert provider_a is not None
        assert provider_c is not None
        assert inspect_tool.provider is not None

    @pytest.mark.asyncio
    async def test_lazy_init_failure_emits_error(self, tmp_path):
        from drawagent.orchestrator.server_runner import ServerRunner

        cfg = AppConfig(
            agent_a=AgentAConfig(api_key=None),
            agent_c=AgentCConfig(api_key=None),
        )
        registry = ToolRegistry()
        event_bus = EventBus()

        errors = []
        async def capture_error(evt, data):
            errors.append(data)

        event_bus.on("error", capture_error)

        runner = ServerRunner(
            config=cfg,
            tool_registry=registry,
            session_manager=SessionManager(),
            interrupt_handler=InterruptHandler(),
            event_bus=event_bus,
            output_dir=str(tmp_path),
        )

        # Remove env var to force failure
        saved = os.environ.pop("OPENAI_API_KEY", None)
        try:
            session = Session(id="err-test", user_request="test")
            await runner._execute_loop(session, "test")
            assert len(errors) > 0
        finally:
            if saved:
                os.environ["OPENAI_API_KEY"] = saved


# Minimal mock helper
class MagicMock:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)
