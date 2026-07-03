"""finalize tool — LLM signals task completion in agentic mode.

Analogous to opencode's step-finish event (finish_reason="stop").
The LLM must explicitly declare which images are accepted and why.
The program verifies the declaration against inspection results before allowing exit.
"""

from __future__ import annotations

from drawagent.tools.base import BaseTool, ToolContext, ToolResult


class FinalizeTool(BaseTool):
    """Let the LLM declare the task is complete with specific delivery.

    The LLM MUST call this tool to end the generation loop. Simply returning
    text without finalize is not accepted — the program will ask the LLM to
    either finalize or continue working.

    The `accepted_images` argument must be based on actual inspection results.
    If the program detects inspection failures that contradict the acceptance,
    it will reject the finalize call and ask the LLM to fix the issues.
    """

    name = "finalize"
    description = (
        "Declare the image generation task complete. You MUST specify exactly "
        "which images are accepted and which are rejected, with a reason citing "
        "specific inspection results. The program will verify your declaration "
        "against actual inspection outcomes. If verification fails, finalize is "
        "rejected and you must fix the issues before calling finalize again."
    )
    parameters_schema: dict = {
        "type": "object",
        "properties": {
            "accepted_images": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "File paths of images that pass quality standards. "
                    "Must be based on actual inspection results, not guesswork."
                ),
            },
            "rejected_images": {
                "type": "array",
                "items": {"type": "string"},
                "description": "File paths of images that failed quality checks.",
            },
            "reason": {
                "type": "string",
                "description": (
                    "Detailed reason for acceptance. Cite specific inspection checks "
                    "that passed and failed. Format: 'PASS: <dimension> (<detail>), "
                    "FAIL: <dimension> (<detail>)'. Be honest about quality issues — "
                    "fabricating pass results will be detected by program verification."
                ),
            },
        },
        "required": ["accepted_images", "reason"],
    }

    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        accepted = args.get("accepted_images", [])
        rejected = args.get("rejected_images", [])
        reason = args.get("reason", "")
        return ToolResult(
            tool_call_id=ctx.tool_call_id or "",
            name=self.name,
            output=(
                f"Task finalized.\n"
                f"Accepted ({len(accepted)}): {', '.join(accepted) or 'none'}\n"
                f"Rejected ({len(rejected)}): {', '.join(rejected) or 'none'}\n"
                f"Reason: {reason}"
            ),
            metadata={
                "accepted_images": accepted,
                "rejected_images": rejected,
                "reason": reason,
            },
        )
