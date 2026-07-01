"""
Debug: Multi-image vision test — shorter prompts, raw response inspection.
"""

import asyncio
import base64
import json
import sys
from pathlib import Path

import httpx

# Fix GBK encoding on Windows
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OLLAMA_BASE = "http://localhost:11434/v1"
MODEL = "qwen3.5:9b"

PROJECT_ROOT = Path(__file__).parent.parent

CROSS = [
    PROJECT_ROOT / "outputs" / "mcp_1782751361370_00_276294668.png",  # apple
    PROJECT_ROOT / "outputs" / "mcp_1782835032580_00_881141255.png",  # cathedral
]

SAME = [
    PROJECT_ROOT / "outputs" / "gen_mcp_1782835501000_01_1440181630.png",
    PROJECT_ROOT / "outputs" / "gen_mcp_1782835543164_02_1440182630.png",
]

SHARP = PROJECT_ROOT.parent / "Z-Image" / "outputs" / "2026-01-17" / "ca67520a2e2f42138276b05a5986f495" / "中世纪少女中世纪服饰站在桌子旁正在往面包_20260117_012651_b03b1e83_00.png"


async def test(client, pair, label, question):
    b1 = base64.b64encode(pair[0].read_bytes()).decode()
    b2 = base64.b64encode(pair[1].read_bytes()).decode()

    content = [
        {"type": "text", "text": question},
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b1}"}},
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b2}"}},
    ]

    print(f"\n{'='*70}")
    print(f"  [{label}]")
    print(f"  Q: {question}")
    print(f"  Content items: {len(content)}")

    try:
        resp = await client.post(
            f"{OLLAMA_BASE}/chat/completions",
            json={
                "model": MODEL,
                "messages": [{"role": "user", "content": content}],
                "max_tokens": 512,
                "temperature": 0.3,
            },
            timeout=httpx.Timeout(120.0),
        )
        raw = resp.json()
        choice = raw.get("choices", [{}])[0]
        msg = choice.get("message", {})
        answer = msg.get("content", "")

        finish = choice.get("finish_reason", "?")
        print(f"  Finish: {finish}")
        print(f"  Answer length: {len(answer)} chars")
        print(f"  Answer: {answer[:600]}")
    except Exception as e:
        print(f"  ERROR: {e}")


async def test_single(client, path, label, question):
    b64 = base64.b64encode(path.read_bytes()).decode()
    content = [
        {"type": "text", "text": question},
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
    ]

    print(f"\n--- [{label}] single image: {path.name}")
    try:
        resp = await client.post(
            f"{OLLAMA_BASE}/chat/completions",
            json={
                "model": MODEL,
                "messages": [{"role": "user", "content": content}],
                "max_tokens": 256,
                "temperature": 0.3,
            },
            timeout=httpx.Timeout(60.0),
        )
        msg = resp.json()["choices"][0]["message"]
        answer = msg.get("content", "")
        print(f"  Answer ({len(answer)} chars): {answer[:300]}")
    except Exception as e:
        print(f"  ERROR: {e}")


async def main():
    async with httpx.AsyncClient() as client:

        # Verify model available
        print(f"Model: {MODEL}")

        # Test 1: Single image — verify it works at all
        await test_single(client, CROSS[0], "SINGLE", "What do you see? Describe briefly.")

        # Test 2: Two images, very short question — does multi-image work?
        await test(client, CROSS, "MULTI SHORT",
                   "Image 1 then Image 2. What is each image? One word each.")

        # Test 3: Two images, order check
        await test(client, CROSS, "MULTI ORDER",
                   "Image 1 is displayed first, Image 2 second. Tell me: what subject is in Image 1? What subject is in Image 2?")

        # Test 4: Two images, comparison
        await test(client, CROSS, "MULTI COMPARE",
                   "Compare Image 1 and Image 2. Which has more visual complexity? Use 'Image 1' and 'Image 2' labels.")

        # Test 5: Two same-subject images
        await test(client, SAME, "SAME-SUBJECT",
                   "These are two cathedral images. Compare their composition: how does Image 1 differ from Image 2?")

        # Test 6: Sharpness comparison
        if SHARP.exists():
            await test(client, [SHARP, CROSS[1]], "SHARPNESS",
                       "Which image is sharper: Image 1 or Image 2? Answer with 'Image 1' or 'Image 2' first.")

            # Same but swapped
            await test(client, [CROSS[1], SHARP], "SHARPNESS SWAPPED",
                       "Which is sharper, Image 1 or Image 2? Be specific about each.")

        # Test 7: Element addition question
        await test(client, SAME, "ELEMENTS",
                   "What architectural elements appear in Image 2 that are absent from Image 1?")

        # Test 8: Quality comparison
        await test(client, SAME, "QUALITY",
                   "Between Image 1 and Image 2, which has better visual quality? Check sharpness, lighting, composition.")

        print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
