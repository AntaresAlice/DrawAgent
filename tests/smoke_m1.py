"""M1 smoke tests for DrawAgent."""

import asyncio
import sys

sys.path.insert(0, "src")


async def smoke_test():
    # 1. Config validation
    from drawagent.config.schema import AppConfig

    cfg = AppConfig()
    assert cfg.agent_a.model == "gpt-4o"
    assert cfg.agent_a.temperature == 0.7
    assert cfg.loop.max_iterations == 7
    assert cfg.agent_c.temperature == 0.3
    print("1. Config validation: OK")

    # 2. Config env var resolution
    import os
    from drawagent.config.loader import ConfigLoader

    os.environ["TEST_VAR"] = "resolved_value"
    result = ConfigLoader._resolve_string("${TEST_VAR}")
    assert result == "resolved_value"
    del os.environ["TEST_VAR"]
    print("2. Config env var resolution: OK")

    # 3. Core types: Session + Iteration
    from drawagent.core.types import Session, SessionState, Iteration

    session = Session(id="test-1", user_request="a cat")
    assert session.state == SessionState.IDLE
    assert session.user_request == "a cat"
    it = Iteration(number=1, prompt="a beautiful cat")
    session.iterations.append(it)
    assert len(session.iterations) == 1
    print("3. Core types: OK")

    # 4. Event bus
    from drawagent.core.events import DrawEvent, EventBus

    events_received = []

    async def handler(evt_type, data):
        events_received.append((evt_type, data))

    bus = EventBus()
    bus.on(DrawEvent.ITERATION_STARTED, handler)
    await bus.emit(DrawEvent.ITERATION_STARTED, iteration=1)
    assert len(events_received) == 1
    assert events_received[0][1]["iteration"] == 1
    print("4. Event bus: OK")

    # 5. Tool registry
    from drawagent.tools.base import BaseTool, ToolRegistry, ToolResult, ToolContext

    class EchoTool(BaseTool):
        name = "echo"
        description = "Echo back input"
        parameters_schema = {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        }

        async def execute(self, args, ctx):
            return ToolResult(
                tool_call_id=ctx.tool_call_id or "t1",
                name=self.name,
                output=f"Echo: {args['text']}",
            )

    registry = ToolRegistry()
    registry.register(EchoTool())
    mat = registry.materialize()
    assert len(mat.definitions) == 1
    assert mat.definitions[0]["function"]["name"] == "echo"

    results = await mat.settle(
        [
            {
                "id": "call_1",
                "function": {"name": "echo", "arguments": '{"text": "hello"}'},
            }
        ],
        ToolContext(session_id="s1", agent="A"),
    )
    assert results[0].output == "Echo: hello"
    assert results[0].success
    print("5. Tool registry: OK")

    # 6. Database initialization
    import tempfile
    from drawagent.persistence.database import Database

    db_path = tempfile.mktemp(suffix=".db")
    db = Database(db_path)
    await db.connect()
    try:
        await db.execute(
            "INSERT INTO sessions (id, user_request) VALUES (?, ?)",
            ("s1", "test request"),
        )
        await db.commit()
        cursor = await db.execute("SELECT * FROM sessions WHERE id = ?", ("s1",))
        row = await cursor.fetchone()
        assert row["user_request"] == "test request"
    finally:
        await db.close()
        import os as _os
        _os.unlink(db_path)
    print("6. Database: OK")

    # 7. Provider factory
    from drawagent.providers.factory import ProviderFactory
    from drawagent.config.schema import AgentAConfig, AgentCConfig

    a_cfg = AgentAConfig(api_key="sk-test")
    c_cfg = AgentCConfig(api_key="sk-test")
    a_prov = ProviderFactory.create_agent_a(a_cfg)
    c_prov = ProviderFactory.create_agent_c(c_cfg)
    assert hasattr(a_prov, "chat_stream")
    assert hasattr(c_prov, "analyze_image")
    print("7. Provider factory: OK")

    # 8. Error hierarchy
    from drawagent.core.errors import (
        DrawAgentError,
        ConfigError,
        ProviderError,
        ToolError,
        SessionError,
    )

    try:
        raise ToolError("test error", tool_name="test")
    except DrawAgentError as e:
        assert e.tool_name == "test"
    print("8. Error hierarchy: OK")

    # 9. Persistence models
    from drawagent.persistence.models import SessionRecord, IterationRecord

    sr = SessionRecord.from_row({
        "id": "s1",
        "user_request": "test",
        "state": "idle",
        "max_iterations": 5,
        "created_at": "2026-01-01",
        "updated_at": "2026-01-01",
    })
    assert sr.id == "s1"
    assert sr.max_iterations == 5
    print("9. Persistence models: OK")

    # 10. LLM Stream events
    from drawagent.providers.base import LLMStreamEvent, LLMMessage

    evt = LLMStreamEvent(
        type="text_delta",
        content="Hello",
    )
    assert evt.type == "text_delta"
    assert evt.content == "Hello"

    msg = LLMMessage(
        role="user",
        content="hello",
    )
    assert msg.role == "user"
    print("10. Stream events: OK")

    print()
    print("=== ALL M1 SMOKE TESTS PASSED ===")


if __name__ == "__main__":
    asyncio.run(smoke_test())
