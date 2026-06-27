from __future__ import annotations

import base64
import json
from typing import AsyncIterator

import httpx

from .base import LLMMessage, LLMProvider, LLMStreamEvent, VisionProvider


class OpenAICompatibleProvider(LLMProvider, VisionProvider):
    """OpenAI-compatible API provider.

    Supports: OpenAI, Anthropic (via proxy), Qwen, DeepSeek, local vLLM/Ollama.

    Reference: opencode's openai-compatible provider + streaming protocol.
    """

    def __init__(self, api_base: str, api_key: str, model: str, timeout: float = 120.0):
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key
        self.model = model
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(timeout))

    async def chat_stream(
        self,
        messages: list[LLMMessage],
        tools: list[dict] | None = None,
        tool_choice: str | None = None,
        **kwargs: object,
    ) -> AsyncIterator[LLMStreamEvent]:
        body: dict = {
            "model": self.model,
            "messages": [self._format_message(m) for m in messages],
            "stream": True,
            "stream_options": {"include_usage": True},
            **{k: v for k, v in kwargs.items() if k not in ("temperature", "max_tokens")},
        }

        temperature = kwargs.get("temperature")
        if temperature is not None:
            body["temperature"] = temperature

        max_tokens = kwargs.get("max_tokens")
        if max_tokens is not None:
            body["max_tokens"] = max_tokens

        if tools:
            body["tools"] = tools
        if tool_choice:
            body["tool_choice"] = tool_choice

        accumulated: dict[str, dict] = {}
        finish_reason: str | None = None

        async with self._client.stream(
            "POST",
            f"{self.api_base}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json=body,
        ) as response:
            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str == "[DONE]":
                    break

                data = json.loads(data_str)
                choice = (data.get("choices") or [{}])[0]
                delta = choice.get("delta") or {}

                finish_reason = choice.get("finish_reason") or finish_reason

                if delta.get("content"):
                    yield LLMStreamEvent(
                        type="text_delta",
                        content=delta["content"],
                    )

                tool_calls = delta.get("tool_calls") or []
                for tc in tool_calls:
                    tc_id = tc.get("id") or ""
                    fn = tc.get("function") or {}

                    if tc_id not in accumulated:
                        accumulated[tc_id] = {"name": fn.get("name", ""), "arguments": ""}
                        yield LLMStreamEvent(
                            type="tool_call_start",
                            tool_name=fn.get("name"),
                            tool_call_id=tc_id,
                        )

                    args_delta = fn.get("arguments") or ""
                    if args_delta:
                        accumulated[tc_id]["arguments"] += args_delta
                        yield LLMStreamEvent(
                            type="tool_call_args",
                            content=args_delta,
                            tool_name=accumulated[tc_id]["name"],
                            tool_call_id=tc_id,
                        )

                if finish_reason:
                    usage = data.get("usage")
                    yield LLMStreamEvent(
                        type="step_finish",
                        finish_reason=finish_reason,
                        usage=usage,
                    )

    async def chat(
        self,
        messages: list[LLMMessage],
        tools: list[dict] | None = None,
        **kwargs: object,
    ) -> dict:
        body: dict = {
            "model": self.model,
            "messages": [self._format_message(m) for m in messages],
            **{k: v for k, v in kwargs.items() if k not in ("temperature", "max_tokens")},
        }

        temperature = kwargs.get("temperature")
        if temperature is not None:
            body["temperature"] = temperature

        max_tokens = kwargs.get("max_tokens")
        if max_tokens is not None:
            body["max_tokens"] = max_tokens

        if tools:
            body["tools"] = tools

        resp = await self._client.post(
            f"{self.api_base}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json=body,
        )
        return resp.json()["choices"][0]["message"]

    async def analyze_image(
        self,
        image_data: bytes,
        question: str,
        context: str | None = None,
        **kwargs: object,
    ) -> str:
        b64 = base64.b64encode(image_data).decode()

        content: list[dict] = [{"type": "text", "text": question}]
        if context:
            content.append({"type": "text", "text": context})

        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{b64}"},
        })

        resp = await self._client.post(
            f"{self.api_base}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model,
                "messages": [{"role": "user", "content": content}],
                "max_tokens": kwargs.get("max_tokens", 2048),
            },
        )
        return resp.json()["choices"][0]["message"]["content"]

    def _format_message(self, msg: LLMMessage) -> dict:
        formatted: dict = {"role": msg.role, "content": msg.content}
        if msg.tool_call_id is not None:
            formatted["tool_call_id"] = msg.tool_call_id
        if msg.name is not None:
            formatted["name"] = msg.name
        if msg.tool_calls is not None:
            formatted["tool_calls"] = msg.tool_calls
        return formatted

    async def close(self) -> None:
        await self._client.aclose()
