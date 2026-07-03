"""LLM-driven context compaction for agentic mode.

Replaces classic rule-based CompactedHistory with LLM-generated summaries.
Uses the main Agent A model (no separate compaction model).

Token estimation uses tiktoken when available, falling back to a
Chinese-aware heuristic (CJK chars ≈ 1.5 tokens, ASCII ≈ 0.3 tokens).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from drawagent.agents.agent_a import AgentA
    from drawagent.models.agentic_session import AgenticCompaction, AgenticSession

logger = logging.getLogger("drawagent.compactor")

_SUMMARY_PROMPT = (
    "Summarize the conversation below while preserving these key elements:\n"
    "1. Original user request (exact wording)\n"
    "2. Key decisions made (prompt changes, parameter choices, tool calls)\n"
    "3. What was tried + what worked + what failed (cite specific outcomes)\n"
    "4. Any explicit user feedback\n"
    "5. Current state (what's left to do, what images exist)\n\n"
    "Keep the summary concise (max 500 tokens). Use bullet points.\n\n"
    "<conversation>\n"
    "{conversation}\n"
    "</conversation>"
)


class ContextCompactor:
    """Compresses old conversation turns via LLM summarization.

    Triggered when token budget check detects potential overflow.
    Uses the main Agent A model for summarization — no secondary model config needed.
    """

    def __init__(self, agent_a: "AgentA", config: dict):
        self._agent_a = agent_a
        agentic_cfg = config.get("agentic", {})
        compaction_cfg = agentic_cfg.get("compaction", {})
        self._keep_tokens = compaction_cfg.get("keep_tokens", 8000)

    async def compact_if_needed(
        self,
        session: "AgenticSession",
        system_prompt: str,
        messages: list[dict],
        tools: list[dict],
    ) -> bool:
        """Check token budget. If compacted, remove old turns + store Compaction.

        Returns True if compaction was performed (caller should rebuild context).
        """
        if len(session.turns) < 3:
            return False  # Not enough turns to compact meaningfully

        # Find split point: keep N turns worth of tokens, compact the rest
        split_at = self._find_split_point(session.turns)
        if split_at <= 0:
            return False

        old_turns = session.turns[:split_at]
        recent_turns = session.turns[split_at:]

        # Get previous summary for context (if it exists)
        prev_summary = ""
        if session.compactions:
            prev_summary = session.compactions[-1].summary

        # Build conversation text for the compactor
        parts = []
        if prev_summary:
            parts.append(f"<previous-summary>{prev_summary}</previous-summary>")
        for turn in old_turns:
            parts.append(self._format_turn(turn))

        conversation = "\n\n".join(parts)
        prompt = _SUMMARY_PROMPT.format(conversation=conversation)

        try:
            response = await self._agent_a.provider.chat([
                {"role": "user", "content": prompt},
            ])
            content = response.get("content", "") or ""
            summary = content if isinstance(content, str) else str(content)

            if not summary or len(summary) < 20:
                logger.warning("Compaction produced empty/short summary, skipping")
                return False

            # Store compaction checkpoint
            comp = AgenticCompaction(
                seq=split_at,
                summary=summary,
                compacted_turn_count=len(old_turns),
                created_at=datetime.now(),
            )
            session.compactions.append(comp)

            # Replace turns: keep only recent ones
            session.turns = recent_turns

            logger.info("Compacted %d turns → summary of %d chars, kept %d turns",
                        comp.compacted_turn_count, len(summary), len(recent_turns))
            return True

        except Exception as exc:
            logger.debug("Compaction LLM call failed: %s", exc)
            return False

    def _find_split_point(self, turns: list) -> int:
        """Walk backward through turns, accumulate token estimates.
        Return the index where accumulated tokens exceed keep_tokens.
        """
        accumulated = 0
        for i, turn in enumerate(reversed(turns)):
            turn_tokens = self._estimate_turn_tokens(turn)
            accumulated += turn_tokens
            if accumulated > self._keep_tokens:
                # Split point: index from start
                return len(turns) - i - 1
        return 0  # Not enough tokens to need compaction

    @staticmethod
    def _format_turn(turn) -> str:
        parts = [f"<turn>"]
        if turn.user_message:
            parts.append(f"  <user>{turn.user_message.text[:500]}</user>")
        if turn.assistant_text:
            parts.append(f"  <assistant>{turn.assistant_text[:1000]}</assistant>")
        for tc in turn.tool_calls:
            if tc.status == "completed":
                result_str = json.dumps(tc.result, ensure_ascii=False)[:300]
                parts.append(f"  <tool name='{tc.tool_name}'>{result_str}</tool>")
            elif tc.error:
                parts.append(f"  <tool name='{tc.tool_name}' error='{tc.error[:200]}'/>")
        parts.append("</turn>")
        return "\n".join(parts)

    @staticmethod
    def _estimate_turn_tokens(turn) -> int:
        text = ""
        if turn.user_message:
            text += turn.user_message.text
        if turn.assistant_text:
            text += turn.assistant_text
        for tc in turn.tool_calls:
            if tc.result:
                text += json.dumps(tc.result, ensure_ascii=False)
        return _estimate_tokens(text)


def _estimate_tokens(text: str) -> int:
    """Estimate token count with Chinese awareness."""
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except ImportError:
        cjk = sum(1 for c in text if "\u4e00" <= c <= "\u9fff" or "\u3000" <= c <= "\u303f")
        ascii_count = sum(1 for c in text if ord(c) < 128)
        other = len(text) - cjk - ascii_count
        return int(cjk * 1.5 + ascii_count * 0.3 + other * 0.5)
