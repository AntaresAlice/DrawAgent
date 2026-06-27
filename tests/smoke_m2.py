"""M2 smoke tests for DrawAgent Core Loop."""

import asyncio
import sys

sys.path.insert(0, "src")


async def smoke_test():
    # ── 1. Session Manager ──
    from drawagent.orchestrator.session import SessionManager
    from drawagent.core.types import SessionState

    mgr = SessionManager()
    session = mgr.create(user_request="draw a cat")
    assert session.id
    assert session.user_request == "draw a cat"
    assert session.state == SessionState.IDLE

    mgr.transition(session, SessionState.PLANNING)
    assert session.state == SessionState.PLANNING

    got = mgr.get(session.id)
    assert got is session

    mgr.set_interrupt(session, "steer", "make it blue")
    assert mgr.is_interrupted(session)
    assert session.pending_action == "steer"
    assert session.steer_message == "make it blue"

    mgr.clear_interrupt(session)
    assert not mgr.is_interrupted(session)
    print("1. Session manager: OK")

    # ── 2. Interrupt Handler ──
    from drawagent.orchestrator.interrupt import InterruptHandler

    handler = InterruptHandler()
    assert "pause" in handler.VALID_ACTIONS
    assert "steer" in handler.VALID_ACTIONS

    s2 = mgr.create(user_request="test")
    await handler.handle(s2, "pause")
    assert s2.state == SessionState.INTERRUPTED

    await handler.handle(s2, "resume")
    assert s2.state == SessionState.GENERATING
    assert not s2.interrupt_event.is_set()

    await handler.handle(s2, "steer", {"message": "change style"})
    assert s2.pending_action == "steer"
    assert s2.steer_message == "change style"
    assert s2.interrupt_event.is_set()
    print("2. Interrupt handler: OK")

    # ── 3. Compacted History ──
    from drawagent.context.compaction import CompactedHistory

    ch = CompactedHistory(
        goal="draw a cat",
        progress=["Iter 1: generated cat image"],
        key_decisions=["Iter 1: FAILED — cat has three legs"],
        prompt_evolution=["Iter 1 prompt: a cat sitting on a windowsill"],
        remaining_issues=["distorted legs"],
        next_steps="Refine prompt to fix leg structure",
    )
    ctx_str = ch.to_context_string()
    assert "<compacted_history>" in ctx_str
    assert "<goal>draw a cat</goal>" in ctx_str
    assert "distorted legs" in ctx_str
    print("3. Compacted history: OK")

    # ── 4. Context Assembler ──
    from drawagent.context.assembler import ContextAssembler
    from drawagent.config.schema import AgentBConfig

    b_cfg = AgentBConfig()
    assembler = ContextAssembler(agent_b_config=b_cfg)
    msgs = assembler.assemble_current_turn(session, "generate a cat")
    assert len(msgs) == 2
    assert msgs[0].role == "system"
    assert "Agent A" in msgs[0].content
    assert msgs[1].role == "user"
    assert msgs[1].content == "generate a cat"
    print("4. Context assembler: OK")

    # ── 5. AskUser Tool ──
    from drawagent.tools.human_input import AskUserTool
    from drawagent.tools.base import ToolContext

    ask = AskUserTool()
    ctx = ToolContext(session_id="s1", agent="A")

    async def mock_handler(question, options, context):
        return "test answer"

    ask.set_handler(mock_handler)
    result = await ask.execute(
        {"question": "What style?", "options": ["realistic", "anime"]},
        ctx,
    )
    assert result.success
    assert "test answer" in result.output
    print("5. AskUser tool: OK")

    # ── 6. Tool Registry with multiple tools ──
    from drawagent.tools.base import ToolRegistry, BaseTool, ToolResult

    class CountTool(BaseTool):
        name = "count"
        description = "Count items"
        parameters_schema = {
            "type": "object",
            "properties": {"items": {"type": "array"}},
            "required": ["items"],
        }

        async def execute(self, args, ctx):
            return ToolResult(
                tool_call_id=ctx.tool_call_id or "t1",
                name=self.name,
                output=str(len(args["items"])),
            )

    registry = ToolRegistry()
    registry.register(CountTool())
    registry.register(ask)

    all_names = registry.list_names()
    assert "count" in all_names
    assert "ask_user" in all_names

    mat = registry.materialize(enabled_tools={"count"})
    assert len(mat.definitions) == 1
    assert mat.definitions[0]["function"]["name"] == "count"
    print("6. Tool registry multi-tool: OK")

    # ── 7. GenerateImageTool instantiation ──
    from drawagent.tools.generate_image import GenerateImageTool
    from drawagent.config.schema import AgentBConfig

    b_cfg = AgentBConfig(
        api_base="http://localhost:8000",
        endpoint="/api/generate",
    )
    gen_tool = GenerateImageTool(config=b_cfg, output_dir="./outputs")
    assert gen_tool.name == "generate_image"
    assert gen_tool.parameters_schema["required"] == ["prompt"]
    print("7. GenerateImageTool: OK")

    # ── 8. InspectImageTool instantiation ──
    from drawagent.tools.inspect_image import InspectImageTool

    class MockVisionProvider:
        async def analyze_image(self, image_data, question, context=None, **kwargs):
            return f"Analysis of image: {question[:50]}"

    mock_vision = MockVisionProvider()
    inspect_tool = InspectImageTool(vision_provider=mock_vision)
    assert inspect_tool.name == "inspect_image"
    assert inspect_tool.parameters_schema["required"] == ["image_path", "task_description"]
    print("8. InspectImageTool: OK")

    # ── 9. AgentA instantiation ──
    from drawagent.agents.agent_a import AgentA
    from drawagent.providers.openai_compat import OpenAICompatibleProvider

    class MockLLMProvider:
        def __init__(self):
            self._calls: list[dict] = []

        async def chat_stream(self, messages, tools=None, tool_choice=None, **kwargs):
            yield type("Event", (), {
                "type": "text_delta",
                "content": "Hello from mock",
                "tool_name": None,
                "tool_call_id": None,
                "finish_reason": None,
                "usage": None,
            })()
            yield type("Event", (), {
                "type": "step_finish",
                "content": "",
                "tool_name": None,
                "tool_call_id": None,
                "finish_reason": "stop",
                "usage": None,
            })()

        async def chat(self, messages, tools=None, **kwargs):
            return {"content": '{"passed": true, "confidence": 0.9, "reasoning": "looks good"}'}

    mock_provider = MockLLMProvider()
    agent_a = AgentA(
        provider=mock_provider,
        tool_registry=registry,
        session=session,
    )

    from drawagent.providers.base import LLMMessage
    turn = await agent_a.run_turn(
        messages=[LLMMessage(role="user", content="draw a cat")],
    )
    assert "Hello from mock" in turn.text
    assert turn.finish_reason == "stop"
    print("9. AgentA run_turn: OK")

    # ── 10. InnerLoop instantiation ──
    from drawagent.orchestrator.loop import InnerLoop
    from drawagent.core.events import EventBus
    from drawagent.config.schema import LoopConfig

    loop_cfg = LoopConfig(max_iterations=3)
    event_bus = EventBus()
    s3 = mgr.create(user_request="draw a cat", max_iterations=3)
    agent_a3 = AgentA(provider=mock_provider, tool_registry=registry, session=s3)

    inner = InnerLoop(
        session=s3,
        agent_a=agent_a3,
        tool_registry=registry,
        session_manager=mgr,
        interrupt_handler=handler,
        assembler=assembler,
        event_bus=event_bus,
        config=loop_cfg,
    )
    print("10. InnerLoop instantiation: OK")

    # ── 11. EventBus integration ──
    events_received = []

    async def listen(evt_type, data):
        events_received.append(evt_type)

    event_bus.on("iteration.started", listen)
    event_bus.on("loop.terminated", listen)
    await event_bus.emit("iteration.started", iteration=1)
    await event_bus.emit("loop.terminated", reason="test")
    assert len(events_received) == 2
    print("11. EventBus integration: OK")

    print()
    print("=== ALL M2 SMOKE TESTS PASSED ===")


if __name__ == "__main__":
    asyncio.run(smoke_test())
