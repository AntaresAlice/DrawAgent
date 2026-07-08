from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

from drawagent.config.schema import AgentBConfig
from drawagent.core.errors import ImageGenerationError
from drawagent.core.verbose_log import VerboseLog

logger = logging.getLogger("drawagent.mcp")


class MCPProvider:
    """Model Context Protocol image generation provider.

    Supports both stdio (local subprocess) and HTTP (remote) MCP servers.
    Communicates via JSON-RPC 2.0 over stdio or HTTP.
    """

    def __init__(self, config: AgentBConfig):
        self.config = config
        self._process: subprocess.Popen | None = None
        self._http_client: httpx.AsyncClient | None = None
        self._tool_args_schema: dict | None = None
        self._initialized = False

    async def connect(self) -> None:
        """Initialize connection to MCP server and discover the generate tool."""
        if self.config.type == "mcp" and self.config.mcp_url:
            self._http_client = httpx.AsyncClient(timeout=httpx.Timeout(300.0))
            await self._http_initialize()
        elif self.config.type == "mcp" and self.config.mcp_command:
            await self._stdio_initialize()
        else:
            raise ImageGenerationError("MCP provider requires mcp_command or mcp_url in config")

    async def _stdio_initialize(self) -> None:
        cmd = self.config.mcp_command
        if not cmd:
            raise ImageGenerationError("mcp_command is required for stdio MCP")

        t0 = time.monotonic()
        logger.info("[MCP] spawning subprocess: %s", cmd)
        env = os.environ.copy()

        # Use subprocess.Popen (not asyncio.create_subprocess_exec) for reliable
        # Windows compatibility. stderr → DEVNULL to prevent pipe deadlock.
        env["PYTHONIOENCODING"] = "utf-8"
        self._process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=env,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
        logger.info("[MCP] subprocess spawned (pid=%s), elapsed=%.1fs",
                     self._process.pid, time.monotonic() - t0)

        try:
            logger.info("[MCP] sending initialize...")
            init_result = await self._send_json_rpc_stdio("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "DrawAgent", "version": "0.2.0"},
            })
            logger.info("[MCP] handshake OK: %s", init_result.get("serverInfo", init_result))

            tools_result = await self._send_json_rpc_stdio("tools/list", {})
            tools = tools_result.get("tools", [])
            logger.info("[MCP] tools discovered: %s", [t.get("name") for t in tools])

            tool = next((t for t in tools if t.get("name") == self.config.mcp_tool_name), None)
            if tool is None:
                names = [t.get("name") for t in tools]
                raise ImageGenerationError(
                    f"MCP tool '{self.config.mcp_tool_name}' not found. Available: {names}"
                )

            self._tool_args_schema = tool.get("inputSchema", {})
            self._initialized = True
            logger.info("[MCP] initialized successfully (elapsed=%.1fs)", time.monotonic() - t0)
        except Exception:
            if self._process:
                self._process.kill()
                self._process = None
            raise

    async def _http_initialize(self) -> None:
        if self._http_client is None:
            raise RuntimeError("HTTP client not initialized")
        resp = await self._http_client.post(
            self.config.mcp_url,
            json={"jsonrpc": "2.0", "method": "initialize", "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "DrawAgent", "version": "0.2.0"},
            }, "id": 1},
        )
        data = resp.json()
        logger.info("MCP HTTP initialized: %s", data.get("result", {}))

        resp2 = await self._http_client.post(
            self.config.mcp_url,
            json={"jsonrpc": "2.0", "method": "tools/list", "params": {}, "id": 2},
        )
        tools_data = resp2.json()
        tools = tools_data.get("result", {}).get("tools", [])

        for tool in tools:
            if tool.get("name") == self.config.mcp_tool_name:
                self._tool_args_schema = tool.get("inputSchema", {})
                break

        if self._tool_args_schema is None:
            available = [t.get("name") for t in tools]
            raise ImageGenerationError(
                f"MCP tool '{self.config.mcp_tool_name}' not found. Available: {available}"
            )
        self._initialized = True

    async def _send_json_rpc_stdio(self, method: str, params: dict) -> dict:
        if self._process is None or self._process.stdin is None or self._process.stdout is None:
            raise RuntimeError("MCP stdio process not running")

        request = json.dumps({
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": 1,
        })

        t_write = time.monotonic()
        loop = asyncio.get_running_loop()
        proc = self._process  # capture for thread safety
        await loop.run_in_executor(
            None,
            lambda: (proc.stdin.write(request + "\n"), proc.stdin.flush()),
        )
        logger.debug("[MCP] wrote %s (%.2fs)", method, time.monotonic() - t_write)

        # Read response, skipping non-JSON startup noise
        MAX_SKIP = 50
        skipped = 0
        for _ in range(MAX_SKIP):
            t_read = time.monotonic()
            line = await loop.run_in_executor(None, proc.stdout.readline)
            elapsed = time.monotonic() - t_read
            if not line:
                raise ImageGenerationError(
                    f"MCP server closed connection (waited {elapsed:.1f}s, skipped {skipped} lines)"
                )
            try:
                response = json.loads(line.strip())
                logger.debug("[MCP] got %s response (%.2fs)", method, elapsed)
                break
            except (json.JSONDecodeError, UnicodeDecodeError):
                skipped += 1
                logger.debug("[MCP] skipping non-JSON stdout[%d]: %.200s", skipped, line.rstrip())
                continue
        else:
            raise ImageGenerationError(
                f"MCP server sent >{MAX_SKIP} non-JSON lines (noise threshold exceeded)"
            )

        if "error" in response:
            raise ImageGenerationError(f"MCP error: {response['error']}")
        return response.get("result", {})

    async def generate(self, prompt: str, negative_prompt: str = "", **params) -> dict:
        """Call the MCP tool to generate an image. Returns response dict with image data."""
        if not self._initialized:
            raise ImageGenerationError("MCP provider not initialized. Call connect() first.")

        args = {"prompt": prompt}
        if negative_prompt:
            args["negative_prompt"] = negative_prompt
        for key in ("width", "height", "steps", "guidance", "cfg_truncation",
                     "max_sequence_length", "seed", "num_images"):
            if key in params:
                args[key] = params[key]

        if self._process is not None:
            VerboseLog.get().mcp_request("tools/call", {"name": self.config.mcp_tool_name, "arguments": args})
            result = await self._send_json_rpc_stdio("tools/call", {
                "name": self.config.mcp_tool_name,
                "arguments": args,
            })
            VerboseLog.get().mcp_response("tools/call", result=result)
        elif self._http_client is not None:
            resp = await self._http_client.post(
                self.config.mcp_url,
                json={"jsonrpc": "2.0", "method": "tools/call", "params": {
                    "name": self.config.mcp_tool_name,
                    "arguments": args,
                }, "id": 3},
            )
            result = resp.json().get("result", {})
        else:
            raise ImageGenerationError("MCP provider has no active connection")

        return result

    async def close(self) -> None:
        if self._process is not None:
            try:
                self._process.stdin.close()
            except Exception:
                pass
            self._process.kill()
            self._process = None
        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None
        self._initialized = False
