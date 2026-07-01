from __future__ import annotations

import base64
import json
from typing import AsyncIterator

import httpx

from .base import LLMMessage, LLMProvider, LLMStreamEvent, VisionProvider
from drawagent.core.errors import ProviderError
from drawagent.core.verbose_log import VerboseLog


class OpenAICompatibleProvider(LLMProvider, VisionProvider):
    """OpenAI-compatible API provider.

    Supports: OpenAI, Anthropic (via proxy), Qwen, DeepSeek, local vLLM/Ollama.
    """

    def __init__(self, api_base: str, api_key: str, model: str, timeout: float = 120.0):
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key
        self.model = model
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(self._timeout))
        return self._client

    async def __aenter__(self):
        await self._ensure_client()
        return self

    async def __aexit__(self, *args):
        await self.close()

    def _handle_error(self, exc: httpx.HTTPError, context: str = "") -> ProviderError:
        msg = str(exc)
        provider_name = "Agent"
        if isinstance(exc, httpx.HTTPStatusError):
            code = exc.response.status_code
            if code == 401:
                msg = f"API Key 无效或未授权 (HTTP 401) — 请检查 {context} 的 API Key 是否正确"
            elif code == 403:
                msg = f"API 访问被拒绝 (HTTP 403) — 请检查 {context} 的 API Key 权限"
            elif code == 404:
                msg = f"API 端点未找到 (HTTP 404) — 请检查 {context} 的 API Base URL: {self.api_base}"
            elif code >= 500:
                msg = f"API 服务器错误 (HTTP {code}) — 请稍后重试或检查 {context} 的 API Base URL"
            else:
                msg = f"API 请求失败 (HTTP {code}): {exc.response.text[:300]}"
        elif isinstance(exc, httpx.ConnectError):
            msg = f"无法连接到 API 服务器 — 请检查 {context} 的 API Base URL 是否可达: {self.api_base}"
        elif isinstance(exc, httpx.TimeoutException):
            msg = f"API 请求超时 — {context} 的 API Base URL 响应过慢: {self.api_base}"
        return ProviderError(msg, provider=context, status_code=getattr(getattr(exc, 'response', None), 'status_code', None))

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

        vlog = VerboseLog.get()
        vlog.llm_request(self.model, self.model, messages, tools, self.api_base)

        accumulated: dict[str, dict] = {}
        finish_reason: str | None = None

        client = await self._ensure_client()
        try:
            async with client.stream(
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
                    vlog.llm_chunk(self.model, data)
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
                        tc_idx = tc.get("index", 0)
                        fn = tc.get("function") or {}

                        # Use index-based key for dedup (OpenAI/DSS: id only in first chunk)
                        if tc_idx not in accumulated:
                            tc_id = tc.get("id") or ""
                            accumulated[tc_idx] = {
                                "name": fn.get("name", ""),
                                "arguments": "",
                                "id": tc_id,
                            }
                            yield LLMStreamEvent(
                                type="tool_call_start",
                                tool_name=fn.get("name"),
                                tool_call_id=tc_id,
                            )

                        args_delta = fn.get("arguments") or ""
                        if args_delta:
                            entry = accumulated[tc_idx]
                            entry["arguments"] += args_delta
                            yield LLMStreamEvent(
                                type="tool_call_args",
                                content=args_delta,
                                tool_name=entry["name"],
                                tool_call_id=entry["id"],
                            )

                    if finish_reason:
                        usage = data.get("usage")
                        yield LLMStreamEvent(
                            type="step_finish",
                            finish_reason=finish_reason,
                            usage=usage,
                        )
                # Log final assembled result
                final_tool_calls = []
                for tc_idx, entry in sorted(accumulated.items()):
                    if entry.get("name"):
                        final_tool_calls.append({
                            "id": entry.get("id", ""),
                            "type": "function",
                            "function": {
                                "name": entry["name"],
                                "arguments": entry.get("arguments", ""),
                            },
                        })
                vlog.llm_final(
                    provider=self.model,
                    text="",
                    tool_calls=final_tool_calls,
                    finish_reason=finish_reason or "stop",
                )
        except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError) as e:
            raise self._handle_error(e, f"{self.model}") from e

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

        client = await self._ensure_client()
        try:
            resp = await client.post(
                f"{self.api_base}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=body,
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]
        except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError) as e:
            raise self._handle_error(e, f"{self.model}") from e

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

        client = await self._ensure_client()
        try:
            resp = await client.post(
                f"{self.api_base}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": content}],
                    "max_tokens": kwargs.get("max_tokens", 2048),
                },
            )
            resp.raise_for_status()
            observation = resp.json()["choices"][0]["message"]["content"]
            VerboseLog.get().vision_response(self.model, observation)
            return observation
        except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError) as e:
            raise self._handle_error(e, f"{self.model}") from e

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
        if self._client is not None:
            await self._client.aclose()
            self._client = None
