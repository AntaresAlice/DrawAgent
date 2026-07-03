"""Experience accumulation via LLM reflection.

After each outer loop round, reflects on iteration results and records
concrete lessons in the session for future turns.

Uses the main Agent A model — no separate reflection model needed.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from drawagent.agents.agent_a import AgentA
    from drawagent.models.agentic_session import AgenticSession

logger = logging.getLogger("drawagent.learner")

_REFLECTION_PROMPT = (
    "Based on the conversation so far, identify concrete lessons for improving "
    "future image generation. Focus on:\n"
    "1. What went wrong? Be specific — cite actual tool results or LLM decisions.\n"
    "2. What strategy worked well?\n"
    "3. What should be done differently next time?\n\n"
    "Output each lesson on its own line in this EXACT format:\n"
    "LEARNED: <category> | <observation> | <strategy>\n\n"
    "Example:\n"
    "LEARNED: skin_texture | hands look plastic in portrait close-ups | "
    "Add 'visible pores, natural skin texture' to prompt, use side-lighting\n"
    "LEARNED: prompt_style | vague adjectives produce generic results | "
    "Use specific material nouns like silk, lace, denim instead of smooth, nice\n\n"
    "Output ONLY lessons in the format above, nothing else.\n\n"
    "Conversation summary:\n"
    "{turns_summary}"
)


class ExperienceLearner:
    """Generates structured lessons from iteration outcomes using Agent A."""

    def __init__(self, agent_a: "AgentA", config: dict):
        self._agent_a = agent_a
        agentic_cfg = config.get("agentic", {})
        learning_cfg = agentic_cfg.get("learning", {})
        self._enabled = learning_cfg.get("enabled", True)
        self._max_lessons = learning_cfg.get("max_lessons", 10)
        self._event_bus: object | None = None

    def set_event_bus(self, event_bus) -> None:
        self._event_bus = event_bus

    async def reflect(self, session: "AgenticSession") -> None:
        if not self._enabled:
            return
        if not session.turns:
            return

        summary = self._summarize_turns(session)
        prompt = _REFLECTION_PROMPT.format(turns_summary=summary)

        try:
            response = await self._agent_a.provider.chat([
                {"role": "user", "content": prompt},
            ])
            content = response.get("content", "") or ""
            text = content if isinstance(content, str) else str(content)

            new_lessons = self._parse_lessons(text)
            for lesson in new_lessons:
                if lesson not in session.learned_lessons:
                    session.learned_lessons.append(lesson)

            # Trim to keep only recent lessons
            if len(session.learned_lessons) > self._max_lessons:
                session.learned_lessons = session.learned_lessons[-self._max_lessons:]

            if new_lessons:
                logger.info("Session %s learned %d new lessons (total: %d)",
                            session.id, len(new_lessons), len(session.learned_lessons))
                if self._event_bus:
                    await self._event_bus.emit("session.learned", {
                        "session_id": session.id,
                        "new_lessons": len(new_lessons),
                        "total_lessons": len(session.learned_lessons),
                    })

        except Exception as exc:
            logger.debug("ExperienceLearner reflect failed: %s", exc)

    @staticmethod
    def _summarize_turns(session: "AgenticSession") -> str:
        lines = [f"Original request: {session.user_request}"]
        for i, turn in enumerate(session.turns[-6:], 1):
            tool_summary = ", ".join(
                f"{tc.tool_name}(error={tc.error})" if tc.error else tc.tool_name
                for tc in turn.tool_calls
            ) or "none"
            lines.append(
                f"Turn {i}: tools=[{tool_summary}], "
                f"finish={turn.finish_reason}, "
                f"text={turn.assistant_text or ''}"
            )
        return "\n".join(lines)

    @staticmethod
    def _parse_lessons(text: str) -> list[str]:
        lessons = []
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.upper().startswith("LEARNED:"):
                lesson = stripped[len("LEARNED:"):].strip()
                if lesson:
                    lessons.append(lesson)
        return lessons
