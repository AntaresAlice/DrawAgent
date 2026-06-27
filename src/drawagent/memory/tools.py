from __future__ import annotations

from drawagent.tools.base import BaseTool, ToolContext, ToolResult

from .index import MemoryIndex, IndexEntry
from .store import MemoryStore


class LoadMemoryTool(BaseTool):
    """Load a specific memory category into the Agent's context.

    Agent A should call this at session start for relevant categories
    (e.g., prompts/portraits for a portrait request).
    """

    name = "load_memory"
    description = (
        "Load a specific memory category file. Categories are paths like "
        "'prompts/portraits' or 'inspections/_builtin_portrait'. "
        "Returns the full file content (truncated if too long)."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "description": "Memory category path, e.g. 'prompts/portraits', 'inspections/_builtin_portrait'",
            }
        },
        "required": ["category"],
    }

    MAX_OUTPUT_LENGTH = 8000

    def __init__(self, store: MemoryStore):
        self.store = store

    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        category = args["category"]
        content = await self.store.read(category)

        if content is None:
            return ToolResult(
                tool_call_id=ctx.tool_call_id or "",
                name=self.name,
                output=(
                    f"<memory_not_found category='{category}'>"
                    f"Memory file does not exist. Available categories: "
                    f"{', '.join(await self.store.list_categories())}"
                    f"</memory_not_found>"
                ),
            )

        truncated = len(content) > self.MAX_OUTPUT_LENGTH
        if truncated:
            content = (
                content[: self.MAX_OUTPUT_LENGTH]
                + "\n\n(Content truncated. Use search_memory to find specific information.)"
            )

        return ToolResult(
            tool_call_id=ctx.tool_call_id or "",
            name=self.name,
            output=f"<memory category='{category}'>\n{content}\n</memory>",
            metadata={
                "category": category,
                "truncated": truncated,
                "length": len(content),
            },
        )


class SearchMemoryTool(BaseTool):
    """Search all memory files for relevant content by keyword."""

    name = "search_memory"
    description = (
        "Search all memory files for content matching the given query keywords. "
        "Returns top results with file references and content snippets."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search keywords to find relevant memories",
            },
        },
        "required": ["query"],
    }

    def __init__(self, store: MemoryStore):
        self.store = store

    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        query = args["query"]
        results = await self.store.search(query)

        if not results:
            return ToolResult(
                tool_call_id=ctx.tool_call_id or "",
                name=self.name,
                output="<search_results>No matching memories found.</search_results>",
            )

        parts = ["<search_results>"]
        for r in results:
            parts.append(
                f"  <hit file='{r['file']}' category='{r['category']}' score='{r['score']}'>"
            )
            parts.append(f"    {r['snippet'][:300]}")
            parts.append(f"  </hit>")
        parts.append("</search_results>")

        return ToolResult(
            tool_call_id=ctx.tool_call_id or "",
            name=self.name,
            output="\n".join(parts),
            metadata={"query": query, "result_count": len(results)},
        )


class SaveMemoryTool(BaseTool):
    """Save experience or knowledge to the memory system.

    Agent A should call this at session end if it discovered reusable patterns.
    """

    name = "save_memory"
    description = (
        "Save knowledge to the memory system. Use this at session end to preserve "
        "reusable prompt patterns or inspection techniques. Provide a category path, "
        "markdown-formatted content, and a reason for the save (for audit logging)."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "description": "Target category, e.g. 'prompts/portraits' or 'inspections/user_feedback'",
            },
            "content": {
                "type": "string",
                "description": "Markdown-formatted memory entry to append",
            },
            "reason": {
                "type": "string",
                "description": "Why this is worth saving (for audit/review)",
            },
        },
        "required": ["category", "content"],
    }

    def __init__(self, store: MemoryStore, index: MemoryIndex):
        self.store = store
        self.index = index

    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        category = args["category"]
        content = args["content"]
        reason = args.get("reason", "")

        # Add timestamp to the entry
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry = (
            f"\n<!-- saved: {timestamp} -->\n"
            f"<!-- reason: {reason} -->\n"
            f"{content}\n"
        )

        await self.store.write(category, entry, append=True)
        await self.index.update_from_file(category, self.store)

        return ToolResult(
            tool_call_id=ctx.tool_call_id or "",
            name=self.name,
            output=(
                f"<memory_saved category='{category}'>"
                f"Memory saved successfully at {timestamp}."
                f"</memory_saved>"
            ),
            metadata={
                "category": category,
                "reason": reason,
                "timestamp": timestamp,
            },
        )
