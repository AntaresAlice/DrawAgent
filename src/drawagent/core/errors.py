class DrawAgentError(Exception):
    """Base exception for all DrawAgent errors."""


class ConfigError(DrawAgentError):
    """Configuration-related errors."""


class ProviderError(DrawAgentError):
    """LLM provider errors (API failures, timeouts, etc.)."""

    def __init__(self, message: str, provider: str = "", status_code: int | None = None):
        super().__init__(message)
        self.provider = provider
        self.status_code = status_code


class ToolError(DrawAgentError):
    """Tool execution errors."""

    def __init__(self, message: str, tool_name: str = ""):
        super().__init__(message)
        self.tool_name = tool_name


class SessionError(DrawAgentError):
    """Session lifecycle errors (not found, invalid state, etc.)."""


class ImageGenerationError(DrawAgentError):
    """Image generation failures."""


class ValidationError(DrawAgentError):
    """Input/schema validation errors."""
