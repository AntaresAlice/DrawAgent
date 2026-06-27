"""Integration test — full inner loop with mock providers."""

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from drawagent.agents.agent_a import AgentA
from drawagent.config.schema import AgentBConfig, LoopConfig
from drawagent.context.assembler import ContextAssembler
from drawagent.core.events import EventBus
from drawagent.core.types import SessionState
from drawagent.orchestrator.interrupt import InterruptHandler
from drawagent.orchestrator.loop import InnerLoop
from drawagent.orchestrator.session import SessionManager
from drawagent.tools.base import BaseTool, ToolContext, ToolRegistry, ToolResult


class _MockGenTool(BaseTool):
    name = "generate_image"
    description = "Generate images"
    parameters_schema = {
        "type": "object",
        "properties": {"prompt": {"type": "string"}},
        "required": ["prompt"],
    }

    async def execute(self, args, ctx):
        return ToolResult(
            tool_call_id=ctx.tool_call_id or "t1",
            name=self.name,
            output="Generated image at /tmp/test.png",
            metadata={
                "images": [
                    {"path": "/tmp/test.png", "filename": "test.png", "seed": 42, "width": 1024, "height": 1024},
                ],
                "prompt": args["prompt"],
                "seeds": [42],
            },
        )


class _MockInspectTool(BaseTool):
    name = "inspect_image"
    description = "Inspect image"
    parameters_schema = {
        "type": "object",
        "properties": {
            "image_path": {"type": "string"},
            "task_description": {"type": "string"},
        },
        "required": ["image_path", "task_description"],
    }

    async def execute(self, args, ctx):
        return ToolResult(
            tool_call_id=ctx.tool_call_id or "t1",
            name=self.name,
            output="Image looks good. No issues found.",
        )


class MockLLMProvider:
    """Mock LLM provider that returns controlled responses."""

    def __init__(self, responses: list[str] | None = None):
        self.responses = responses or []
        self.call_index = 0
        self.chat_calls: list[dict] = []

    async def chat_stream(self, messages, tools=None, tool_choice=None, **kwargs):
        resp = self._next_response()

        if "generate" in str(messages).lower() or "Generate" in str(messages):
            yield type("Ev", (), {
                "type": "tool_call_start",
                "content": "", "tool_name": "generate_image",
                "tool_call_id": "g1", "finish_reason": None, "usage": None,
            })()
            yield type("Ev", (), {
                "type": "tool_call_args",
                "content": '{"prompt": "a cat"}',
                "tool_name": "generate_image",
                "tool_call_id": "g1", "finish_reason": None, "usage": None,
            })()
            yield type("Ev", (), {
                "type": "step_finish",
                "content": "", "tool_name": None,
                "tool_call_id": None, "finish_reason": "tool_calls", "usage": None,
            })()
        elif "inspect" in str(messages).lower() or "Inspect" in str(messages):
            yield type("Ev", (), {
                "type": "tool_call_start",
                "content": "", "tool_name": "inspect_image",
                "tool_call_id": "i1", "finish_reason": None, "usage": None,
            })()
            yield type("Ev", (), {
                "type": "tool_call_args",
                "content": '{"image_path": "/tmp/test.png", "task_description": "check quality"}',
                "tool_name": "inspect_image",
                "tool_call_id": "i1", "finish_reason": None, "usage": None,
            })()
            yield type("Ev", (), {
                "type": "step_finish",
                "content": "", "tool_name": None,
                "tool_call_id": None, "finish_reason": "tool_calls", "usage": None,
            })()
        else:
            yield type("Ev", (), {
                "type": "text_delta", "content": resp,
                "tool_name": None, "tool_call_id": None,
                "finish_reason": None, "usage": None,
            })()
            yield type("Ev", (), {
                "type": "step_finish",
                "content": "", "tool_name": None,
                "tool_call_id": None, "finish_reason": "stop", "usage": None,
            })()

    async def chat(self, messages, tools=None, **kwargs):
        self.chat_calls.append({"messages": len(messages), "tools": bool(tools)})
        resp = self._next_response()
        return {"content": resp}

    def _next_response(self) -> str:
        if self.responses:
            idx = self.call_index % len(self.responses)
            self.call_index += 1
            return self.responses[idx]
        self.call_index += 1
        return '[{"name":"check","description":"Check quality"}]'


class TestIntegration:

    @pytest.mark.asyncio
    async def test_full_loop_single_iteration_pass(self, tmp_path):
        """Full loop with mock providers — agent passes on first iteration."""
        mock_llm = MockLLMProvider(responses=[
            # inspection plan
            '[{"name":"check_quality","description":"Check overall quality"}]',
            # quality evaluation — pass
            json.dumps({
                "passed": True,
                "confidence": 0.95,
                "reasoning": "All checks passed",
                "remaining_issues": [],
                "recommendation": "accept",
            }),
            # generate_image tool execution continuation
            "Generated successfully.",
            # inspect_image tool execution continuation
            "Looks good.",
        ])

        session_mgr = SessionManager()
        session = session_mgr.create(user_request="draw a cat", max_iterations=3)
        interrupt_handler = InterruptHandler()

        registry = ToolRegistry()
        registry.register(_MockGenTool())
        registry.register(_MockInspectTool())

        agent_a = AgentA(provider=mock_llm, tool_registry=registry, session=session)

        assembler = ContextAssembler(agent_b_config=AgentBConfig())
        event_bus = EventBus()

        loop = InnerLoop(
            session=session,
            agent_a=agent_a,
            tool_registry=registry,
            session_manager=session_mgr,
            interrupt_handler=interrupt_handler,
            assembler=assembler,
            event_bus=event_bus,
            config=LoopConfig(max_iterations=3),
        )

        result = await loop.run(initial_prompt="a beautiful cat")

        assert result.terminated_reason in ("quality_passed", "auto_accepted")
        assert result.iterations_completed >= 1
        assert len(session.iterations) >= 1
        assert session.iterations[0].decision.passed

    @pytest.mark.asyncio
    async def test_loop_max_iterations_reached(self, tmp_path):
        """Loop terminates after max iterations with failing evaluations."""
        mock_llm = MockLLMProvider(responses=[
            '[{"name":"c1","description":"Check"}]',
            json.dumps({"passed": False, "confidence": 0.6, "reasoning": "bad", "remaining_issues": [], "recommendation": "iterate"}),
            "ok",
            "ok",
            '[{"name":"c2","description":"Re-check"}]',
            json.dumps({"passed": False, "confidence": 0.6, "reasoning": "still bad", "remaining_issues": [], "recommendation": "iterate"}),
            "ok",
            "ok",
            '[{"name":"c3","description":"Re-re-check"}]',
            json.dumps({"passed": False, "confidence": 0.6, "reasoning": "still bad", "remaining_issues": [], "recommendation": "iterate"}),
            "ok",
            "ok",
        ])

        session_mgr = SessionManager()
        session = session_mgr.create(user_request="draw a cat", max_iterations=2)
        session.max_iterations = 2
        interrupt_handler = InterruptHandler()

        registry = ToolRegistry()
        registry.register(_MockGenTool())
        registry.register(_MockInspectTool())

        agent_a = AgentA(provider=mock_llm, tool_registry=registry, session=session)

        assembler = ContextAssembler(agent_b_config=AgentBConfig())
        event_bus = EventBus()

        loop = InnerLoop(
            session=session,
            agent_a=agent_a,
            tool_registry=registry,
            session_manager=session_mgr,
            interrupt_handler=interrupt_handler,
            assembler=assembler,
            event_bus=event_bus,
            config=LoopConfig(max_iterations=2),
        )

        result = await loop.run(initial_prompt="a cat")
        assert result.terminated_reason == "max_iterations"

    @pytest.mark.asyncio
    async def test_loop_user_interrupt_accept(self, tmp_path):
        """User interrupts with accept_current."""
        responses = []
        for i in range(5):
            responses.extend([
                '[{"name":"c","description":"Check"}]',
                json.dumps({"passed": False, "confidence": 0.5, "reasoning": "needs work", "remaining_issues": [], "recommendation": "iterate"}),
                "ok",
                "ok",
            ])

        mock_llm = MockLLMProvider(responses=responses)

        session_mgr = SessionManager()
        session = session_mgr.create(user_request="draw a cat", max_iterations=5)
        interrupt_handler = InterruptHandler()

        registry = ToolRegistry()
        registry.register(_MockGenTool())
        registry.register(_MockInspectTool())

        agent_a = AgentA(provider=mock_llm, tool_registry=registry, session=session)
        assembler = ContextAssembler(agent_b_config=AgentBConfig())
        event_bus = EventBus()

        loop = InnerLoop(
            session=session,
            agent_a=agent_a,
            tool_registry=registry,
            session_manager=session_mgr,
            interrupt_handler=interrupt_handler,
            assembler=assembler,
            event_bus=event_bus,
            config=LoopConfig(max_iterations=5),
        )

        # Set interrupt before starting the loop
        await interrupt_handler.handle(session, "accept_current")
        result = await loop.run(initial_prompt="a cat")

        assert result.terminated_reason == "user_accept"
