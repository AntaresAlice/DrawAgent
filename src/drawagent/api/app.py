from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .routes import init_routes, router
from .websocket import ws_manager


def create_app(
    output_dir: str = "./outputs",
) -> FastAPI:
    """FastAPI application factory."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield

    app = FastAPI(
        title="DrawAgent API",
        version="0.1.0",
        description="AI-powered image generation agent system",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(router)

    # WebSocket endpoint — handles interrupts, clarification confirmations
    @app.websocket("/ws/sessions/{session_id}")
    async def session_websocket(ws: WebSocket, session_id: str):
        await ws_manager.connect(session_id, ws)
        try:
            while True:
                data = await ws.receive_text()
                msg = json.loads(data)
                if msg.get("type") == "interrupt":
                    from .routes import _interrupt_handler, _session_manager, _runner
                    if _runner is not None:
                        # Check for agentic mode first
                        agentic_state = _runner.get_agentic_state(session_id)
                        if agentic_state is not None and msg.get("action") == "steer":
                            text = msg.get("data", {}).get("message", "")
                            if text:
                                await _runner.handle_agentic_steer(session_id, text)
                            continue
                    if _interrupt_handler and _session_manager:
                        session = _session_manager.get_or_none(session_id)
                        if session:
                            await _interrupt_handler.handle(
                                session,
                                msg["action"],
                                msg.get("data"),
                            )
                            # If steer message supplied, store it
                            if msg.get("data", {}).get("message"):
                                session.steer_message = msg["data"]["message"]
                elif msg.get("type") in ("clarify_accept", "clarify_modify"):
                    from .routes import _session_manager
                    if _session_manager:
                        session = _session_manager.get_or_none(session_id)
                        if session:
                            if msg["type"] == "clarify_modify":
                                extra = msg.get("text", "")
                                if extra:
                                    session.user_request = (session.user_request or "") + " " + extra
                            session.pending_action = "clarify_done"
                            session.interrupt_event.set()
        except WebSocketDisconnect:
            pass
        finally:
            await ws_manager.disconnect(session_id, ws)

    # Mount static files for the UI
    static_dir = Path(__file__).parent.parent / "ui" / "static"
    if static_dir.exists():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    return app
