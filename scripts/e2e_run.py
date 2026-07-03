"""End-to-end pipeline run with full verbose logging."""
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
LOG_PATH = LOG_DIR / f"run_{TIMESTAMP}.log"

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

class Tee:
    def __init__(self, file1, file2):
        self.file1 = file1
        self.file2 = file2
    def write(self, s):
        self.file1.write(s)
        self.file1.flush()
        self.file2.write(s)
        self.file2.flush()
    def flush(self):
        self.file1.flush()
        self.file2.flush()

sys.stdout = Tee(_original_stdout, log_file)
sys.stderr = Tee(_original_stderr, log_file)

print(f"Log file: {LOG_PATH}")
print(f"Started: {datetime.now()}")
print(f"="*70)

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

PROMPT = (
    "中国少女，身材非常好，戴眼镜，马尾/短发/盘发，"
    "T恤衫/吊带衫，牛仔裤/喇叭裤/热裤，"
    "教室里坐着，看着镜头，从下往上仰视拍摄。水磨石地板，防盗窗，窗外阳光明媚，光影斑驳"
    "真实摄影"
)

async def main():
    VerboseLog.enable()
    logging.basicConfig(level=logging.DEBUG, stream=sys.stdout, format='%(asctime)s [%(name)s] %(message)s')

    print(f"\nPrompt: {PROMPT}\n")

    # Config
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
    config = AppConfig(**raw)

    # Providers
    factory = ProviderFactory()
    provider_a = factory.create_agent_a(config.agent_a)
    provider_c = factory.create_agent_c(config.agent_c)

    # Tools
    outdir = Path(__file__).parent.parent / "outputs"
    gen_tool = GenerateImageTool(config.agent_b, output_dir=str(outdir))
    inspect_tool = InspectImageTool(vision_provider=provider_c)
    compare_tool = CompareImagesTool(vision_provider=provider_c)
    registry = ToolRegistry()
    registry.register(gen_tool)
    registry.register(inspect_tool)
    registry.register(compare_tool)

    # Session
    session_mgr = SessionManager()
    session = session_mgr.create(user_request=PROMPT, max_iterations=3)

    # Agent A + Loop
    agent_a = AgentA(provider=provider_a, tool_registry=registry, session=session)
    assembler = ContextAssembler(agent_b_config=config.agent_b)
    event_bus = EventBus()
    loop = InnerLoop(
        session=session, agent_a=agent_a, tool_registry=registry,
        session_manager=session_mgr, interrupt_handler=InterruptHandler(),
        assembler=assembler, event_bus=event_bus, config=config.loop,
    )

    t0 = time.monotonic()
    try:
        result = await loop.run(initial_prompt=PROMPT)
    finally:
        await gen_tool.close()

    elapsed = time.monotonic() - t0
    print(f"\n{'='*70}")
    print(f"RESULT: {result.terminated_reason}")
    print(f"Iterations: {result.iterations_completed}")
    print(f"Time: {elapsed:.0f}s")
    print(f"Log: {LOG_PATH}")
    for img in result.final_images:
        print(f"  Image: {img.path}")


asyncio.run(main())
log_file.close()
