from __future__ import annotations

from collections.abc import Callable, Awaitable
from typing import Any

from drawagent.tools.base import BaseTool, ToolContext, ToolResult


class AskUserTool(BaseTool):
    """Tool for Agent A to ask the user clarifying questions or request approval.

    In CLI mode: prints to console and waits for input.
    In API mode: pushes question via event bus and waits for response callback.
    """

    name = "ask_user"
    description = (
        "Ask the user a question and wait for their response. Use this when you need "
        "clarification about their request, or when presenting options for them to choose. "
        "The user's response will be returned to you."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "The question to ask the user",
            },
            "options": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional list of predefined options for the user to choose from",
            },
            "context": {
                "type": "string",
                "description": "Why you are asking this question and how the answer will be used",
            },
        },
        "required": ["question"],
    }

    def __init__(self):
        self._prompt_handler: Callable[..., Awaitable[str]] | None = None

    def set_handler(self, handler: Callable[..., Awaitable[str]]) -> None:
        """Set a custom handler for prompting the user (used by API/CLI)."""
        self._prompt_handler = handler

    def prompt(self, question: str, options: list[str] | None = None) -> str:
        """Synchronous prompt for CLI mode."""
        if options:
            print(f"\n[Agent A asks] {question}")
            for i, opt in enumerate(options, 1):
                print(f"  [{i}] {opt}")
            while True:
                try:
                    choice = input("> ").strip()
                    idx = int(choice) - 1
                    if 0 <= idx < len(options):
                        return options[idx]
                except ValueError:
                    pass
                print(f"Please enter 1-{len(options)}")
        else:
            print(f"\n[Agent A asks] {question}")
            return input("> ")

    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        question = args["question"]
        options = args.get("options")
        context = args.get("context", "")

        if self._prompt_handler:
            answer = await self._prompt_handler(question, options, context)
        else:
            answer = self.prompt(question, options)

        return ToolResult(
            tool_call_id=ctx.tool_call_id or "",
            name=self.name,
            output=f"<user_response>{answer}</user_response>",
            metadata={
                "question": question,
                "response": answer,
            },
        )
