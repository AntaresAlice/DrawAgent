from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolResult:
    """Result of a tool execution.

    Reference: opencode's ExecuteResult pattern.
    """

    tool_call_id: str
    name: str
    output: str
    metadata: dict = field(default_factory=dict)
    error: str | None = None

    @property
    def success(self) -> bool:
        return self.error is None


@dataclass
class ToolDefinition:
    """Tool definition in OpenAI function-calling format."""

    name: str
    description: str
    parameters: dict


@dataclass
class ToolContext:
    """Context passed to tool execution.

    Reference: opencode's Tool.Context.
    """

    session_id: str
    agent: str
    message_id: str | None = None
    tool_call_id: str | None = None


@dataclass
class ToolMaterialization:
    """Materialized tools ready for LLM consumption.

    Reference: opencode's materialize() → settle pattern.
    The definitions are sent to the LLM; settle executes the tool calls.
    """

    definitions: list[dict]
    settle: Callable[..., Awaitable[list[ToolResult]]]


class BaseTool(ABC):
    """Tool base class.

    Reference: opencode's Tool.define() pattern:
    register → materialize → settle (three-phase lifecycle).
    """

    name: str
    description: str
    parameters_schema: dict

    @abstractmethod
    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        ...

    def to_openai_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters_schema,
            },
        }

    def format_output_for_llm(self, result: ToolResult) -> str:
        """Format tool result for LLM consumption.

        Reference: opencode's XML-tag output format.
        """
        if result.error:
            return f"<tool_error name='{self.name}'>{result.error}</tool_error>"
        return f"<tool_result name='{self.name}'>{result.output}</tool_result>"


class ToolRegistry:
    """Central tool registry.

    Reference: opencode's ToolRegistry with materialize/settle pattern.
    """

    def __init__(self):
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def list_names(self) -> list[str]:
        return list(self._tools.keys())

    def materialize(
        self, enabled_tools: set[str] | None = None
    ) -> ToolMaterialization:
        """Materialize tools for LLM consumption.

        Reference: opencode's materialize — filters by permissions,
        generates LLM definitions, returns settle function.
        """
        active = {
            name: tool
            for name, tool in self._tools.items()
            if enabled_tools is None or name in enabled_tools
        }

        definitions = [t.to_openai_schema() for t in active.values()]

        async def settle(tool_calls: list[dict], ctx: ToolContext) -> list[ToolResult]:
            results: list[ToolResult] = []
            for call in tool_calls:
                fn = call["function"]
                name = fn["name"]
                call_id = call["id"]

                tool = active.get(name)
                if tool is None:
                    results.append(ToolResult(
                        tool_call_id=call_id,
                        name=name,
                        output="",
                        error=f"Unknown tool: {name}",
                    ))
                    continue

                try:
                    args = json.loads(fn["arguments"])
                except json.JSONDecodeError as e:
                    results.append(ToolResult(
                        tool_call_id=call_id,
                        name=name,
                        output="",
                        error=f"Invalid JSON arguments: {e}",
                    ))
                    continue

                ctx.tool_call_id = call_id
                result = await tool.execute(args, ctx)
                results.append(result)

            return results

        return ToolMaterialization(definitions=definitions, settle=settle)
