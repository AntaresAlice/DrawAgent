"""M4 smoke tests for DrawAgent API + UI layer."""

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, "src")


async def smoke_test():
    # ── 1. API Schemas ──
    from drawagent.api.schemas import (
        CreateSessionRequest,
        CreateSessionResponse,
        SendMessageRequest,
        InterruptRequest,
        ServerStatus,
        SessionHistoryResponse,
    )

    req = CreateSessionRequest(user_request="draw a cat", max_iterations=5)
    assert req.user_request == "draw a cat"
    assert req.max_iterations == 5

    resp = CreateSessionResponse(session_id="abc123")
    assert resp.session_id == "abc123"

    msg_req = SendMessageRequest(text="hello")
    assert msg_req.text == "hello"

    int_req = InterruptRequest(action="steer", data={"message": "change"})
    assert int_req.action == "steer"
    assert int_req.data == {"message": "change"}

    status = ServerStatus(version="0.1.0", sessions_count=3)
    assert status.status == "ok"
    assert status.sessions_count == 3

    print("1. API Schemas: OK")

    # ── 2. WebSocket Manager ──
    from drawagent.api.websocket import ws_manager, WebSocketManager

    wm = WebSocketManager()
    assert wm.connection_count == 0
    print("2. WebSocket Manager: OK")

    # ── 3. API Routes exist ──
    from drawagent.api.routes import router, init_routes

    assert router is not None
    route_paths = [r.path for r in router.routes]
    assert "/api/sessions" in route_paths
    assert "/api/status" in route_paths
    print("3. API Routes: OK")

    # ── 4. App Factory ──
    from drawagent.api.app import create_app
    from drawagent.main import main

    app = create_app(output_dir="./outputs")
    assert app is not None
    assert app.title == "DrawAgent API"
    print("4. App Factory: OK")

    # ── 5. Static files exist ──
    static_dir = Path(__file__).parent.parent / "src" / "drawagent" / "ui" / "static"
    assert (static_dir / "index.html").exists()
    assert (static_dir / "css" / "style.css").exists()
    assert (static_dir / "js" / "app.js").exists()
    assert (static_dir / "js" / "api.js").exists()
    assert (static_dir / "js" / "renderer.js").exists()
    assert (static_dir / "js" / "events.js").exists()
    assert (static_dir / "js" / "viewer.js").exists()
    print("5. Static files: OK")

    # ── 6. HTML contains key elements ──
    html = (static_dir / "index.html").read_text(encoding="utf-8")
    assert "DrawAgent" in html
    assert "sidebar" in html
    assert "messagesContainer" in html
    assert "promptInput" in html
    assert "interruptBar" in html
    assert "settingsPanel" in html
    assert "viewerOverlay" in html
    assert "AppState.init()" in html
    print("6. HTML structure: OK")

    # ── 7. CSS contains key classes ──
    css = (static_dir / "css" / "style.css").read_text(encoding="utf-8")
    assert ".sidebar" in css
    assert ".message" in css
    assert ".iteration-card" in css
    assert ".viewer-overlay" in css
    assert ".settings-panel" in css
    assert ".interrupt-bar" in css
    print("7. CSS structure: OK")

    # ── 8. JS AppState ──
    js_app = (static_dir / "js" / "app.js").read_text(encoding="utf-8")
    assert "AppState" in js_app
    assert "currentSessionId" in js_app
    assert "settings" in js_app
    assert "generationParams" in js_app
    print("8. JS AppState: OK")

    # ── 9. JS API module ──
    js_api = (static_dir / "js" / "api.js").read_text(encoding="utf-8")
    assert "createSession" in js_api
    assert "sendMessage" in js_api
    assert "sendInterrupt" in js_api
    assert "WebSocket" in js_api or "WSClient" in js_api
    print("9. JS API module: OK")

    # ── 10. JS Renderer ──
    js_renderer = (static_dir / "js" / "renderer.js").read_text(encoding="utf-8")
    assert "addMessage" in js_renderer
    assert "addIterationCard" in js_renderer
    assert "setLoading" in js_renderer
    assert "showToast" in js_renderer
    print("10. JS Renderer: OK")

    # ── 11. JS EventRouter ──
    js_events = (static_dir / "js" / "events.js").read_text(encoding="utf-8")
    assert "EventRouter" in js_events
    assert "dispatch" in js_events
    assert "iteration.started" in js_events
    assert "images.ready" in js_events
    assert "loop.terminated" in js_events
    assert "AppActions" in js_events
    assert "sendMessage" in js_events
    assert "acceptCurrent" in js_events
    print("11. JS EventRouter + AppActions: OK")

    # ── 12. JS Viewer ──
    js_viewer = (static_dir / "js" / "viewer.js").read_text(encoding="utf-8")
    assert "Viewer" in js_viewer
    assert "open" in js_viewer and "close" in js_viewer
    assert "ArrowLeft" in js_viewer or "ArrowRight" in js_viewer
    print("12. JS Viewer: OK")

    # ── 13. main.py entry point ──
    from drawagent.main import main, run_server

    assert callable(main)
    assert callable(run_server)
    print("13. main.py entrypoint: OK")

    # ── 14. FastAPI test client ──
    from fastapi.testclient import TestClient
    from drawagent.orchestrator.session import SessionManager
    from drawagent.orchestrator.interrupt import InterruptHandler

    sm = SessionManager()
    ih = InterruptHandler()

    test_app = create_app(output_dir="./outputs")
    from drawagent.api.routes import init_routes
    init_routes(sm, ih, "./outputs")

    client = TestClient(test_app)
    resp = client.get("/api/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["version"] == "0.1.0"
    print("14. FastAPI TestClient: OK")

    # ── 15. Create session via API ──
    resp = client.post("/api/sessions", json={"user_request": "draw a cat", "max_iterations": 5})
    assert resp.status_code == 200
    data = resp.json()
    assert "session_id" in data
    sid = data["session_id"]

    resp = client.get("/api/sessions")
    assert resp.status_code == 200
    sessions = resp.json()
    assert len(sessions) >= 1
    print("15. Create/list sessions: OK")

    # ── 16. Send message and get history ──
    resp = client.post(f"/api/sessions/{sid}/message", json={"text": "hello"})
    assert resp.status_code == 200

    resp = client.get(f"/api/sessions/{sid}/history")
    assert resp.status_code == 200
    history = resp.json()
    assert history["session_id"] == sid
    print("16. Send message + history: OK")

    # ── 17. Interrupt session ──
    resp = client.post(f"/api/sessions/{sid}/interrupt", json={
        "action": "steer",
        "data": {"message": "change style"},
    })
    assert resp.status_code == 200
    assert resp.json()["accepted"]
    print("17. Interrupt session: OK")

    # ── 18. Delete session ──
    resp = client.delete(f"/api/sessions/{sid}")
    assert resp.status_code == 200
    resp = client.get("/api/sessions")
    assert len([s for s in resp.json() if s["id"] == sid]) == 0
    print("18. Delete session: OK")

    print()
    print("=== ALL M4 SMOKE TESTS PASSED ===")


if __name__ == "__main__":
    asyncio.run(smoke_test())
