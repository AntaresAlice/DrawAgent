"""compare_images tool — Agent C two-image comparison wrapper.

Sends two images simultaneously to the vision model for direct comparison.
Images are resized internally to fit context window limits (temporary workaround).

TODO: Remove image resizing once the vision model or API properly handles
large multi-image context. See: openai_compat.py:compare_images() MAX_DIM.
"""

from __future__ import annotations

from pathlib import Path

from drawagent.core.verbose_log import VerboseLog
from drawagent.providers.base import VisionProvider
from drawagent.tools.base import BaseTool, ToolContext, ToolResult


class CompareImagesTool(BaseTool):
    """Directly compare two generated images using the vision model.

    Sends both images to Agent C in a single call and asks the specified
    comparative questions. The model sees images in order as Image 1 and
    Image 2, and is instructed to label them as such in its response.
    """

    name = "compare_images"
    description = (
        "Compare two generated images side by side using the vision model. "
        "Provide the paths to both images and specify what aspects to compare. "
        "Use this when you want to evaluate whether a new generation improved "
        "over a previous one, or when comparing two variants from the same iteration. "
        "The model sees Image 1 first, then Image 2."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "image_path_1": {
                "type": "string",
                "description": "File path to the first image (shown as Image 1)",
            },
            "image_path_2": {
                "type": "string",
                "description": "File path to the second image (shown as Image 2)",
            },
            "comparison_questions": {
                "type": "string",
                "description": (
                    "What to compare. Can be multiple questions. Examples:\n"
                    "- 'Is Image 2 sharper than Image 1?'\n"
                    "- 'What elements appear in Image 2 that are absent in Image 1?'\n"
                    "- 'Compare lighting, composition, and detail quality between the two.'\n"
                    "- 'Which image better matches the request: a moody twilight cathedral?'"
                ),
            },
            "context": {
                "type": "string",
                "description": "Optional: original user request or prompt for reference",
            },
        },
        "required": ["image_path_1", "image_path_2", "comparison_questions"],
    }

    def __init__(self, vision_provider: VisionProvider | None = None):
        self.provider = vision_provider

    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        if self.provider is None:
            return ToolResult(
                tool_call_id=ctx.tool_call_id or "",
                name=self.name,
                output="",
                error="Vision provider (Agent C) is not configured.",
            )

        path_1 = Path(args["image_path_1"])
        path_2 = Path(args["image_path_2"])
        questions = args["comparison_questions"]
        context = args.get("context")

        for label, p in [("Image 1", path_1), ("Image 2", path_2)]:
            if not p.exists():
                return ToolResult(
                    tool_call_id=ctx.tool_call_id or "",
                    name=self.name,
                    output="",
                    error=f"{label} file not found: {p}",
                )

        vlog = VerboseLog.get()
        vlog.tool_call(
            "compare_images",
            {"image_1": str(path_1), "image_2": str(path_2), "q": questions[:100]},
        )

        try:
            image_data_1 = path_1.read_bytes()
            image_data_2 = path_2.read_bytes()

            observation = await self.provider.compare_images(
                image_data_1=image_data_1,
                image_data_2=image_data_2,
                questions=questions,
                context=context,
            )
        except Exception as exc:
            vlog.tool_result("compare_images", success=False, error=str(exc))
            return ToolResult(
                tool_call_id=ctx.tool_call_id or "",
                name=self.name,
                output="",
                error=f"Vision comparison failed: {exc}",
            )

        vlog.tool_result("compare_images", success=True, output=observation)
        return ToolResult(
            tool_call_id=ctx.tool_call_id or "",
            name=self.name,
            output=observation,
            metadata={
                "image_path_1": str(path_1),
                "image_path_2": str(path_2),
                "comparison_questions": questions,
            },
        )
