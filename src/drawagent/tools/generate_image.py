from __future__ import annotations

import base64
import json
import time
from io import BytesIO
from pathlib import Path

import httpx
from PIL import Image

from drawagent.config.schema import AgentBConfig
from drawagent.core.errors import ImageGenerationError
from drawagent.tools.base import BaseTool, ToolContext, ToolResult


class GenerateImageTool(BaseTool):
    """Agent B wrapper — calls image generation API.

    Supports two backends configured via AgentBConfig.type:
    - http: Direct HTTP API POST with JSON body
    - mcp: Model Context Protocol server (stdio or remote)
    """

    name = "generate_image"
    description = (
        "Generate images from a text prompt. Supports multiple images per call "
        "with different seeds. Returns file paths to generated images."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "The image generation prompt (positive prompt, detailed)",
            },
            "negative_prompt": {
                "type": "string",
                "description": "Negative prompt — what to avoid in the image",
            },
            "num_images": {
                "type": "integer",
                "description": "Number of images to generate (1-4)",
                "default": 2,
            },
            "seed": {
                "type": "integer",
                "description": "Random seed (-1 for random)",
                "default": -1,
            },
            "width": {
                "type": "integer",
                "description": "Image width in pixels",
                "default": 1024,
            },
            "height": {
                "type": "integer",
                "description": "Image height in pixels",
                "default": 1024,
            },
            "steps": {
                "type": "integer",
                "description": "Diffusion steps (quality vs speed)",
                "default": 8,
            },
            "guidance": {
                "type": "number",
                "description": "CFG guidance scale",
                "default": 3.5,
            },
        },
        "required": ["prompt"],
    }

    def __init__(self, config: AgentBConfig, output_dir: str = "./outputs"):
        self.config = config
        self.output_dir = Path(output_dir).resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._client: httpx.AsyncClient | None = None
        self._mcp_provider = None
        if config.type == "mcp":
            from drawagent.providers.mcp_provider import MCPProvider
            self._mcp_provider = MCPProvider(config)

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(300.0))
        return self._client

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()

    async def _ensure_mcp_connected(self) -> None:
        if self._mcp_provider is not None and not self._mcp_provider._initialized:
            await self._mcp_provider.connect()

    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        prompt = args["prompt"]
        num_images = args.get("num_images", 2)
        num_images = max(1, min(num_images, 4))

        params = dict(self.config.default_params)
        params.update({
            "width": args.get("width", params.get("width", 1024)),
            "height": args.get("height", params.get("height", 1024)),
            "steps": args.get("steps", params.get("steps", 8)),
            "guidance": args.get("guidance", params.get("guidance", 3.5)),
        })

        seeds = []
        base_seed = args.get("seed", -1)
        if base_seed < 0:
            import random
            base_seed = random.randint(0, 2**31 - 1)

        images_info = []
        for i in range(num_images):
            seed = base_seed + i * 1000
            seeds.append(seed)
            params["seed"] = seed

            try:
                image_path = await self._generate_single(
                    prompt=prompt,
                    negative_prompt=args.get("negative_prompt", ""),
                    params=params,
                    index=i + 1,
                )
                images_info.append({
                    "path": str(image_path),
                    "seed": seed,
                    "width": params["width"],
                    "height": params["height"],
                })
            except Exception as exc:
                images_info.append({
                    "error": str(exc),
                    "seed": seed,
                })

        success_count = sum(1 for img in images_info if "error" not in img)
        if success_count == 0:
            return ToolResult(
                tool_call_id=ctx.tool_call_id or "",
                name=self.name,
                output="",
                error=f"All {num_images} image generation attempts failed: {images_info}",
            )

        output_parts = [f"Generated {success_count}/{num_images} images successfully."]
        for i, info in enumerate(images_info, 1):
            if "error" in info:
                output_parts.append(f"  Image {i}: FAILED — {info['error']}")
            else:
                output_parts.append(
                    f"  Image {i}: {info['path']} (seed={info['seed']}, "
                    f"{info['width']}x{info['height']})"
                )

        return ToolResult(
            tool_call_id=ctx.tool_call_id or "",
            name=self.name,
            output="\n".join(output_parts),
            metadata={
                "images": images_info,
                "prompt": prompt,
                "seeds": seeds,
            },
        )

    async def _generate_single(
        self,
        prompt: str,
        negative_prompt: str,
        params: dict,
        index: int,
    ) -> Path:
        if self.config.type == "mcp":
            return await self._generate_mcp(prompt, negative_prompt, params, index)
        return await self._generate_http(prompt, negative_prompt, params, index)

    async def _generate_mcp(
        self,
        prompt: str,
        negative_prompt: str,
        params: dict,
        index: int,
    ) -> Path:
        await self._ensure_mcp_connected()
        assert self._mcp_provider is not None
        result = await self._mcp_provider.generate(prompt, negative_prompt, **params)

        if isinstance(result, dict):
            image_data = None
            content = result.get("content", [])
            if isinstance(content, list) and content:
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "image":
                        b64 = item.get("data", "")
                        if b64:
                            image_data = base64.b64decode(b64)
                            break
                    elif isinstance(item, dict) and item.get("type") == "text":
                        text = item.get("text", "")
                        if text.startswith("data:image"):
                            _, b64 = text.split(",", 1)
                            image_data = base64.b64decode(b64)
                            break
            if image_data is None:
                raise ImageGenerationError(f"MCP result has no image data: {json.dumps(result, default=str)[:500]}")

            timestamp = int(time.time() * 1000)
            filename = f"gen_mcp_{timestamp}_{index:02d}_{params.get('seed', -1)}.png"
            output_path = self.output_dir / filename
            image = Image.open(BytesIO(image_data))
            image.save(output_path, "PNG")
            return output_path

        raise ImageGenerationError(f"Unexpected MCP result format: {type(result)}")

    async def _generate_http(
        self,
        prompt: str,
        negative_prompt: str,
        params: dict,
        index: int,
    ) -> Path:
        api_url = f"{self.config.api_base.rstrip('/')}{self.config.endpoint}"

        body = {
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            **params,
        }

        client = await self._ensure_client()
        try:
            resp = await client.post(api_url, json=body)
        except httpx.ConnectError:
            raise ImageGenerationError(
                f"无法连接到图像生成服务器 (Agent B) — 请确认服务是否已启动: {api_url}\n"
                f"在系统设置中检查 Agent B 的 API Base URL 和 Endpoint"
            )
        except httpx.TimeoutException:
            raise ImageGenerationError(
                f"图像生成请求超时 — 服务器 {api_url} 响应过慢"
            )
        if resp.status_code != 200:
            raise ImageGenerationError(
                f"Image generation API returned {resp.status_code}: {resp.text[:500]}"
            )

        content_type = resp.headers.get("content-type", "")
        if "image/" in content_type:
            image_data = resp.content
        elif "application/json" in content_type:
            data = resp.json()
            if "base64" in data:
                image_data = base64.b64decode(data["base64"])
            elif "url" in data:
                dl_resp = await client.get(data["url"])
                image_data = dl_resp.content
            elif "images" in data:
                image_data = base64.b64decode(data["images"][0])
            else:
                raise ImageGenerationError(
                    f"Unexpected JSON response format: {list(data.keys())}"
                )
        else:
            image_data = resp.content

        timestamp = int(time.time() * 1000)
        filename = f"gen_{timestamp}_{index:02d}_{params['seed']}.png"
        output_path = self.output_dir / filename

        image = Image.open(BytesIO(image_data))
        image.save(output_path, "PNG")

        return output_path

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        if self._mcp_provider is not None:
            await self._mcp_provider.close()


def ctx_message_id(ctx: ToolContext) -> str:
    return (ctx.message_id or ctx.session_id)[:8]
