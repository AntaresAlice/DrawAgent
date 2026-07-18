from __future__ import annotations

import json
import logging
from typing import AsyncIterator

from drawagent.agents.prompts import PROMPT_INSPECTION_PLAN, PROMPT_EVALUATE, PROMPT_REFINE
from drawagent.context.compaction import CompactedHistory
from drawagent.core.types import (
    InspectionTaskResult,
    Iteration,
    QualityDecision,
    Session,
)
from drawagent.models.agentic_session import AgenticToolCall, AgenticTurnResult
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
        system_prompt: str | None = None,
    ) -> TurnResult:
        """Execute a single Agent A reasoning turn.

        Streams LLM response, collects tool calls, executes them via settle.
        Supports up to one round of tool calling per turn (no recursive tool loops).
        """
        from drawagent.core.verbose_log import VerboseLog
        vlog = VerboseLog.get()

        if system_prompt:
            messages = [LLMMessage(role="system", content=system_prompt)] + messages
        materialization = self.registry.materialize(enabled_tools)
        messages = self._inject_compacted(messages)

        vlog.log("agent_a", f"run_turn: {len(messages)} msg, enabled_tools={enabled_tools}, provider={self.provider.__class__.__name__}")

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
        logging.getLogger("drawagent.agent_a").info(
            "finish=%s, text=%dch, tool_calls=%d", finish_reason, len(text), len(accumulated)
        )

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
            _aqlog = logging.getLogger("drawagent.agent_a")
            _aqlog.info("Calling %s(%s...)", tool_calls_accumulated[0]['function']['name'],
                        tool_calls_accumulated[0]['function']['arguments'][:120])
            tool_results = await materialization.settle(
                tool_calls_accumulated,
                ToolContext(session_id=self.session.id, agent="A"),
            )
            for tr in tool_results:
                if tr.error:
                    _aqlog.warning("Tool ERROR: %s", tr.error[:200])

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

        # Loop continuation until LLM stops making tool calls (handles multi-round
        # patterns like load_memory → generate_image in a single turn)
        MAX_TOOL_ROUNDS = 4
        for _ in range(MAX_TOOL_ROUNDS):
            continuation = await self.provider.chat(
                messages=messages,
                tools=materialization.definitions,
            )
            content = continuation.get("content", "")
            cont_tool_calls = continuation.get("tool_calls") or []
            finish_reason = continuation.get("finish_reason") or finish_reason

            if cont_tool_calls:
                vlog.log("agent_a", f"continuation tool_calls={len(cont_tool_calls)}: {[tc.get('function',{}).get('name','?') for tc in cont_tool_calls]}")
                cont_results = await materialization.settle(cont_tool_calls, ToolContext(session_id=self.session.id, agent="A"))
                tool_results.extend(cont_results)
                for tr in cont_results:
                    if tr.error:
                        logging.getLogger("drawagent.agent_a").warning("Continuation tool ERROR: %s", tr.error[:200])

                messages.append(LLMMessage(role="assistant", content=None, tool_calls=cont_tool_calls))
                for tr in cont_results:
                    formatted = self.format_tool_result(tr)
                    messages.append(LLMMessage(role="tool", content=formatted, tool_call_id=tr.tool_call_id, name=tr.name))
            else:
                if content:
                    text += "\n" + (str(content) if not isinstance(content, str) else content)
                break

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

    # ------------------------------------------------------------------
    # Agentic mode: LLM-driven turn
    # ------------------------------------------------------------------

    async def run_agentic_turn(
        self,
        system_prompt: str,
        messages: list[dict],
        tools: list[dict],
        event_bus,
        verbose: bool = False,
    ) -> AgenticTurnResult:
        """Execute a single LLM call + tool settlement for the agentic loop.

        Analogous to opencode's runTurn(): stream LLM, collect text + tool calls,
        settle tools, return structured result with finalize detection.

        This is NOT a replacement for run_turn() — classic mode still uses run_turn().
        Agentic mode uses this method because it:
          - Takes raw dict messages (not LLMMessage objects)
          - Returns AgenticTurnResult with finalize detection
          - Emits turn.* events for WebSocket
          - Does not reference classic Session at all
        """
        from datetime import datetime
        from drawagent.core.verbose_log import VerboseLog

        vlog = VerboseLog.get()

        # Convert to internal message format
        llm_messages = [LLMMessage(role="system", content=system_prompt)]
        for m in messages:
            role = m.get("role", "user")
            content = m.get("content")
            tool_calls = m.get("tool_calls")
            tool_call_id = m.get("tool_call_id")
            llm_messages.append(LLMMessage(
                role=role,
                content=content,
                tool_calls=tool_calls,
                tool_call_id=tool_call_id,
            ))

        vlog.log("agent_a", f"run_agentic_turn: {len(llm_messages)} msgs, tools={len(tools)}")

        # Materialize tools (all available — LLM chooses which to call)
        materialization = self.registry.materialize_all()

        # Accumulators
        accumulated: dict[str, dict] = {}
        text_parts: list[str] = []
        finish_reason = None
        finalized_this_turn = False
        _tc_counter = 0  # fallback for missing tool_call_id

        # Stream
        async for event in self.provider.chat_stream(
            messages=llm_messages,
            tools=materialization.definitions,
        ):
            if event.type == "text_delta":
                text_parts.append(event.content)
                await event_bus.emit("text.delta", {
                    "content": event.content,
                    "session_id": self.session.id,
                })
            elif event.type == "tool_call_start":
                tc_id = event.tool_call_id or f"tc_{_tc_counter}"
                _tc_counter += 1
                accumulated[tc_id] = {
                    "name": event.tool_name or "",
                    "arguments": "",
                }
            elif event.type == "tool_call_args":
                tc_id = event.tool_call_id
                if not tc_id:
                    # Try to find the last tool call without an ID
                    tc_id = list(accumulated.keys())[-1] if accumulated else None
                if tc_id and tc_id in accumulated:
                    accumulated[tc_id]["arguments"] += event.content
            elif event.type == "step_finish":
                finish_reason = event.finish_reason

        text = "".join(text_parts)
        vlog.log("agent_a", f"finish={finish_reason}, text={len(text)}ch, tool_calls={len(accumulated)}")

        # Fallback: DeepSeek may not stream tool calls — if finish_reason
        # indicates tool_calls but nothing accumulated, try non-streaming.
        if finish_reason == "tool_calls" and not accumulated:
            logger = logging.getLogger("drawagent.agent_a")
            logger.info("Stream had no tool calls despite finish_reason=tool_calls — trying non-streaming chat")
            try:
                continuation = await self.provider.chat(
                    messages=llm_messages,
                    tools=materialization.definitions,
                )
                cont_content = continuation.get("content", "")
                cont_tool_calls = continuation.get("tool_calls") or []
                if cont_content:
                    text += "\n" + str(cont_content)
                    await event_bus.emit("text.delta", {
                        "content": cont_content,
                        "session_id": self.session.id,
                    })
                if cont_tool_calls:
                    logger.info("Non-streaming recovered %d tool calls", len(cont_tool_calls))
                    for tc in cont_tool_calls:
                        fn = tc.get("function", {})
                        tc_id = tc.get("id") or ""
                        if tc_id:
                            accumulated[tc_id] = {
                                "name": fn.get("name", ""),
                                "arguments": fn.get("arguments", ""),
                            }
            except Exception:
                logger.exception("Non-streaming fallback failed")

        # Build tool calls list
        tool_call_dicts: list[dict] = []
        for call_id, acc in accumulated.items():
            if acc.get("arguments"):
                tool_call_dicts.append({
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": acc["name"],
                        "arguments": acc["arguments"],
                    },
                })

        # Parse tool call arguments for persistence + event emission
        import json as _json
        _parsed_args: dict[str, dict] = {}
        for td in tool_call_dicts:
            try:
                _parsed_args[td["id"]] = _json.loads(td["function"]["arguments"])
            except (json.JSONDecodeError, Exception):
                _parsed_args[td["id"]] = {"_raw": td["function"]["arguments"]}

        # Settle tools
        tool_results: list[AgenticToolCall] = []
        if tool_call_dicts:
            ctx = ToolContext(session_id=self.session.id, agent="A")
            # Emit tool.called for each tool BEFORE execution (in-progress indicator)
            for td in tool_call_dicts:
                await event_bus.emit("tool.called", {
                    "session_id": self.session.id,
                    "call_id": td["id"],
                    "tool_name": td["function"]["name"],
                })
            results = await materialization.settle(tool_call_dicts, ctx)
            for result in results:
                now = datetime.now()
                tc = AgenticToolCall(
                    call_id=result.tool_call_id,
                    tool_name=result.name,
                    arguments=_parsed_args.get(result.tool_call_id, {}),
                    status="completed" if result.success else "error",
                    result={"output": result.output, "metadata": result.metadata} if result.success else None,
                    error=result.error,
                    started_at=now,
                    completed_at=now,
                )
                tool_results.append(tc)

                # Check for finalize
                if result.name == "finalize" and result.success:
                    finalized_this_turn = True

                await event_bus.emit("tool.completed", {
                    "session_id": self.session.id,
                    "call_id": result.tool_call_id,
                    "tool_name": result.name,
                    "status": "completed" if result.success else "error",
                    "result": {"output": result.output, "metadata": result.metadata} if result.success else None,
                    "error": result.error if not result.success else None,
                })

        return AgenticTurnResult(
            text=text,
            tool_results=tool_results,
            finish_reason="tool_calls" if tool_results else "stop",
            finalized=finalized_this_turn,
            tokens_used=0,
        )

    # ------------------------------------------------------------------
    # JSON parsing helpers (shared by classic and agentic paths)
    # ------------------------------------------------------------------

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
