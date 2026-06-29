# DrawAgent Test Design

## Test Architecture

Tests are located in `tests/` and use pytest with pytest-asyncio. Mock providers
avoid dependency on real LLM APIs.

### Test Categories

| File | Category | Runs Without API Keys |
|------|----------|-----------------------|
| `test_config.py` | Config system | Yes |
| `test_tools.py` | Tool registry, lifecycle | Yes |
| `test_memory.py` | Memory store, index, tools | Yes |
| `test_providers.py` | Provider creation, error handling, lazy init | Yes |
| `test_integration.py` | Full inner loop (mock providers) | Yes |

## How to Run Tests

```bash
# All unit tests (no API keys needed, ~3 seconds)
pytest tests/ --ignore=tests/test_integration.py --ignore=tests/cli_test_runner.py -v

# API endpoint tests (no API keys needed, uses FastAPI TestClient)
pytest tests/test_api.py -v

# Provider-specific tests (no API keys needed)
pytest tests/test_providers.py -v

# Integration tests (also no API keys needed, uses mocks)
pytest tests/test_integration.py -v

# Full suite (97+ tests)
pytest tests/ --ignore=tests/cli_test_runner.py -v

# CLI test runner (requires running server)
# Terminal 1:
python -m drawagent serve --port 8000
# Terminal 2:
python tests/cli_test_runner.py
python tests/cli_test_runner.py --full  # includes generation (needs API key)
```

## CLI Test Runner

`tests/cli_test_runner.py` exercises every API endpoint that the frontend UI uses,
in the same order the frontend would call them. Use this to verify backend correctness
before testing the frontend UI.

```bash
# Smoke test (no API key needed)
python tests/cli_test_runner.py

# Full test with DeepSeek
set OPENAI_API_KEY=sk-xxx
python tests/cli_test_runner.py --full

# Test against custom port
python tests/cli_test_runner.py --server http://127.0.0.1:8080 --full
```

### What it tests:
1. Server status (/api/status)
2. Session CRUD (create, list, get history, delete)
3. Config GET/PUT (simulates switching to DeepSeek from frontend)
4. Message send (accepted by server)
5. Interrupt handling (pause, steer, accept)
6. Export + cleanup
7. Error scenarios (404s, invalid JSON)
8. Config sync flow (frontend DeepSeek switch actually changes backend)

## How the Config Sync Works (DeepSeek Switch Bug Fix)

Previously, changing Agent A to DeepSeek in the UI only saved to localStorage
— the backend still used OpenAI. Now:

1. Frontend `applySystemSettings()` calls `PUT /api/config` with the new settings
2. Backend `PUT /api/config` calls `ServerRunner.update_config()` 
3. `update_config()` sets new values on the runtime `AppConfig` model
4. Cached providers are cleared (`_provider_a = None, _provider_c = None`)
5. Next message recreates providers with the new API base/key/model

## Integration/E2E Tests (Require API Keys)

When you have API keys and an image generation service running, these
scenarios should be tested manually or with the following:

### Pre-requisites
1. Set `OPENAI_API_KEY` environment variable (or configure in frontend)
2. Start Z-Image server: `python webuiv5.py` on port 8000
3. Start DrawAgent server: `python -m drawagent serve`

### E2E Test Scenarios

#### Scenario 1: Server Starts Without API Key
1. Unset OPENAI_API_KEY: `Remove-Item Env:OPENAI_API_KEY`
2. Start DrawAgent: `python -m drawagent serve --port 8080`
3. **Expected**: Server starts, Web UI loads at http://127.0.0.1:8080
4. Type a prompt and send
5. **Expected**: Error card appears: "API 配置错误: ... 请在系统设置中配置 API Key"
6. Server should NOT crash

#### Scenario 2: Configure API Key via Frontend
1. With server running from Scenario 1
2. Open System Settings (gear icon)
3. Enter valid API key in Agent A API Key field
4. Enter valid API key in Agent C API Key field
5. Save settings
6. Type a prompt and send
7. **Expected**: Generation proceeds normally (errors only about image server)

#### Scenario 3: Image Server Unreachable
1. Stop Z-Image server (or don't start it)
2. Send a prompt to DrawAgent
3. **Expected**: Error card: "无法连接到图像生成服务器 (Agent B)"

#### Scenario 4: Invalid API Key
1. Enter an intentionally wrong API key
2. Send a prompt
3. **Expected**: Error card: "API Key 无效或未授权 (HTTP 401)"

#### Scenario 5: Invalid API Base URL
1. Set API Base URL to `http://nonexistent.local:1234/v1`
2. Send a prompt
3. **Expected**: Error card: "无法连接到 API 服务器"

#### Scenario 6: Agent C Has Full Configuration
1. Open System Settings
2. Verify Agent C shows: Provider, Model, API Base URL, API Key, Temperature
3. All fields should be editable and saved

#### Scenario 7: WebSocket Reconnection
1. Start a generation
2. Kill the server mid-generation
3. Restart the server
4. **Expected**: WebSocket should attempt reconnection (check browser console)

## Test Code for E2E (Run When API Keys Are Available)

```python
# tests/e2e/test_e2e.py — requires OPENAI_API_KEY or config file
import os
import sys
import asyncio
import httpx
import pytest

@pytest.mark.asyncio
@pytest.mark.e2e
async def test_server_starts_without_api_key():
    """Verify server can start even without API key configured."""
    import subprocess
    import time
    
    env = os.environ.copy()
    env.pop("OPENAI_API_KEY", None)
    
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "drawagent", "serve", "--port", "18999",
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    
    await asyncio.sleep(3)
    
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get("http://127.0.0.1:18999/api/status")
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "ok"
    finally:
        proc.kill()
        await proc.wait()

@pytest.mark.asyncio
@pytest.mark.e2e
@pytest.mark.skipif(
    not os.environ.get("OPENAI_API_KEY"),
    reason="Requires OPENAI_API_KEY set"
)
async def test_full_flow_with_real_api():
    """End-to-end: create session, send message, wait for result."""
    import time
    
    import httpx
    
    # Start server with API key
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "drawagent", "serve", "--port", "18998",
    )
    
    await asyncio.sleep(4)
    
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            # Create session
            resp = await client.post(
                "http://127.0.0.1:18998/api/sessions",
                json={"user_request": "a simple red circle on white background", "max_iterations": 2},
            )
            assert resp.status_code == 200
            session_id = resp.json()["session_id"]
            
            # Send message
            resp = await client.post(
                f"http://127.0.0.1:18998/api/sessions/{session_id}/message",
                json={"text": "a simple red circle on white background"},
            )
            assert resp.status_code == 200
            assert resp.json()["accepted"] is True
            
            # Wait for result (polling)
            for _ in range(30):
                await asyncio.sleep(4)
                resp = await client.get(
                    f"http://127.0.0.1:18998/api/sessions/{session_id}/history"
                )
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("iterations"):
                        assert len(data["iterations"]) >= 1
                        return  # Success
    finally:
        proc.kill()
        await proc.wait()
```
