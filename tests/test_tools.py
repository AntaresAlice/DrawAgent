"""Unit tests for tool system."""

import json

import pytest

from drawagent.tools.base import (
    BaseTool,
    ToolContext,
    ToolMaterialization,
    ToolRegistry,
    ToolResult,
)


class _EchoTool(BaseTool):
    name = "echo"
    description = "Echo input"
    parameters_schema = {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    }

    async def execute(self, args, ctx):
        return ToolResult(tool_call_id=ctx.tool_call_id or "t1", name=self.name, output=args["text"])


class _FailingTool(BaseTool):
    name = "failer"
    description = "Always fails"
    parameters_schema = {"type": "object", "properties": {}}

    async def execute(self, args, ctx):
        return ToolResult(tool_call_id=ctx.tool_call_id or "t1", name=self.name, output="", error="deliberate error")


class TestToolResult:
    def test_success(self):
        r = ToolResult(tool_call_id="c1", name="t", output="ok")
        assert r.success is True

    def test_error(self):
        r = ToolResult(tool_call_id="c1", name="t", output="", error="fail")
        assert r.success is False


class TestToolDefinition:
    def test_openai_schema(self):
        tool = _EchoTool()
        schema = tool.to_openai_schema()
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "echo"
        assert "text" in str(schema["function"]["parameters"])

    def test_format_output_success(self):
        tool = _EchoTool()
        result = ToolResult(tool_call_id="c1", name="echo", output="hello")
        formatted = tool.format_output_for_llm(result)
        assert "<tool_result" in formatted
        assert "hello" in formatted

    def test_format_output_error(self):
        tool = _EchoTool()
        result = ToolResult(tool_call_id="c1", name="echo", output="", error="bad")
        formatted = tool.format_output_for_llm(result)
        assert "<tool_error" in formatted
        assert "bad" in formatted


class TestToolRegistry:
    def test_register_and_list(self):
        registry = ToolRegistry()
        registry.register(_EchoTool())
        assert "echo" in registry.list_names()
        assert registry.get("echo") is not None
        assert registry.get("nonexistent") is None

    def test_unregister(self):
        registry = ToolRegistry()
        registry.register(_EchoTool())
        registry.unregister("echo")
        assert "echo" not in registry.list_names()

    async def test_materialize_single(self):
        registry = ToolRegistry()
        registry.register(_EchoTool())
        mat = registry.materialize()
        assert len(mat.definitions) == 1

        results = await mat.settle(
            [{"id": "c1", "function": {"name": "echo", "arguments": '{"text":"hello"}'}}],
            ToolContext(session_id="s1", agent="A"),
        )
        assert len(results) == 1
        assert results[0].output == "hello"

    async def test_materialize_filtered(self):
        registry = ToolRegistry()
        registry.register(_EchoTool())
        registry.register(_FailingTool())
        mat = registry.materialize(enabled_tools={"echo"})
        assert len(mat.definitions) == 1
        assert mat.definitions[0]["function"]["name"] == "echo"

    async def test_materialize_unknown_tool(self):
        registry = ToolRegistry()
        mat = registry.materialize()
        results = await mat.settle(
            [{"id": "c1", "function": {"name": "ghost", "arguments": "{}"}}],
            ToolContext(session_id="s1", agent="A"),
        )
        assert results[0].error is not None
        assert "Unknown" in results[0].error

    async def test_materialize_invalid_json(self):
        registry = ToolRegistry()
        registry.register(_EchoTool())
        mat = registry.materialize()
        results = await mat.settle(
            [{"id": "c1", "function": {"name": "echo", "arguments": "not json"}}],
            ToolContext(session_id="s1", agent="A"),
        )
        assert results[0].error is not None

    async def test_materialize_multiple_tools(self):
        registry = ToolRegistry()
        registry.register(_EchoTool())
        registry.register(_FailingTool())
        mat = registry.materialize()

        results = await mat.settle(
            [
                {"id": "c1", "function": {"name": "echo", "arguments": '{"text":"ok"}'}},
                {"id": "c2", "function": {"name": "failer", "arguments": "{}"}},
            ],
            ToolContext(session_id="s1", agent="A"),
        )
        assert len(results) == 2
        assert results[0].success
        assert not results[1].success


class TestToolContext:
    def test_defaults(self):
        ctx = ToolContext(session_id="s1", agent="A")
        assert ctx.session_id == "s1"
        assert ctx.agent == "A"
        assert ctx.message_id is None
        assert ctx.tool_call_id is None

    def test_with_ids(self):
        ctx = ToolContext(
            session_id="s1", agent="A",
            message_id="m1", tool_call_id="c1",
        )
        assert ctx.message_id == "m1"
        assert ctx.tool_call_id == "c1"
