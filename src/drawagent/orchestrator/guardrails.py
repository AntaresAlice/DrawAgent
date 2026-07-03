"""Guardrails for the agentic loop — safety boundaries without flow control.

Analogous to opencode's maxSteps, compaction overflow checks, and question_rejection.
The guardrails do NOT dictate what phase to enter — they only enforce hard limits
and inject system messages when thresholds are crossed.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from drawagent.models.agentic_session import AgenticSession


class SessionGuardrails:
    """Safety limits for agentic loop execution.

    All methods return boolean: True = boundary reached, caller should act.
    None of these methods mutate session state — the caller decides how to react.
    """

    def __init__(self, agentic_config: dict):
        self.max_tool_rounds = agentic_config.get("max_tool_rounds", 10)
        self.max_agentic_rounds = agentic_config.get("max_agentic_rounds", 20)
        self.max_finalize_rejections = agentic_config.get("max_finalize_rejections", 3)
        self.context_window = agentic_config.get("context_window", 65536)
        self.output_buffer = agentic_config.get("output_buffer", 8192)
        self._guardrails_config = agentic_config.get("guardrails", {})

    # --- Tool round limit ---

    def check_tool_rounds(self, current_round: int) -> bool:
        return current_round >= self.max_tool_rounds

    # --- Outer round limit ---

    def check_agentic_rounds(self, current_round: int) -> bool:
        return current_round >= self.max_agentic_rounds

    # --- Finalize rejection deadlock prevention ---

    def check_finalize_rejections(self, session: "AgenticSession") -> bool:
        """True when consecutive finalize rejections exceed the threshold.

        Caller should inject a system message telling the LLM to fix specific
        failed inspections before attempting finalize again.
        """
        return session.finalize_rejection_count >= self.max_finalize_rejections

    # --- Token budget ---

    def check_token_budget(
        self,
        system_prompt: str,
        messages: list[dict],
        tools: list[dict],
    ) -> bool:
        """True when estimated token count exceeds safe threshold.

        Caller should trigger compaction before the next LLM call.
        """
        total = (
            self._estimate_tokens(system_prompt)
            + sum(self._estimate_tokens(self._msg_repr(m)) for m in messages)
            + sum(self._estimate_tokens(self._msg_repr(t)) for t in tools)
        )
        return total > self.context_window - self.output_buffer

    # --- Empty response limit ---

    def check_empty_responses(self, consecutive_empty: int) -> bool:
        threshold = self._guardrails_config.get("empty_response_threshold", 3)
        return consecutive_empty >= threshold

    # --- No image generated limit ---

    def check_no_image_generated(self, consecutive_no_image: int) -> bool:
        threshold = self._guardrails_config.get("no_image_threshold", 3)
        return consecutive_no_image >= threshold

    # --- Token estimation ---

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """Estimate token count, preferring tiktoken when available.

        Falls back to a conservative heuristic for Chinese text (1 char ≈ 0.5-1 tokens).
        """
        try:
            import tiktoken
            enc = tiktoken.get_encoding("cl100k_base")
            return len(enc.encode(text))
        except ImportError:
            # Conservative Chinese-aware fallback:
            # CJK characters ≈ 1-2 tokens each, ASCII ≈ 0.3 tokens each
            cjk = sum(1 for c in text if "\u4e00" <= c <= "\u9fff" or "\u3000" <= c <= "\u303f")
            ascii_count = sum(1 for c in text if ord(c) < 128)
            other = len(text) - cjk - ascii_count
            return int(cjk * 1.5 + ascii_count * 0.3 + other * 0.5)

    @staticmethod
    def _msg_repr(obj) -> str:
        if isinstance(obj, dict):
            return json.dumps(obj, ensure_ascii=False)
        return str(obj)
