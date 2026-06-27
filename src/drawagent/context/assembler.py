from __future__ import annotations

from pathlib import Path

from drawagent.agents.prompts import (
    BASE_SYSTEM_PROMPT,
    MEMORY_USAGE_GUIDE,
)
from drawagent.config.schema import AgentBConfig
from drawagent.context.compaction import CompactedHistory
from drawagent.core.types import Iteration, Session
from drawagent.providers.base import LLMMessage


class ContextAssembler:
    """Assembles LLM context from session state, memory, and history.

    Reference: opencode's Context Epoch model — five-layer assembly:
      1. SystemContext (Agent A system prompt + model info)
      2. MemoryContext (loaded memory files)
      3. CompactedHistory (compressed old iterations)
      4. RecentIterations (last N full iterations)
      5. CurrentMessages (current turn messages)
    """

    def __init__(self, agent_b_config: AgentBConfig):
        self.agent_b_config = agent_b_config

    async def assemble(
        self,
        session: Session,
        compacted: CompactedHistory | None,
        current_messages: list[LLMMessage],
    ) -> list[LLMMessage]:
        messages: list[LLMMessage] = []
        messages.append(LLMMessage(
            role="system",
            content=self._build_system_prompt(session),
        ))

        if session.loaded_memories:
            for memory_ref in session.loaded_memories:
                messages.append(LLMMessage(
                    role="system",
                    content=f"<memory source='{memory_ref}'>\n[Memory loaded]\n</memory>",
                ))

        if compacted:
            messages.append(LLMMessage(
                role="system",
                content=compacted.to_context_string(),
            ))

        recent = session.iterations[-session.max_iterations:]
        kept_recent = 2
        for it in recent[-kept_recent:]:
            messages.append(LLMMessage(
                role="system",
                content=self._format_iteration(it),
            ))

        messages.extend(current_messages)
        return messages

    def assemble_current_turn(
        self,
        session: Session,
        instruction: str,
    ) -> list[LLMMessage]:
        """Assemble a simple context for a single-turn Agent A call."""
        messages: list[LLMMessage] = []
        messages.append(LLMMessage(
            role="system",
            content=self._build_system_prompt(session),
        ))
        messages.append(LLMMessage(
            role="user",
            content=instruction,
        ))
        return messages

    def _build_system_prompt(self, session: Session) -> str:
        parts = [BASE_SYSTEM_PROMPT]

        parts.append(f"\n## Current Image Model: {self.agent_b_config.model}")
        parts.append(f"\n## Image Parameters: {self.agent_b_config.default_params}")

        guide = f"""
## Prompt Format Guide ({self.agent_b_config.prompt_format})
- Model: {self.agent_b_config.model}
- Default size: {self.agent_b_config.default_params.get('width', 1024)}x{self.agent_b_config.default_params.get('height', 1024)}
- Default steps: {self.agent_b_config.default_params.get('steps', 8)}
- Guidance scale: {self.agent_b_config.default_params.get('guidance', 3.5)}
"""
        parts.append(guide)
        parts.append(MEMORY_USAGE_GUIDE)

        return "\n".join(parts)

    def _format_iteration(self, it: Iteration) -> str:
        parts = [f"<iteration number='{it.number}'>"]
        parts.append(f"  <prompt>{it.prompt}</prompt>")

        if it.images:
            parts.append("  <images>")
            for img in it.images:
                parts.append(f"    <image path='{img.path}' seed='{img.seed}' "
                             f"score='{img.quality_score}'/>")
            parts.append("  </images>")

        if it.inspections:
            parts.append("  <inspections>")
            for insp in it.inspections:
                parts.append(f"    <task name='{insp.task_name}' passed='{insp.passed}'>")
                parts.append(f"      {insp.observation[:200]}")
                parts.append(f"    </task>")
            parts.append("  </inspections>")

        if it.decision:
            parts.append(f"  <decision passed='{it.decision.passed}' "
                         f"confidence='{it.decision.confidence}'>")
            parts.append(f"    {it.decision.reasoning[:200]}")
            parts.append(f"  </decision>")

        parts.append("</iteration>")
        return "\n".join(parts)
