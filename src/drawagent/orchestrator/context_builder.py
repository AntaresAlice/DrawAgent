"""Context builder for agentic mode — constructs system prompt + message history.

Analogous to opencode's system prompt assembly + toLLMMessages().
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from drawagent.models.agentic_session import AgenticSession


class ContextBuilder:
    """Builds LLM-ready system prompt and message list for each agentic turn."""

    def __init__(self, agentic_config: dict, agent_a_config: dict | None = None, agent_b_config=None, registry=None):
        self._agentic_config = agentic_config
        self._agent_a_config = agent_a_config or {}
        self._agent_b_config = agent_b_config
        self._registry = registry

    def build_system_prompt(self, session: "AgenticSession") -> str:
        parts = []

        # 1. Base agent identity
        base_prompt = self._resolve_base_system_prompt()
        if base_prompt:
            parts.append(base_prompt)

        # 2. Model info (from AgentB config)
        parts.append(self._model_info())

        # 3. Session state summary
        parts.append(self._state_summary(session))

        # 4. Lessons learned
        parts.append(self._lessons_summary(session))

        # 5. Compaction checkpoints
        parts.append(self._compaction_summary(session))

        # 6. VLM inspection throttle (config-driven, 0 = no limit)
        limit = self._agentic_config.get("max_images_per_inspection", 0)
        if limit > 0:
            parts.append(
                f"IMPORTANT: To control costs, limit inspect_image calls to "
                f"at most {limit} images per iteration. Prioritize the most "
                f"critical inspection tasks.\n\n"
            )

        return "\n\n---\n\n".join(p for p in parts if p)

    def build_messages(self, session: "AgenticSession") -> list[dict]:
        messages: list[dict] = []

        # Compaction summaries go first as user messages
        for comp in session.compactions:
            messages.append({
                "role": "user",
                "content": (
                    "<conversation-checkpoint>\n"
                    f"<summary>{comp.summary}</summary>\n"
                    "</conversation-checkpoint>"
                ),
            })

        # Messages not yet consumed by any turn — show as new user inputs.
        # Uses turn->user_message tracking instead of promoted_at, which avoids
        # the DB/in-memory sync problem where promoted_at is never synced back.
        consumed_ids = {
            turn.user_message.id for turn in session.turns if turn.user_message
        }
        unconsumed = [m for m in session.messages if m.id not in consumed_ids]
        for m in unconsumed:
            messages.append({"role": "user", "content": m.text})

        # Turns: user messages + assistant + tool calls + tool results
        for turn in session.turns:
            if turn.user_message:
                messages.append({
                    "role": "user",
                    "content": turn.user_message.text,
                })

            if turn.assistant_text or turn.tool_calls:
                msg = {"role": "assistant", "content": turn.assistant_text}
                if turn.tool_calls:
                    msg["tool_calls"] = [
                        {
                            "id": tc.call_id,
                            "type": "function",
                            "function": {
                                "name": tc.tool_name,
                                "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                            },
                        }
                        for tc in turn.tool_calls
                    ]
                messages.append(msg)

            # Tool results follow assistant tool_calls
            for tc in turn.tool_calls:
                if tc.status == "completed":
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.call_id,
                        "content": json.dumps(tc.result, ensure_ascii=False) if tc.result else "",
                    })
                elif tc.status == "error":
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.call_id,
                        "content": f"Error: {tc.error}",
                    })

        return messages

    def _resolve_base_system_prompt(self) -> str:
        """Resolve the base system prompt from config or built-in defaults,
        replacing the capabilities section with the actually registered tools."""
        from drawagent.agents.prompts import BASE_SYSTEM_PROMPT, MEMORY_USAGE_GUIDE

        configured = self._agent_a_config.get("system_prompt", "default")
        if configured and configured != "default":
            base = configured
        else:
            base = BASE_SYSTEM_PROMPT

        # Replace the hardcoded "Your Capabilities" section with actual tool list
        actual_tools = self._build_tool_capabilities_section()
        if actual_tools:
            import re
            base = re.sub(
                r'## Your Capabilities\n\n.*?(?=\n## |\Z)',
                actual_tools,
                base,
                flags=re.DOTALL,
            )

        return base + "\n\n" + MEMORY_USAGE_GUIDE

    def _build_tool_capabilities_section(self) -> str:
        """Build a 'Your Capabilities' section from actually registered tools."""
        if self._registry is None:
            return ""
        lines = ["## Your Capabilities", "", "You have access to these tools:"]
        for name in sorted(self._registry.list_names()):
            tool = self._registry.get(name)
            if tool:
                desc = tool.description.split(".")[0][:120]
                lines.append(f"- **{name}**: {desc}.")
        return "\n".join(lines)

    def _model_info(self) -> str:
        """Inject AgentB model parameters and hints into the system prompt."""
        if self._agent_b_config is None:
            return ""
        parts = []
        parts.append(f"## Image Generation Model: {self._agent_b_config.model}")
        params = getattr(self._agent_b_config, "default_params", {})
        parts.append(
            f"## Default Parameters: width={params.get('width', 1024)}, "
            f"height={params.get('height', 1024)}, steps={params.get('steps', 30)}, "
            f"guidance={params.get('guidance', 7.0)}"
        )
        hints = getattr(self._agent_b_config, "model_hints", "")
        if hints and hints.strip():
            parts.append(f"## Model-Specific Knowledge\n{hints.strip()}")
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Summary sections
    # ------------------------------------------------------------------

    @staticmethod
    def _state_summary(session: "AgenticSession") -> str:
        lines = ["## Current Session State"]
        lines.append(f"- Original user request: {session.user_request}")
        lines.append(f"- Turns completed: {len(session.turns)}")
        lines.append(f"- Messages received: {len(session.messages)}")

        if session.iterations:
            last = session.iterations[-1]
            lines.append(f"- Generated images this session: {sum(len(it.images) for it in session.iterations)}")
            if last.decision:
                d = last.decision
                lines.append(
                    f"- Last quality decision: {'PASSED' if d.get('passed') else 'FAILED'} "
                    f"(confidence {d.get('confidence', '?')}/10)"
                )

        if session.errors:
            lines.append(f"- Errors encountered: {len(session.errors)} (latest: {session.errors[-1].get('type', '?')})")

        if session.finalize_rejection_count > 0:
            lines.append(f"- Finalize rejections (consecutive): {session.finalize_rejection_count}")

        return "\n".join(lines)

    @staticmethod
    def _lessons_summary(session: "AgenticSession") -> str:
        if not session.learned_lessons:
            return ""
        lines = ["## Lessons Learned from Previous Iterations"]
        for i, lesson in enumerate(session.learned_lessons[-10:], 1):
            lines.append(f"{i}. {lesson}")
        lines.append("(You are NOT required to follow all lessons — use your best judgment.)")
        return "\n".join(lines)

    @staticmethod
    def _compaction_summary(session: "AgenticSession") -> str:
        if not session.compactions:
            return ""
        comp = session.compactions[-1]
        return (
            "<conversation-checkpoint>\n"
            f"<summary>{comp.summary}</summary>\n"
            "</conversation-checkpoint>"
        )
