from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path

import httpx

from drawagent.config.schema import AgentBConfig
from drawagent.core.errors import ImageGenerationError

logger = logging.getLogger("drawagent.mcp")


class MCPProvider:
    """Model Context Protocol image generation provider.

    Supports both stdio (local subprocess) and HTTP (remote) MCP servers.
    Communicates via JSON-RPC 2.0 over stdio or HTTP.
    """

    def __init__(self, config: AgentBConfig):
        self.config = config
        self._process: asyncio.subprocess.Process | None = None
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

        env = os.environ.copy()

        self._process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

        try:
            init_result = await self._send_json_rpc_stdio("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "DrawAgent", "version": "0.2.0"},
            })
            logger.info("MCP initialized: %s", init_result.get("serverInfo", {}))

            tools_result = await self._send_json_rpc_stdio("tools/list", {})
            tools = tools_result.get("tools", [])
            tool_name = self.config.mcp_tool_name

            for tool in tools:
                if tool.get("name") == tool_name:
                    self._tool_args_schema = tool.get("inputSchema", {})
                    break

            if self._tool_args_schema is None:
                available = [t.get("name") for t in tools]
                raise ImageGenerationError(
                    f"MCP tool '{tool_name}' not found. Available: {available}"
                )

            self._initialized = True
            logger.info("MCP tool '%s' discovered", tool_name)

        except Exception:
            if self._process:
                self._process.kill()
                self._process = None
            raise

    async def _http_initialize(self) -> None:
        assert self._http_client is not None
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
        assert self._process is not None
        assert self._process.stdin is not None
        assert self._process.stdout is not None

        request = json.dumps({
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": 1,
        })

        self._process.stdin.write((request + "\n").encode())
        await self._process.stdin.drain()

        line = await self._process.stdout.readline()
        if not line:
            raise ImageGenerationError("MCP server closed connection")

        response = json.loads(line.decode())
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
        for key in ("width", "height", "steps", "guidance", "seed", "num_images"):
            if key in params:
                args[key] = params[key]

        if self._process is not None:
            result = await self._send_json_rpc_stdio("tools/call", {
                "name": self.config.mcp_tool_name,
                "arguments": args,
            })
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
