from __future__ import annotations

from typing import Optional

from drawagent.core.errors import ConfigError
from drawagent.config.schema import AgentAConfig, AgentBConfig, AgentCConfig, AppConfig

from .base import LLMProvider, VisionProvider
from .openai_compat import OpenAICompatibleProvider


class ProviderFactory:
    """Create provider instances from configuration.

    Reference: opencode's provider resolution from ConfigProvider.
    """

    @staticmethod
    def create_agent_a(config: AgentAConfig) -> LLMProvider:
        api_key = config.api_key or ProviderFactory._require_env("OPENAI_API_KEY")
        if not api_key:
            raise ConfigError(
                "Agent A requires an API key. Set it in config or OPENAI_API_KEY env var."
            )
        return OpenAICompatibleProvider(
            api_base=config.api_base,
            api_key=api_key,
            model=config.model,
        )

    @staticmethod
    def create_agent_c(config: AgentCConfig) -> VisionProvider:
        api_key = config.api_key or ProviderFactory._require_env("OPENAI_API_KEY")
        if not api_key:
            raise ConfigError(
                "Agent C requires an API key. Set it in config or OPENAI_API_KEY env var."
            )
        return OpenAICompatibleProvider(
            api_base=config.api_base,
            api_key=api_key,
            model=config.model,
        )

    @classmethod
    def create_all(cls, config: AppConfig) -> tuple[LLMProvider, VisionProvider]:
        """Create Agent A and Agent C providers from app config."""
        return (
            cls.create_agent_a(config.agent_a),
            cls.create_agent_c(config.agent_c),
        )

    @staticmethod
    def _require_env(name: str) -> Optional[str]:
        import os
        return os.environ.get(name)
