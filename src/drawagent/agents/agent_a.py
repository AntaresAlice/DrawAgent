from __future__ import annotations

import json
import re
from typing import AsyncIterator

from drawagent.agents.prompts import PROMPT_INSPECTION_PLAN, PROMPT_EVALUATE, PROMPT_REFINE
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
                if stream_callback:
                    await stream_callback.__anext__()  # noqa: typing escape

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

        for call_id, acc in accumulated.items():
            if acc["arguments"]:
                tool_calls_accumulated.append({
                    "id": call_id,
                    "function": {
                        "name": acc["name"],
                        "arguments": acc["arguments"],
                    },
                })

        tool_results: list[ToolResult] = []
        if tool_calls_accumulated:
            tool_results = await materialization.settle(
                tool_calls_accumulated,
                ToolContext(session_id=self.session.id, agent="A"),
            )

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

    async def refine_prompt(self, current_prompt: str, issues: list[dict]) -> str:
        """Refine the generation prompt based on inspection issues."""
        messages = [
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
        ]
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

        messages = [
            LLMMessage(role="system", content=PROMPT_INSPECTION_PLAN),
            LLMMessage(role="user", content="\n\n".join(context_parts)),
        ]
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

        messages = [
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
        ]
        result = await self.provider.chat(messages)
        content = result.get("content", "{}")
        text = content if isinstance(content, str) else str(content)
        return self._parse_quality_decision(text)

    def _parse_json_array(self, text: str) -> list[dict]:
        match = re.search(r"\[.*\]", text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        return []

    def _parse_quality_decision(self, text: str) -> QualityDecision:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            data = json.loads(match.group(0))
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
