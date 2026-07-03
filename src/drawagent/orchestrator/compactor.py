"""LLM-driven context compaction for agentic mode (Phase 4 stub).

Replaces classic rule-based CompactedHistory with LLM-generated summaries.
Uses the main Agent A model (no separate compaction model).

Full implementation deferred to Phase 4.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from drawagent.agents.agent_a import AgentA
    from drawagent.models.agentic_session import AgenticSession

logger = logging.getLogger("drawagent.compactor")


class ContextCompactor:
    """Compresses old conversation turns via LLM summarization (Phase 4)."""

    def __init__(self, agent_a: "AgentA", config: dict):
        self._agent_a = agent_a

    async def compact_if_needed(
        self,
        session: "AgenticSession",
        system_prompt: str,
        messages: list[dict],
        tools: list[dict],
    ) -> bool:
        """Check token budget and compact if needed. Phase 4 stub — always returns False."""
        return False
