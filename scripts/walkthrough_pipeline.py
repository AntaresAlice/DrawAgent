"""
DrawAgent full pipeline walkthrough — DeepSeek A → Z-Image MCP B → Ollama C.

Every LLM response, tool call, generation, and inspection is captured
via verbose logging. Results saved to temp/walkthrough/.
"""
import asyncio
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent))

import yaml

from drawagent.agents.agent_a import AgentA
from drawagent.config.schema import AppConfig
from drawagent.context.assembler import ContextAssembler
from drawagent.core.events import EventBus
from drawagent.core.verbose_log import VerboseLog
from drawagent.orchestrator.interrupt import InterruptHandler
from drawagent.orchestrator.loop import InnerLoop
from drawagent.orchestrator.session import SessionManager
from drawagent.providers.factory import ProviderFactory
from drawagent.tools.base import ToolRegistry
from drawagent.tools.generate_image import GenerateImageTool
from drawagent.tools.inspect_image import InspectImageTool
from drawagent.tools.compare_images import CompareImagesTool

# ── Sett logging to DEBUG for maximum detail ───────────────────────────────
LOG_LINES = []
_t0 = time.monotonic()

def log_line(record):
    ts = time.monotonic() - _t0
    msg = record.getMessage()
    name = record.name
    if name.startswith("drawagent"):
        line = f"[{ts:7.1f}s] [{name:30s}] {msg}"
    else:
        line = f"[{ts:7.1f}s] [{record.levelname:5s}] {record.name}: {msg}"
    LOG_LINES.append(line)
    print(line)

class LogCapture(logging.Handler):
    def emit(self, record):
        log_line(record)

logging.getLogger().setLevel(logging.DEBUG)
for h in logging.getLogger().handlers[:]:
    logging.getLogger().removeHandler(h)
logging.getLogger().addHandler(LogCapture())

# Enable specific loggers
for name in ["drawagent", "drawagent.mcp", "drawagent.agents", "drawagent.tools",
             "drawagent.orchestrator", "drawagent.providers", "drawagent.api",
             "drawagent.config", "drawagent.context"]:
    logging.getLogger(name).setLevel(logging.DEBUG)


async def main():
    t_start = time.monotonic()

    # ── Config ─────────────────────────────────────────────────────────────
    logging.info("=== Loading config ===")
    config_path = Path(__file__).parent.parent / "config.example.yaml"
    with open(config_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    raw["agent_b"]["mcp_command"] = [
        r"D:\SoftwareStation\Conda\envs\qwen-image\python.exe",
        r"D:\Code\Z-Image-MCP\mcp_server.py",
    ]
    raw["agent_b"]["mcp_keep_alive"] = False
    raw["agent_b"]["default_params"] = {
        "width": 1024, "height": 1024, "steps": 30, "guidance": 7.0,
        "cfg_truncation": 0.6, "max_sequence_length": 512, "seed": -1,
    }
    raw["agent_b"]["model_hints"] = (
        "## Z-Image Model Tips\n"
        "- Recommended params: steps=20-40, guidance=5-8, cfg_truncation=0.5-0.7\n"
        "- Prompt style: use 50-150 word detailed visual descriptions. "
        "Describe materials, lighting, atmosphere, composition.\n"
        "- Known weaknesses: complex hands, small faces, text rendering, extreme aspect ratios\n"
        "- Strengths: architectural details, landscapes, portraits, mood/lighting\n"
        "- Always include negative: 'blurry, distorted, low quality, extra limbs, fused fingers, watermark'\n"
        "- For faces: ensure face fills >15% of image; include 'detailed facial features, sharp eyes'"
    )

    config = AppConfig(**raw)
    VerboseLog.enable()  # Full transparency in walkthrough
    logging.info(f"Agent A: {config.agent_a.model} @ {config.agent_a.api_base}")
    logging.info(f"Agent B: MCP stdio (keep_alive={config.agent_b.mcp_keep_alive})")
    logging.info(f"Agent C: {config.agent_c.model} @ {config.agent_c.api_base}")
    logging.info(f"Max iterations: {config.loop.max_iterations}")

    # ── Providers ──────────────────────────────────────────────────────────
    logging.info("Creating providers...")
    factory = ProviderFactory()
    provider_a = factory.create_agent_a(config.agent_a)
    provider_c = factory.create_agent_c(config.agent_c)

    # ── Tools ──────────────────────────────────────────────────────────────
    outdir = Path(__file__).parent.parent / "temp" / "walkthrough"
    outdir.mkdir(parents=True, exist_ok=True)

    gen_tool = GenerateImageTool(config.agent_b, output_dir=str(outdir))
    inspect_tool = InspectImageTool(vision_provider=provider_c)
    compare_tool = CompareImagesTool(vision_provider=provider_c)

    registry = ToolRegistry()
    registry.register(gen_tool)
    registry.register(inspect_tool)
    registry.register(compare_tool)
    logging.info(f"Tools: generate_image, inspect_image, compare_images")

    # ── Session ────────────────────────────────────────────────────────────
    session_mgr = SessionManager()
    session = session_mgr.create(
        user_request=(
            "A mysterious gothic cathedral at twilight, illuminated by "
            "candelabras and stained glass, with a lone figure in a red "
            "cloak standing in the entrance"
        ),
        max_iterations=config.loop.max_iterations,
    )
    logging.info(f"Session: {session.id[:16]}...")

    # ── Agent A + Loop ────────────────────────────────────────────────────
    agent_a = AgentA(provider=provider_a, tool_registry=registry, session=session)
    assembler = ContextAssembler(agent_b_config=config.agent_b)
    event_bus = EventBus()
    interrupt_handler = InterruptHandler()

    loop = InnerLoop(
        session=session,
        agent_a=agent_a,
        tool_registry=registry,
        session_manager=session_mgr,
        interrupt_handler=interrupt_handler,
        assembler=assembler,
        event_bus=event_bus,
        config=config.loop,
    )

    # ── Run ────────────────────────────────────────────────────────────────
    logging.info("=" * 60)
    logging.info(f"STARTING LOOP: \"{session.user_request[:80]}...\"")
    logging.info("=" * 60)

    try:
        result = await loop.run(
            initial_prompt=session.user_request,
            step_limit=2,  # max 2 iterations for walkthrough
        )
        logging.info(f"Loop result: {result.terminated_reason}, {result.iterations_completed} iters")
    except Exception as e:
        logging.error(f"Loop crashed: {e}", exc_info=True)
    finally:
        await gen_tool.close()

    total_time = time.monotonic() - t_start

    # ── Report ─────────────────────────────────────────────────────────────
    lines = []
    lines.append("# DrawAgent Full Pipeline Walkthrough\n\n")
    lines.append(f"> **Started**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    lines.append(f"> **Duration**: {total_time:.0f}s\n\n")
    lines.append(f"**User Prompt**: {session.user_request}\n\n")

    lines.append("## Pipeline Configuration\n\n")
    lines.append("| Component | Config |\n|---|---|\n")
    lines.append(f"| Agent A (LLM) | `{config.agent_a.model}` @ `{config.agent_a.api_base}` |\n")
    lines.append(f"| Agent B (Image) | Z-Image MCP stdio, `keep_alive=False` |\n")
    lines.append(f"| Agent C (Vision) | `{config.agent_c.model}` @ `{config.agent_c.api_base}` |\n")
    lines.append(f"| Gen params | `{json.dumps(config.agent_b.default_params)}` |\n")
    lines.append(f"| Max iters | `{config.loop.max_iterations}` |\n\n")

    lines.append("## Full Execution Log\n\n```\n")
    for line_text in LOG_LINES:
        lines.append(line_text + "\n")
    lines.append("```\n\n")

    lines.append("## Iteration Details\n\n")
    for it in session.iterations:
        lines.append(f"### Iteration {it.number}\n\n")
        lines.append(f"- **Prompt**: `{it.prompt[:200]}`...\n")
        lines.append(f"- **Images**: {len(it.images)}\n")
        for i, img in enumerate(it.images):
            img_path = Path(img.path) if img.path else None
            if img_path and img_path.exists():
                rel = img_path.relative_to(Path(__file__).parent.parent)
                lines.append(f"\n![Iteration {it.number} - Image {i+1}]({rel})\n\n")
                lines.append(f"- Path: `{rel}`\n")
                lines.append(f"- Seed: `{img.seed}`\n")
                lines.append(f"- Resolution: `{img.width}x{img.height}`\n")
        if it.inspections:
            lines.append(f"\n**Inspections**:\n")
            for insp in it.inspections:
                lines.append(f"- Score: `{insp.get('score', '?')}` / Passed: `{insp.get('passed', '?')}`\n")
                lines.append(f"- Feedback: _{insp.get('feedback', '')}_\n")
        if it.decision:
            lines.append(f"\n**Decision**: {it.decision.action} (passed={it.decision.passed})\n")
            lines.append(f"- _{it.decision.reasoning}_\n")
        lines.append("\n---\n\n")

    report_path = outdir / "WALKTHROUGH.md"
    report_path.write_text("".join(lines), encoding="utf-8")
    print(f"\nReport: {report_path}")
    print(f"Images: {list(outdir.glob('*.png'))}")
    print("DONE")


if __name__ == "__main__":
    asyncio.run(main())
