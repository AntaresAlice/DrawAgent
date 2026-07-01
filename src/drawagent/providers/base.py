from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncIterator, Literal


@dataclass
class LLMMessage:
    """Standardized LLM message format."""

    role: Literal["system", "user", "assistant", "tool"]
    content: str | list[dict]
    tool_call_id: str | None = None
    name: str | None = None
    tool_calls: list[dict] | None = None


@dataclass
class LLMStreamEvent:
    """Streaming event from LLM provider.

    Reference: opencode's LLMEvent simplified.
    """

    type: Literal["text_delta", "tool_call_start", "tool_call_args", "step_finish", "error"]
    content: str = ""
    tool_name: str | None = None
    tool_call_id: str | None = None
    finish_reason: str | None = None
    usage: dict | None = None


class LLMProvider(ABC):
    """Abstract LLM provider interface.

    Reference: opencode's Provider + Protocol pattern.
    """

    @abstractmethod
    async def chat_stream(
        self,
        messages: list[LLMMessage],
        tools: list[dict] | None = None,
        tool_choice: str | None = None,
        **kwargs: object,
    ) -> AsyncIterator[LLMStreamEvent]:
        ...

    @abstractmethod
    async def chat(
        self,
        messages: list[LLMMessage],
        tools: list[dict] | None = None,
        **kwargs: object,
    ) -> dict:
        ...


class VisionProvider(ABC):
    """Abstract vision/multimodal provider interface."""

    @abstractmethod
    async def analyze_image(
        self,
        image_data: bytes,
        question: str,
        context: str | None = None,
        **kwargs: object,
    ) -> str:
        ...

    @abstractmethod
    async def compare_images(
        self,
        image_data_1: bytes,
        image_data_2: bytes,
        questions: str,
        context: str | None = None,
        **kwargs: object,
    ) -> str:
        """Compare two images using the vision model.

        Sends both images in a single API call with comparison questions.
        The model identifies images by their order (first = Image 1, second = Image 2).

        NOTE: Images are resized internally to fit context window limits.
        This is a temporary workaround for small-context vision models.
        """
        ...
