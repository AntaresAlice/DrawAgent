from __future__ import annotations

import asyncio
from pathlib import Path

from PIL import Image

from drawagent.core.errors import ProviderError
from drawagent.core.types import InspectionTaskResult
from drawagent.providers.base import VisionProvider
from drawagent.tools.base import BaseTool, ToolContext, ToolResult


class InspectImageTool(BaseTool):
    """Agent C wrapper — uses a vision LLM to inspect generated images.

    Agent A specifies WHAT to look for; Agent C (this tool) describes WHAT IT SEES.
    """

    name = "inspect_image"
    description = (
        "Inspect a generated image using a vision model. Provide a specific inspection task "
        "(e.g., 'Count the fingers on the left hand' or 'Describe the lighting direction') "
        "and the path to the image file. Returns a detailed observation."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "image_path": {
                "type": "string",
                "description": "File path to the image to inspect",
            },
            "task_description": {
                "type": "string",
                "description": "Specific inspection instruction for the vision model",
            },
            "context": {
                "type": "string",
                "description": "Optional additional context (e.g., the original user request)",
            },
        },
        "required": ["image_path", "task_description"],
    }

    def __init__(self, vision_provider: VisionProvider):
        self.provider = vision_provider

    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        image_path = args["image_path"]
        task_description = args["task_description"]
        context = args.get("context")

        path = Path(image_path)
        if not path.exists():
            return ToolResult(
                tool_call_id=ctx.tool_call_id or "",
                name=self.name,
                output="",
                error=f"Image file not found: {image_path}",
            )

        image_data = path.read_bytes()

        try:
            observation = await self.provider.analyze_image(
                image_data=image_data,
                question=task_description,
                context=context,
            )
        except ProviderError as exc:
            return ToolResult(
                tool_call_id=ctx.tool_call_id or "",
                name=self.name,
                output="",
                error=f"Vision API error: {exc}",
            )

        return ToolResult(
            tool_call_id=ctx.tool_call_id or "",
            name=self.name,
            output=observation,
            metadata={
                "image_path": image_path,
                "task_description": task_description,
            },
        )
