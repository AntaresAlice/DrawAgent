import asyncio, json, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from drawagent.config.schema import AgentBConfig
from drawagent.tools.base import ToolContext
from drawagent.tools.generate_image import GenerateImageTool

async def main():
    cfg = AgentBConfig(
        type="mcp",
        mcp_command=[
            r"D:\SoftwareStation\Conda\envs\qwen-image\python.exe",
            r"D:\Code\Z-Image-MCP\mcp_server.py",
        ],
        mcp_tool_name="generate_image",
        mcp_keep_alive=True,
        default_params={"width": 512, "height": 512, "steps": 4, "guidance": 3.5, "seed": -1},
    )

    outdir = Path(__file__).parent / "outputs" / "mcp_integration_demo"
    outdir.mkdir(parents=True, exist_ok=True)

    tool = GenerateImageTool(cfg, output_dir=str(outdir))

    prompts = [
        ("a single red apple on white background", "red_apple"),
        ("a blue circle on gradient background", "blue_circle"),
        ("verification test: simple geometric shapes", "shapes"),
    ]

    results = []
    for prompt, tag in prompts:
        t0 = time.monotonic()
        print(f"\n{'='*60}")
        print(f"Prompt: {prompt}")
        result = await tool.execute(
            {"prompt": prompt, "num_images": 1},
            ToolContext(session_id=f"demo-{tag}", agent="test",
                        message_id="m1", tool_call_id="t1"),
        )
        elapsed = time.monotonic() - t0
        print(f"Elapsed: {elapsed:.1f}s")
        if result.error is None:
            img_path = result.metadata["images"][0]["path"]
            size = Path(img_path).stat().st_size
            print(f"  OK: {img_path} ({size} bytes)")
            results.append({"prompt": prompt, "path": img_path, "error": None, "elapsed": elapsed})
        else:
            print(f"  FAIL: {result.error}")
            results.append({"prompt": prompt, "path": None, "error": result.error, "elapsed": elapsed})

    await tool.close()

    # Write summary JSON
    summary_path = outdir / "results.json"
    summary_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nSummary: {summary_path}")

if __name__ == "__main__":
    asyncio.run(main())
