"""
Real MCP integration test — no mocks, full pipeline.

Reads MCP config from file (MCP_TEST_CONFIG env var or default paths),
loads generation params from a preset file, and generates real images
through the MCP server to verify the full pipeline works.

Requires:
    - Z-Image MCP server accessible (either via HTTP or stdio)
    - For stdio: conda env 'qwen-image' with torch + zimage
    - Model files at default or configured path

Test matrix:
    1. stdio mode: MCPProvider spawns subprocess, full JSON-RPC handshake
    2. mcp_keep_alive=False: MCP process killed after generation
    3. Batch generation: multiple images in one call
    4. gen_params preset: loaded from YAML and merged with defaults
    5. Different prompt + params produce valid output images

Skip conditions:
    - MCP_TEST_CONFIG env not set and no default config found
    - MCP server fails to start (e.g., wrong conda env)
"""

import os
import sys
from pathlib import Path

import pytest
import yaml
from PIL import Image

from drawagent.config.schema import AgentBConfig
from drawagent.tools.base import ToolContext
from drawagent.tools.generate_image import GenerateImageTool


# ── Config resolution ──────────────────────────────────────────────────────
def _find_config():
    """Resolve MCP test config path, or return None → skip."""
    env_path = os.environ.get("MCP_TEST_CONFIG")
    if env_path and Path(env_path).exists():
        return Path(env_path)

    candidates = [
        Path("config.example.yaml"),
        Path("config.local.yaml"),
        Path.home() / ".drawagent" / "config.yaml",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def _find_gen_preset():
    """Resolve gen params preset, or return None."""
    candidates = [
        Path("gen_presets/fast-preview.yaml"),
        Path("gen_presets/seed-sweep.yaml"),
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def _load_agent_b_config(config_path: Path) -> AgentBConfig:
    """Load just the agent_b section from a config YAML."""
    with open(config_path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    agent_b_data = data.get("agent_b", {})
    return AgentBConfig(**agent_b_data)


def _load_gen_params(preset_path: Path) -> dict:
    """Load generation params from a preset YAML."""
    with open(preset_path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return {k: v for k, v in data.items() if not k.startswith("_")}


# ── Skip marker ────────────────────────────────────────────────────────────
_config_path = _find_config()



# ── Fixtures ───────────────────────────────────────────────────────────────
def _require_config():
    """Fixture-like: skip if no config found."""
    if _config_path is None:
        pytest.skip(
            "No MCP config found. Set MCP_TEST_CONFIG env var "
            "or create config.example.yaml"
        )


@pytest.fixture(scope="module")
def agent_b_config():
    """Load Agent B config from the test config file."""
    _require_config()
    return _load_agent_b_config(_config_path)


@pytest.fixture(scope="module")
def gen_params():
    """Load generation params from a preset YAML."""
    preset = _find_gen_preset()
    if preset:
        return _load_gen_params(preset)
    return {}


# ── Helper: attempt connection once, surface env issues clearly ────────────
async def _try_connect_once(tool: GenerateImageTool) -> str | None:
    """Try to connect to the MCP server and return error string or None."""
    try:
        await tool._ensure_mcp_connected()
        return None  # success
    except Exception as e:
        msg = str(e)
        if "closed connection" in msg.lower() or "Connection refused" in msg.lower():
            return (
                f"MCP server failed to start.\n"
                f"  Command: {tool.config.mcp_command}\n"
                f"  Error: {msg}\n"
                f"  Hint: Ensure the Python environment has torch + zimage installed.\n"
                f"        For conda: conda activate qwen-image first, "
                f"        or set mcp_command to use the conda env's python executable.\n"
                f"        You can also use a custom config via: MCP_TEST_CONFIG=path/to/config.yaml"
            )
        return f"MCP connection error: {msg}"


# ── Tests ──────────────────────────────────────────────────────────────────
@pytest.mark.integration
class TestMCPRealPipeline:
    """Real MCP pipeline — actual subprocess, actual images."""

    @pytest.mark.asyncio
    async def test_stdio_single_image(self, tmp_path, agent_b_config, gen_params):
        """stdio mode: single image generation → valid PNG output."""
        import asyncio

        outdir = tmp_path / "outputs"
        outdir.mkdir()

        tool = GenerateImageTool(agent_b_config, output_dir=str(outdir))

        # ── Connection pre-check (gives clear error if env is wrong) ──
        connect_err = await _try_connect_once(tool)
        if connect_err:
            pytest.skip(connect_err)

        merged_params = dict(gen_params)
        merged_params["prompt"] = "a single red apple on white background"
        merged_params["num_images"] = 1

        try:
            result = await tool.execute(merged_params, ToolContext(
                session_id="mcp-int-1", agent="test",
                message_id="msg-1", tool_call_id="tc-1",
            ))
        finally:
            await tool.close()

        assert result.error is None, f"Generation failed: {result.error}"
        assert result.metadata is not None
        images = result.metadata["images"]
        assert len(images) == 1
        img_path = Path(images[0]["path"])
        assert img_path.exists(), f"Output file missing: {img_path}"
        assert img_path.stat().st_size > 100, f"File too small: {img_path.stat().st_size} bytes"

        img = Image.open(img_path)
        assert img.size[0] > 0 and img.size[1] > 0
        assert img_path.suffix.lower() == ".png"

    @pytest.mark.asyncio
    async def test_stdio_batch_images(self, tmp_path, agent_b_config, gen_params):
        """stdio mode: 2 images in one call with different seeds."""
        outdir = tmp_path / "outputs"
        outdir.mkdir()

        tool = GenerateImageTool(agent_b_config, output_dir=str(outdir))

        merged_params = dict(gen_params)
        merged_params["prompt"] = "a blue square"
        merged_params["num_images"] = 2

        try:
            result = await tool.execute(merged_params, ToolContext(
                session_id="mcp-int-2", agent="test",
                message_id="msg-2", tool_call_id="tc-2",
            ))
        finally:
            await tool.close()

        assert result.error is None, f"Batch generation failed: {result.error}"
        images = result.metadata["images"]
        assert len(images) == 2
        for img_info in images:
            assert "error" not in img_info, f"Image failed: {img_info}"
            p = Path(img_info["path"])
            assert p.exists(), f"Batch image missing: {p}"

        seeds = result.metadata["seeds"]
        assert len(seeds) == 2
        assert seeds[0] != seeds[1], "Batch seeds should differ"

    @pytest.mark.asyncio
    async def test_mcp_keep_alive_stdio(self, tmp_path):
        """mcp_keep_alive=False: MCP process killed after generation."""
        # Load config and force mcp_keep_alive=False
        agent_b_data = _load_agent_b_config(_config_path)
        # Force mcp_keep_alive to False for this test
        kwargs = agent_b_data.model_dump()
        kwargs["mcp_keep_alive"] = False
        cfg = AgentBConfig(**kwargs)

        outdir = tmp_path / "outputs"
        outdir.mkdir()
        tool = GenerateImageTool(cfg, output_dir=str(outdir))

        try:
            result = await tool.execute(
                {"prompt": "a green circle", "num_images": 1},
                ToolContext(session_id="mcp-ka", agent="test",
                            message_id="m1", tool_call_id="tc1"),
            )
        finally:
            await tool.close()

        assert result.error is None
        # After generation with keep_alive=False, _mcp_provider should be None
        assert tool._mcp_provider is None, "MCP should be closed after generation"

    @pytest.mark.asyncio
    async def test_gen_params_preset_applied(self, tmp_path, agent_b_config):
        """Gen params from YAML preset are applied to the generation request."""
        preset = _find_gen_preset()
        if preset is None:
            pytest.skip("No gen params preset found")

        params = _load_gen_params(preset)
        outdir = tmp_path / "outputs"
        outdir.mkdir()
        tool = GenerateImageTool(agent_b_config, output_dir=str(outdir))

        merged = dict(params)
        merged["prompt"] = "test preset application"
        merged["num_images"] = 1

        try:
            result = await tool.execute(merged, ToolContext(
                session_id="mcp-preset", agent="test",
                message_id="mp", tool_call_id="tp",
            ))
        finally:
            await tool.close()

        assert result.error is None
        img_path = Path(result.metadata["images"][0]["path"])
        img = Image.open(img_path)
        # Verify dimensions match the preset
        expected_w = params.get("width", 1024)
        expected_h = params.get("height", 1024)
        assert img.size == (expected_w, expected_h), \
            f"Expected {expected_w}x{expected_h}, got {img.size}"

    @pytest.mark.asyncio
    async def test_mcp_output_is_valid_png(self, tmp_path, agent_b_config):
        """Generated image passes PIL verification (not truncated/corrupt)."""
        outdir = tmp_path / "outputs"
        outdir.mkdir()
        tool = GenerateImageTool(agent_b_config, output_dir=str(outdir))

        try:
            result = await tool.execute(
                {"prompt": "verification test image", "num_images": 1},
                ToolContext(session_id="mcp-verify", agent="test",
                            message_id="mv", tool_call_id="tv"),
            )
        finally:
            await tool.close()

        assert result.error is None
        img_path = Path(result.metadata["images"][0]["path"])
        img = Image.open(img_path)
        assert img.mode in ("RGB", "RGBA"), f"Unexpected mode: {img.mode}"
        img.verify()  # PIL integrity check — raises if corrupt


# ── HTTP mode tests (if config uses type: http) ────────────────────────────
@pytest.mark.integration
class TestMCPRealHTTP:
    """Real MCP HTTP pipeline — only runs if config specifies HTTP MCP."""

    @pytest.mark.asyncio
    async def test_http_generate(self, tmp_path, agent_b_config):
        """Generate via HTTP MCP endpoint."""
        if agent_b_config.type != "http":
            pytest.skip("Agent B config type is not 'http'")

        outdir = tmp_path / "outputs"
        outdir.mkdir()
        tool = GenerateImageTool(agent_b_config, output_dir=str(outdir))

        try:
            result = await tool.execute(
                {"prompt": "HTTP MCP test: gradient background", "num_images": 1},
                ToolContext(session_id="mcp-http", agent="test",
                            message_id="mh", tool_call_id="th"),
            )
        finally:
            await tool.close()

        assert result.error is None, f"HTTP generation failed: {result.error}"
        img_path = Path(result.metadata["images"][0]["path"])
        assert img_path.exists()
