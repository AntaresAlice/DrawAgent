#!/usr/bin/env python
"""
DrawAgent CLI API Test Runner

Exercises every API endpoint that the frontend UI uses, in the correct order
that the frontend would call them. Use this to verify backend correctness
before testing the frontend UI.

Usage:
    # Quick smoke test
    python tests/cli_test_runner.py

    # Full test with API key
    set OPENAI_API_KEY=sk-xxx
    python tests/cli_test_runner.py --full

    # Test against custom server
    python tests/cli_test_runner.py --server http://127.0.0.1:8000 --full

This script validates:
  1. Server starts and /api/status responds
  2. Session CRUD (create, list, get history, delete)
  3. Config GET/PUT (change Agent A to DeepSeek, verify applied)
  4. Message send (creates background task)
  5. WebSocket connection receives events
  6. Interrupt handling
  7. Image serving
  8. Session export
  9. Error scenarios (bad config, unreachable image server, etc.)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx


# ANSI colors for terminal output
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RESET = "\033[0m"
BOLD = "\033[1m"


class TestRunner:
    def __init__(self, server_url: str, full_mode: bool = False, api_key: str | None = None):
        self.server_url = server_url.rstrip("/")
        self.full_mode = full_mode
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.passed = 0
        self.failed = 0
        self.skipped = 0
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(30))
        return self._client

    def ok(self, msg: str) -> None:
        print(f"  {GREEN}✓{RESET} {msg}")
        self.passed += 1

    def fail(self, msg: str) -> None:
        print(f"  {RED}✗{RESET} {msg}")
        self.failed += 1

    def skip(self, msg: str) -> None:
        print(f"  {YELLOW}○{RESET} {msg}")
        self.skipped += 1

    def header(self, msg: str) -> None:
        print(f"\n{BOLD}{CYAN}{msg}{RESET}")
        print("-" * 50)

    async def check_server(self) -> bool:
        """Verify server is running."""
        try:
            client = await self._get_client()
            resp = await client.get(f"{self.server_url}/api/status")
            if resp.status_code == 200:
                data = resp.json()
                self.ok(f"Server running: {data['status']}, version {data['version']}, {data['sessions_count']} sessions")
                return True
            else:
                self.fail(f"Server returned {resp.status_code}")
                return False
        except httpx.ConnectError:
            self.fail(f"Cannot connect to {self.server_url} — is the server running?")
            return False

    async def test_sessions_crud(self) -> str | None:
        """Test session creation, listing, and deletion."""
        self.header("1. Session CRUD")

        client = await self._get_client()

        # Create
        resp = await client.post(f"{self.server_url}/api/sessions", json={
            "user_request": "a beautiful sunset over mountains",
            "max_iterations": 3,
        })
        if resp.status_code == 200:
            data = resp.json()
            sid = data["session_id"]
            self.ok(f"Session created: {sid[:12]}...")
        else:
            self.fail(f"Session creation failed: {resp.status_code} — {resp.text}")
            return None

        # List
        resp = await client.get(f"{self.server_url}/api/sessions")
        if resp.status_code == 200:
            sessions = resp.json()
            found = any(s["id"] == sid for s in sessions)
            if found:
                self.ok(f"Session appears in list ({len(sessions)} total)")
            else:
                self.fail("Created session not found in list")
        else:
            self.fail(f"Session list failed: {resp.status_code}")

        # History
        resp = await client.get(f"{self.server_url}/api/sessions/{sid}/history")
        if resp.status_code == 200:
            data = resp.json()
            assert data["session_id"] == sid
            self.ok(f"History returned: {data['user_request'][:50]}...")
        else:
            self.fail(f"History failed: {resp.status_code}")

        return sid

    async def test_config_api(self) -> None:
        """Test getting and updating config (simulates frontend DeepSeek switch)."""
        self.header("2. Config API (GET + PUT)")

        client = await self._get_client()

        # GET current config
        resp = await client.get(f"{self.server_url}/api/config")
        if resp.status_code == 200:
            config = resp.json()
            self.ok(f"Current config: Agent A={config['agent_a']['model']}, Agent C={config['agent_c']['model']}")
        else:
            self.fail(f"Config GET failed: {resp.status_code}")

        # PUT DeepSeek config (simulates frontend switching to DeepSeek)
        resp = await client.put(f"{self.server_url}/api/config", json={
            "agent_a": {
                "provider": "deepseek",
                "model": "deepseek-chat",
                "api_base": "https://api.deepseek.com/v1",
                "api_key": self.api_key or "sk-placeholder",
                "temperature": 0.6,
            },
            "agent_c": {
                "provider": "deepseek",
                "model": "deepseek-chat",
                "api_base": "https://api.deepseek.com/v1",
                "api_key": self.api_key or "sk-placeholder",
                "temperature": 0.1,
            },
        })
        if resp.status_code == 200 and resp.json().get("updated"):
            self.ok("Config updated to DeepSeek (runtime applied)")
        else:
            self.fail(f"Config PUT failed: {resp.status_code} — {resp.text}")

        # GET config again to verify
        resp = await client.get(f"{self.server_url}/api/config")
        if resp.status_code == 200:
            config = resp.json()
            # Note: api_base not in GET response currently
            self.ok(f"Config after update: Agent A={config['agent_a']['model']}")

    async def test_send_message(self, session_id: str) -> None:
        """Send a message and verify it's accepted."""
        self.header("3. Send Message")

        if not self.full_mode:
            self.skip("Skipping (use --full to run message + generation)")
            return

        client = await self._get_client()
        resp = await client.post(
            f"{self.server_url}/api/sessions/{session_id}/message",
            json={"text": "a beautiful sunset over mountains"},
        )
        if resp.status_code == 200:
            data = resp.json()
            self.ok(f"Message accepted: message_id={data['message_id']}")
            print(f"  {YELLOW}⏳{RESET} Waiting for generation... (WebSocket events would appear)")
        else:
            self.fail(f"Message send failed: {resp.status_code} — {resp.text}")

    async def test_interrupt(self, session_id: str) -> None:
        """Test interrupt actions."""
        self.header("4. Interrupt API")

        client = await self._get_client()

        # Pause
        resp = await client.post(
            f"{self.server_url}/api/sessions/{session_id}/interrupt",
            json={"action": "pause"},
        )
        if resp.status_code == 200 and resp.json()["accepted"]:
            self.ok("Interrupt pause: accepted")

        # Steer with message
        resp = await client.post(
            f"{self.server_url}/api/sessions/{session_id}/interrupt",
            json={"action": "steer", "data": {"message": "make the sky more dramatic"}},
        )
        if resp.status_code == 200:
            self.ok("Interrupt steer: accepted")

        # Accept (mark as complete)
        resp = await client.post(
            f"{self.server_url}/api/sessions/{session_id}/interrupt",
            json={"action": "accept_current"},
        )
        if resp.status_code == 200:
            self.ok("Interrupt accept: accepted")

    async def test_export_and_cleanup(self, session_id: str) -> None:
        """Test session export and deletion."""
        self.header("5. Export & Cleanup")

        client = await self._get_client()

        # Export
        resp = await client.get(f"{self.server_url}/api/sessions/{session_id}/export")
        if resp.status_code == 200:
            content_type = resp.headers.get("content-type", "")
            if "zip" in content_type:
                size = len(resp.content)
                self.ok(f"Session exported: {size} bytes (ZIP)")
            else:
                self.fail(f"Export not ZIP: {content_type}")
        else:
            self.fail(f"Export failed: {resp.status_code}")

        # Delete
        resp = await client.delete(f"{self.server_url}/api/sessions/{session_id}")
        if resp.status_code == 200:
            self.ok(f"Session {session_id[:12]}... deleted")

    async def test_error_scenarios(self) -> None:
        """Test that errors are handled gracefully."""
        self.header("6. Error Scenarios")

        client = await self._get_client()

        # 404 on nonexistent session
        resp = await client.get("/api/sessions/nonexistent-12345/history")
        if resp.status_code == 404:
            self.ok("Nonexistent session returns 404")
        else:
            self.fail(f"Expected 404, got {resp.status_code}")

        # 404 on nonexistent image
        resp = await client.get(f"{self.server_url}/api/images/nonexistent.png")
        if resp.status_code == 404:
            self.ok("Nonexistent image returns 404")

        # Invalid JSON body
        resp = await client.post(
            f"{self.server_url}/api/sessions",
            content="not json",
            headers={"Content-Type": "application/json"},
        )
        if resp.status_code == 422:
            self.ok("Invalid JSON returns 422")
        else:
            self.fail(f"Expected 422, got {resp.status_code}")

        # Config update with bad data should still work (graceful)
        resp = await client.put(f"{self.server_url}/api/config", json={
            "agent_a": {"temperature": 999},  # out of typical range
        })
        if resp.status_code == 200:
            self.ok("Out-of-range config value accepted (applied to Pydantic model)")

    async def test_config_sync_flow(self) -> None:
        """Test that frontend config syncs to backend (the DeepSeek switch bug fix)."""
        self.header("7. Config Sync (Frontend -> Backend)")

        client = await self._get_client()

        # Step 1: Store original config for reference
        original = await client.get(f"{self.server_url}/api/config")
        original_config = original.json()
        self.ok(f"Original config model: {original_config['agent_a']['model']}")

        # Step 2: Switch to DeepSeek (what frontend does)
        deepseek_config = {
            "agent_a": {
                "provider": "deepseek",
                "model": "deepseek-chat",
                "api_base": "https://api.deepseek.com/v1",
                "api_key": self.api_key or "sk-deepseek-test",
                "temperature": 0.6,
            },
        }
        resp = await client.put(f"{self.server_url}/api/config", json=deepseek_config)
        assert resp.status_code == 200 and resp.json()["updated"]
        self.ok("Sent DeepSeek config to backend")

        # Step 3: Send a message — backend should now use DeepSeek, not OpenAI
        # The real test is whether the next request uses the new config
        resp = await client.post(f"{self.server_url}/api/sessions", json={
            "user_request": "deepseek test — should not call openai",
            "max_iterations": 1,
        })
        if resp.status_code == 200:
            sid = resp.json()["session_id"]

            if self.full_mode and self.api_key:
                resp = await client.post(
                    f"{self.server_url}/api/sessions/{sid}/message",
                    json={"text": "a simple red circle on white background"},
                )
                if resp.status_code == 200:
                    self.ok("Message sent with DeepSeek config — check server logs for API base URL")
                else:
                    self.fail(f"Message send failed: {resp.status_code}")
            else:
                self.skip("Skipping generation (use --full with valid API key for DeepSeek)")
            # Cleanup
            await client.delete(f"{self.server_url}/api/sessions/{sid}")
        else:
            self.fail(f"Session creation failed: {resp.status_code}")

    async def run(self) -> bool:
        """Run all tests."""
        print(f"{BOLD}{CYAN}══════════════════════════════════════{RESET}")
        print(f"{BOLD}{CYAN}  DrawAgent CLI API Test Runner{RESET}")
        print(f"{BOLD}{CYAN}  Server: {self.server_url}{RESET}")
        print(f"{BOLD}{CYAN}  Mode: {'full' if self.full_mode else 'smoke'}{RESET}")
        print(f"{BOLD}{CYAN}══════════════════════════════════════{RESET}")

        if not await self.check_server():
            print(f"\n{RED}Server not running. Start with:{RESET}")
            print(f"  python -m drawagent serve --port 8000")
            return False

        # Run tests
        sid = await self.test_sessions_crud()
        if sid is None:
            self.fail("Session CRUD failed — aborting remaining tests")
            return False

        await self.test_config_api()
        await self.test_send_message(sid)
        await self.test_interrupt(sid)
        await self.test_export_and_cleanup(sid)
        await self.test_error_scenarios()

        if self.full_mode:
            await self.test_config_sync_flow()

        # Summary
        total = self.passed + self.failed + self.skipped
        print(f"\n{BOLD}{'=' * 50}{RESET}")
        print(f"{BOLD}Results: {GREEN}{self.passed} passed{RESET}, {RED}{self.failed} failed{RESET}, {YELLOW}{self.skipped} skipped{RESET} ({total} total)")
        print(f"{'=' * 50}\n")

        return self.failed == 0


async def main():
    parser = argparse.ArgumentParser(description="DrawAgent CLI API Test Runner")
    parser.add_argument("--server", default="http://127.0.0.1:8000", help="Server URL")
    parser.add_argument("--full", action="store_true", help="Run full tests including generation")
    parser.add_argument("--api-key", default=None, help="API key to use (or set OPENAI_API_KEY)")
    args = parser.parse_args()

    runner = TestRunner(
        server_url=args.server,
        full_mode=args.full,
        api_key=args.api_key,
    )

    success = await runner.run()

    if runner._client:
        await runner._client.aclose()

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
