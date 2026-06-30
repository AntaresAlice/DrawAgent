from __future__ import annotations

import json
from typing import AsyncIterator

from drawagent.agents.prompts import PROMPT_INSPECTION_PLAN, PROMPT_EVALUATE, PROMPT_REFINE
from drawagent.context.compaction import CompactedHistory
from drawagent.core.types import (
    InspectionTaskResult,
    Iteration,
    QualityDecision,
    Session,
)
from drawagent.providers.base import LLMMessage, LLMProvider, LLMStreamEvent
from drawagent.tools.base import ToolRegistry, ToolContext, ToolResult


class TurnResult:
    """Result of a single Agent A turn."""

    def __init__(
        self,
        text: str = "",
        tool_results: list[ToolResult] | None = None,
        finish_reason: str | None = None,
    ):
        self.text = text
        self.tool_results = tool_results or []
        self.finish_reason = finish_reason


class AgentA:
    """Agent A — the main orchestrator LLM.

    Handles: prompt writing, inspection planning, quality evaluation, user interaction.

    Reference: opencode's run_turn() — stream LLM, collect tool calls, parallel settle.
    Key difference: Agent A turns are program-driven (called for specific phases),
    not LLM-autonomous. A only decides within its designated scope per call.
    """

    def __init__(
        self,
        provider: LLMProvider,
        tool_registry: ToolRegistry,
        session: Session,
    ):
        self.provider = provider
        self.registry = tool_registry
        self.session = session
        self._compacted: CompactedHistory | None = None

    def _inject_compacted(self, messages: list[LLMMessage]) -> list[LLMMessage]:
        if self._compacted:
            result = [
                LLMMessage(
                    role="system",
                    content=self._compacted.to_context_string(),
                ),
                *messages,
            ]
            return result
        return messages

    async def run_turn(
        self,
        messages: list[LLMMessage],
        enabled_tools: set[str] | None = None,
        stream_callback: AsyncIterator[LLMStreamEvent] | None = None,
    ) -> TurnResult:
        """Execute a single Agent A reasoning turn.

        Streams LLM response, collects tool calls, executes them via settle.
        Supports up to one round of tool calling per turn (no recursive tool loops).
        """
        materialization = self.registry.materialize(enabled_tools)
        messages = self._inject_compacted(messages)

        tool_calls_accumulated: list[dict] = []
        accumulated: dict[str, dict] = {}
        text_parts: list[str] = []
        finish_reason = None

        async for event in self.provider.chat_stream(
            messages=messages,
            tools=materialization.definitions,
        ):
            if event.type == "text_delta":
                text_parts.append(event.content)
            elif event.type == "tool_call_start":
                if event.tool_call_id:
                    accumulated[event.tool_call_id] = {
                        "name": event.tool_name or "",
                        "arguments": "",
                    }
            elif event.type == "tool_call_args":
                if event.tool_call_id and event.tool_call_id in accumulated:
                    accumulated[event.tool_call_id]["arguments"] += event.content
            elif event.type == "step_finish":
                finish_reason = event.finish_reason

        text = "".join(text_parts)
        print(f"  [AgentA] finish={finish_reason}, text={len(text)}ch, tool_calls={len(accumulated)}", flush=True)

        for call_id, acc in accumulated.items():
            if acc["arguments"]:
                tool_calls_accumulated.append({
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": acc["name"],
                        "arguments": acc["arguments"],
                    },
                })

        tool_results: list[ToolResult] = []
        if tool_calls_accumulated:
            print(f"  [AgentA] Calling {tool_calls_accumulated[0]['function']['name']}("
                  f"{tool_calls_accumulated[0]['function']['arguments'][:120]}...)", flush=True)
            tool_results = await materialization.settle(
                tool_calls_accumulated,
                ToolContext(session_id=self.session.id, agent="A"),
            )
            for tr in tool_results:
                if tr.error:
                    print(f"  [AgentA] Tool ERROR: {tr.error[:200]}", flush=True)

            # OpenAI/DeepSeek requires assistant msg with tool_calls before tool msgs
            messages.append(LLMMessage(
                role="assistant",
                content=None,
                tool_calls=tool_calls_accumulated,
            ))

            for tr in tool_results:
                formatted = self.format_tool_result(tr)
                messages.append(LLMMessage(
                    role="tool",
                    content=formatted,
                    tool_call_id=tr.tool_call_id,
                    name=tr.name,
                ))

            continuation = await self.provider.chat(
                messages=messages,
                tools=materialization.definitions,
            )
            content = continuation.get("content", "")
            if content:
                text += "\n" + (str(content) if not isinstance(content, str) else content)

        return TurnResult(
            text=text,
            tool_results=tool_results,
            finish_reason=finish_reason,
        )

    def format_tool_result(self, result: ToolResult) -> str:
        if result.error:
            return f"<tool_error name='{result.name}'>{result.error}</tool_error>"
        return f"<tool_result name='{result.name}'>{result.output}</tool_result>"

    async def clarify_request(self, current_prompt: str) -> str | None:
        """Clarify the user's request before starting generation.

        Returns a summary of understanding, or None to skip clarification.
        """
        messages = self._inject_compacted([
            LLMMessage(
                role="system",
                content=(
                    "You are Agent A — an art director. Before starting image generation, "
                    "briefly summarize your understanding of the user's request and confirm "
                    "the key details: subject, style, composition, mood, any specific elements. "
                    "Keep it under 3 sentences. Output ONLY the summary, nothing else."
                ),
            ),
            LLMMessage(role="user", content=current_prompt),
        ])
        result = await self.provider.chat(messages)
        content = result.get("content", "")
        text = content if isinstance(content, str) else str(content)
        if text and len(text) > 10:
            return text.strip()
        return None

    async def refine_prompt(self, current_prompt: str, issues: list[dict]) -> str:
        """Refine the generation prompt based on inspection issues."""
        messages = self._inject_compacted([
            LLMMessage(role="system", content=PROMPT_REFINE),
            LLMMessage(
                role="user",
                content=(
                    f"Original request: {self.session.user_request}\n\n"
                    f"Current prompt: {current_prompt}\n\n"
                    f"Issues found:\n{json.dumps(issues, ensure_ascii=False, indent=2)}\n\n"
                    f"Please output the refined prompt."
                ),
            ),
        ])
        result = await self.provider.chat(messages)
        content = result.get("content", "")
        return content if isinstance(content, str) else str(content)

    async def design_inspection_plan(
        self,
        current_prompt: str,
        iteration: int,
        previous_issues: list[dict] | None = None,
    ) -> list[dict]:
        """Design a list of inspection tasks for the current iteration."""
        context_parts = [
            f"Original request: {self.session.user_request}",
            f"Current prompt: {current_prompt}",
            f"Iteration: {iteration}",
        ]
        if previous_issues:
            prev_json = json.dumps(previous_issues, ensure_ascii=False, indent=2)
            context_parts.append(f"Previous issues to re-check:\n{prev_json}")

        messages = self._inject_compacted([
            LLMMessage(role="system", content=PROMPT_INSPECTION_PLAN),
            LLMMessage(role="user", content="\n\n".join(context_parts)),
        ])
        result = await self.provider.chat(messages)
        content = result.get("content", "[]")
        text = content if isinstance(content, str) else str(content)
        return self._parse_json_array(text)

    async def evaluate_quality(
        self,
        current_prompt: str,
        inspection_results: list[InspectionTaskResult],
        iteration: int,
    ) -> QualityDecision:
        """Evaluate overall image quality based on inspection results."""
        inspection_json = json.dumps(
            [
                {
                    "task": r.task_name,
                    "passed": r.passed,
                    "observation": r.observation,
                    "issues": r.issues,
                }
                for r in inspection_results
            ],
            ensure_ascii=False,
            indent=2,
        )

        messages = self._inject_compacted([
            LLMMessage(role="system", content=PROMPT_EVALUATE),
            LLMMessage(
                role="user",
                content=(
                    f"Original request: {self.session.user_request}\n\n"
                    f"Current prompt: {current_prompt}\n\n"
                    f"Iteration: {iteration}/{self.session.max_iterations}\n\n"
                    f"Inspection results:\n{inspection_json}\n\n"
                    f"Output your quality decision as JSON."
                ),
            ),
        ])
        result = await self.provider.chat(messages)
        content = result.get("content", "{}")
        text = content if isinstance(content, str) else str(content)
        return self._parse_quality_decision(text)

    def _find_json_block(self, text: str, bracket_type: str = "object") -> str | None:
        """Find the first balanced JSON block using bracket counting.

        Avoids greedy regex bugs when multiple JSON blocks exist in the text.
        """
        open_b, close_b = ('[', ']') if bracket_type == 'array' else ('{', '}')
        start = text.find(open_b)
        if start == -1:
            return None

        depth = 0
        in_string = False
        escape = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_string:
                if escape:
                    escape = False
                elif ch == '\\':
                    escape = True
                elif ch == '"':
                    in_string = False
            else:
                if ch == '"':
                    in_string = True
                elif ch == open_b:
                    depth += 1
                elif ch == close_b:
                    depth -= 1
                    if depth == 0:
                        return text[start:i + 1]
        return None

    def _parse_json_array(self, text: str) -> list[dict]:
        block = self._find_json_block(text, "array")
        if block:
            return json.loads(block)
        return []

    def _parse_quality_decision(self, text: str) -> QualityDecision:
        block = self._find_json_block(text, "object")
        if block:
            data = json.loads(block)
            return QualityDecision(
                passed=data.get("passed", False),
                confidence=float(data.get("confidence", 0.5)),
                reasoning=data.get("reasoning", text),
                remaining_issues=data.get("remaining_issues", []),
                recommendation=data.get("recommendation", "iterate"),
            )
        return QualityDecision(
            passed=False,
            confidence=0.3,
            reasoning=f"Failed to parse LLM response as JSON: {text[:200]}",
            recommendation="ask_user",
        )
