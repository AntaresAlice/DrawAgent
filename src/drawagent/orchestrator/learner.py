"""Experience accumulation via LLM reflection (Phase 4 stub).

After each outer loop round, reflects on iteration results and records
concrete lessons in the session for future turns.

Full implementation deferred to Phase 4.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from drawagent.agents.agent_a import AgentA
    from drawagent.models.agentic_session import AgenticSession

logger = logging.getLogger("drawagent.learner")


class ExperienceLearner:
    """Generates structured lessons from iteration outcomes (Phase 4)."""

    def __init__(self, agent_a: "AgentA", config: dict):
        self._agent_a = agent_a

    async def reflect(self, session: "AgenticSession") -> None:
        """Phase 4 stub — no-op."""
        pass
