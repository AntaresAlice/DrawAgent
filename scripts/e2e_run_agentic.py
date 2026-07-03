"""End-to-end agentic pipeline run with full verbose logging."""
import asyncio, sys, time, logging
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent))

import yaml

# ── Redirect ALL output to a log file ────────────────────────────────────────
LOG_DIR = Path(__file__).parent.parent / "temp" / "runs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
LOG_PATH = LOG_DIR / f"run_agentic_{TIMESTAMP}.log"

class Tee:
    def __init__(self, *files):
        self.files = files
    def write(self, s):
        for f in self.files:
            f.write(s)
            f.flush()
    def flush(self):
        for f in self.files:
            f.flush()

log_file = open(LOG_PATH, "w", encoding="utf-8")
_original_stdout = sys.stdout
_original_stderr = sys.stderr
sys.stdout = Tee(_original_stdout, log_file)
sys.stderr = Tee(_original_stderr, log_file)

print(f"Log file: {LOG_PATH}")
print(f"Started: {datetime.now()}")
print(f"=" * 70)

from drawagent.agents.agent_a import AgentA
from drawagent.config.schema import AppConfig
from drawagent.core.events import EventBus
from drawagent.core.verbose_log import VerboseLog
from drawagent.models.agentic_session import AgenticSession, InputQueue
from drawagent.orchestrator.agentic_loop import AgenticLoop
from drawagent.orchestrator.session import SessionManager
from drawagent.providers.factory import ProviderFactory
from drawagent.tools.base import ToolRegistry
from drawagent.tools.generate_image import GenerateImageTool
from drawagent.tools.inspect_image import InspectImageTool
from drawagent.tools.compare_images import CompareImagesTool
from drawagent.tools.finalize import FinalizeTool

PROMPT = (
    "中国少女，身材非常好，戴眼镜，马尾/短发/盘发，"
    "T恤衫/吊带衫，牛仔裤/喇叭裤/热裤，"
    "教室里坐着，看着镜头，从下往上仰视拍摄。水磨石地板，防盗窗，窗外阳光明媚，光影斑驳"
    "真实摄影"
)


async def main():
    VerboseLog.enable()
    logging.basicConfig(level=logging.INFO, stream=sys.stdout,
                        format='%(asctime)s [%(name)s] %(message)s')

    print(f"\n[MODE] AGENTIC (LLM-driven loop)")
    print(f"Prompt: {PROMPT}\n")

    # ── Config ────────────────────────────────────────────────────────────────
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
        "num_images": 1,  # Single image per call for speed
    }
    raw["agent_b"]["model_hints"] = (
        "## Z-Image Model Tips\n"
        "- Steps: 20-40 for quality, 8-15 for speed\n"
        "- Guidance: 5.0-8.0 (higher = stricter prompt following)\n"
        "- CFG truncation: 0.5-0.7 (lower = less over-saturation)\n"
        "- Resolution: portrait 960x1280 for full-body, square 1024x1024 for centered\n"
        "- Prompt: 50-150 words, same language as user, detailed visual description\n"
        "- Negative prompt base: '平庸、模糊、扭曲、肥胖、低像素、水印'\n"
        "  Add context: 'extra limbs, fused fingers' for portraits\n"
        "- Strengths: architecture, landscapes, portraits, lighting/mood\n"
        "- Weaknesses: complex hands, small faces, text in images\n"
        "- num_images: 1-2 for iteration, 3-4 for initial exploration"
    )
    # Agentic config
    if "loop" not in raw:
        raw["loop"] = {}
    raw["loop"]["engine"] = "agentic"
    raw["loop"]["agentic"] = {
        "max_tool_rounds": 8,
        "max_agentic_rounds": 5,
        "max_finalize_rejections": 3,
        "context_window": 65536,
        "output_buffer": 8192,
        "compaction": {"enabled": False},
        "learning": {"enabled": False},
    }

    config = AppConfig(**raw)

    # ── Providers ─────────────────────────────────────────────────────────────
    factory = ProviderFactory()
    provider_a = factory.create_agent_a(config.agent_a)
    provider_c = factory.create_agent_c(config.agent_c)

    # ── Tools ─────────────────────────────────────────────────────────────────
    outdir = Path(__file__).parent.parent / "outputs"
    gen_tool = GenerateImageTool(config.agent_b, output_dir=str(outdir))
    inspect_tool = InspectImageTool(vision_provider=provider_c)
    compare_tool = CompareImagesTool(vision_provider=provider_c)
    finalize_tool = FinalizeTool()
    registry = ToolRegistry()
    registry.register(gen_tool)
    registry.register(inspect_tool)
    registry.register(compare_tool)
    registry.register(finalize_tool)

    # ── Agentic Session ───────────────────────────────────────────────────────
    session_id = f"ses_agentic_{TIMESTAMP}"
    agentic_session = AgenticSession(
        id=session_id,
        user_request=PROMPT,
    )

    # ── Agent A ───────────────────────────────────────────────────────────────
    # AgentA needs a classic Session for provider access (minimal stub)
    from drawagent.core.types import Session
    stub_session = Session(id=session_id, user_request=PROMPT, max_iterations=3)
    agent_a = AgentA(provider=provider_a, tool_registry=registry, session=stub_session)

    # ── Agentic Loop ──────────────────────────────────────────────────────────
    loop_config = config.loop.model_dump()
    loop_config["agent_a"] = config.agent_a.model_dump()
    loop_config["agent_b"] = config.agent_b
    loop_config["verbose"] = True

    session_mgr = SessionManager()
    event_bus = EventBus()

    loop = AgenticLoop(
        session=agentic_session,
        agent_a=agent_a,
        registry=registry,
        config=loop_config,
        event_bus=event_bus,
        session_manager=session_mgr,
        verbose=True,
    )
    loop.set_queue(InputQueue(session_id, session_mgr))

    # ── Run ───────────────────────────────────────────────────────────────────
    t0 = time.monotonic()
    try:
        result = await loop.run(force_prompt=PROMPT)
    except Exception as exc:
        print(f"\n[ERROR] {type(exc).__name__}: {exc}")
        import traceback
        traceback.print_exc()
    finally:
        await gen_tool.close()

    elapsed = time.monotonic() - t0
    print(f"\n{'=' * 70}")
    print(f"RESULT: {len(result.turns)} turns, {len(result.iterations)} iterations")
    print(f"Lessons: {len(result.learned_lessons)}")
    print(f"Time: {elapsed:.0f}s")
    print(f"Log: {LOG_PATH}")
    for i, turn in enumerate(result.turns):
        print(f"  Turn {i+1}: finish={turn.finish_reason}, "
              f"tools={[tc.tool_name for tc in turn.tool_calls]}, "
              f"text={len(turn.assistant_text or '')}ch")
    if result.errors:
        print(f"  Errors ({len(result.errors)}):")
        for e in result.errors:
            print(f"    - {e.get('type')}: {e.get('message', '')[:120]}")


asyncio.run(main())
log_file.close()
