"""
Verbose logging for DrawAgent pipeline transparency.

When enabled (--verbose flag or DRAWAGENT_VERBOSE=1 env),
logs raw LLM requests, streaming chunks, assembled responses,
and full tool call arguments/results.

Usage:
    from drawagent.core.verbose_log import VerboseLog
    vlog = VerboseLog.get()
    vlog.llm_request(provider="deepseek", model="v4-flash", messages=[...], tools=[...])
    vlog.llm_chunk(provider="deepseek", index=3, chunk_data=...)
    vlog.llm_final(provider="deepseek", text="...", tool_calls=[...], finish_reason="stop")
    vlog.tool_call(name="generate_image", args={...})
    vlog.tool_result(name="generate_image", success=True, output="...", error=None)
    vlog.vision_request(model="qwen3.5:9b", image_path="/tmp/a.png", question="...")
    vlog.vision_response(model="qwen3.5:9b", observation="...")
    vlog.mcp_request(method="tools/call", params={...})
    vlog.mcp_response(method="tools/call", result={...})

Enable/disable:
    VerboseLog.enable()          # turn on
    VerboseLog.disable()         # turn off
    VerboseLog.set_enabled(True) # explicit set
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime

logger = logging.getLogger("drawagent.verbose")


class VerboseLog:
    """Global singleton for verbose pipeline logging."""

    _instance: VerboseLog | None = None

    @classmethod
    def get(cls) -> VerboseLog:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._enabled = os.environ.get("DRAWAGENT_VERBOSE", "").lower() in ("1", "true", "yes")
        self._stream = sys.stderr
        self._prefix = "  "
        self._chunk_counter: dict[str, int] = {}

    @classmethod
    def enable(cls) -> None:
        cls.get()._enabled = True

    @classmethod
    def disable(cls) -> None:
        cls.get()._enabled = False

    @classmethod
    def set_enabled(cls, value: bool) -> None:
        cls.get()._enabled = value

    @property
    def enabled(self) -> bool:
        return self._enabled

    def _write(self, text: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S.%f")[:12]
        for line in text.split("\n"):
            self._stream.write(f"[{ts}] {self._prefix}{line}\n")
        self._stream.flush()

    def _format_dict(self, obj, max_str: int = 500) -> str:
        """Pretty-print a dict-like object, truncating long values."""
        if isinstance(obj, str):
            if len(obj) > max_str:
                return obj[:max_str] + f"... ({len(obj)} chars)"
            return obj
        if isinstance(obj, (list, tuple)):
            if len(obj) > 10:
                return f"[{len(obj)} items]"
            inner = [self._format_dict(item, 80) for item in obj]
            import re
            joined = ", ".join(inner)
            if len(joined) > max_str:
                joined = joined[:max_str] + "..."
            return f"[{joined}]"
        if isinstance(obj, dict):
            if len(obj) > 20:
                return f"{{{len(obj)} keys}}"
            items = []
            for k, v in obj.items():
                val_str = self._format_dict(v, 100)
                items.append(f"{k}: {val_str}")
            joined = ", ".join(items)
            if len(joined) > max_str:
                joined = joined[:max_str] + "..."
            return f"{{{joined}}}"
        return str(obj)[:max_str]

    def _format_messages(self, messages: list) -> str:
        """Format a list of messages for display."""
        lines = []
        for i, msg in enumerate(messages):
            role = getattr(msg, "role", "?")
            content = getattr(msg, "content", "")
            if isinstance(content, list):
                # Multimodal content (e.g. vision messages)
                parts = []
                for item in content:
                    if isinstance(item, dict):
                        if item.get("type") == "image_url":
                            url = item.get("image_url", {}).get("url", "")
                            if url.startswith("data:"):
                                parts.append(f"<image base64, {len(url)} chars>")
                            else:
                                parts.append(f"<image url: {url[:60]}>")
                        elif item.get("type") == "text":
                            txt = item.get("text", "")
                            parts.append(txt[:200])
                content_str = " | ".join(parts) if parts else "[multimodal]"
            elif content is None:
                content_str = f"[tool_calls: {len(getattr(msg, 'tool_calls', []) or [])}]"
            else:
                content_str = str(content)[:300]
            tool_call_id = getattr(msg, "tool_call_id", None)
            tc_str = f" (tc_id={tool_call_id})" if tool_call_id else ""
            lines.append(f"    [{i}] {role}{tc_str}: {content_str}")
        return "\n".join(lines)

    # ── Generic ────────────────────────────────────────────────────────────────

    def log(self, tag: str, text: str) -> None:
        if not self._enabled:
            return
        self._write(f"[{tag}] {text}")

    # ── LLM Request / Response ────────────────────────────────────────────────

    def llm_request(
        self,
        provider: str,
        model: str,
        messages: list,
        tools: list | None = None,
        api_base: str = "",
    ):
        if not self._enabled:
            return
        self._chunk_counter[provider] = 0
        lines = [
            f"┌─ LLM REQUEST → [{provider}] {model}",
            f"│  API: {api_base}/chat/completions",
            f"│  Messages ({len(messages)}):",
        ]
        lines.append(self._format_messages(messages))
        if tools:
            tool_names = [t.get("function", {}).get("name", "?") for t in tools]
            lines.append(f"│  Tools: {tool_names}")
        lines.append("└─" + "─" * 50)
        self._write("\n".join(lines))

    def llm_chunk(self, provider: str, chunk_data: dict) -> None:
        if not self._enabled:
            return
        self._chunk_counter[provider] = self._chunk_counter.get(provider, 0) + 1
        n = self._chunk_counter[provider]
        # Show first 5 chunks, then every 10th
        if n <= 5 or n % 10 == 0:
            self._write(f"  [chunk #{n}] {self._format_dict(chunk_data, 400)}")

    def llm_final(
        self,
        provider: str,
        text: str = "",
        tool_calls: list | None = None,
        finish_reason: str = "",
    ):
        if not self._enabled:
            return
        lines = [
            f"┌─ LLM RESPONSE ← [{provider}] finish={finish_reason}",
        ]
        if text:
            lines.append(f"│  Text ({len(text)} chars):")
            lines.append(f"│    {text[:500]}")
        if tool_calls:
            lines.append(f"│  Tool Calls ({len(tool_calls)}):")
            for tc in tool_calls:
                fn_name = tc.get("function", {}).get("name", "?")
                fn_args = tc.get("function", {}).get("arguments", "")
                lines.append(f"│    {fn_name}({fn_args[:300]}...)")
        lines.append("└─" + "─" * 50)
        self._write("\n".join(lines))

    # ── Tool Call / Result ───────────────────────────────────────────────────

    def tool_call(self, name: str, args: dict) -> None:
        if not self._enabled:
            return
        self._write(f"  [TOOL CALL] {name}({json.dumps(args, ensure_ascii=False)[:400]})")

    def tool_result(self, name: str, success: bool, output: str = "", error: str | None = None) -> None:
        if not self._enabled:
            return
        if error:
            self._write(f"  [TOOL RESULT] {name} ERROR: {error[:500]}")
        else:
            self._write(f"  [TOOL RESULT] {name} OK: {output[:500]}")

    # ── Vision (Agent C) ─────────────────────────────────────────────────────

    def vision_request(self, model: str, image_path: str, question: str, context: str | None = None):
        if not self._enabled:
            return
        lines = [
            f"  [VISION REQUEST → {model}]",
            f"    Image: {image_path}",
            f"    Question: {question[:300]}",
        ]
        if context:
            lines.append(f"    Context: {context[:200]}")
        self._write("\n".join(lines))

    def vision_response(self, model: str, observation: str):
        if not self._enabled:
            return
        self._write(f"  [VISION RESPONSE ← {model}] ({len(observation)} chars):\n    {observation[:600]}")

    # ── MCP ──────────────────────────────────────────────────────────────────

    def mcp_request(self, method: str, params: dict) -> None:
        if not self._enabled:
            return
        self._write(f"  [MCP →] {method} {self._format_dict(params, 400)}")

    def mcp_response(self, method: str, result: dict | None = None, error: str | None = None) -> None:
        if not self._enabled:
            return
        if error:
            self._write(f"  [MCP ←] {method} ERROR: {error[:300]}")
        elif result:
            # Deep-copy to avoid mutating the caller's result dict.
            # Shallow copy (dict(result)) shares content list items
            # with the original; modifying item["data"] there corrupts
            # the actual base64 data the caller needs to decode.
            import copy
            short = copy.deepcopy(result)
            if "content" in short and isinstance(short["content"], list):
                for item in short["content"]:
                    if isinstance(item, dict) and item.get("type") == "image":
                        data_len = len(item.get("data", ""))
                        item["data"] = f"<base64, {data_len} bytes>"
            self._write(f"  [MCP ←] {method} {self._format_dict(short, 500)}")


# ── Convenience module-level functions ───────────────────────────────────────

def vlog() -> VerboseLog:
    return VerboseLog.get()
