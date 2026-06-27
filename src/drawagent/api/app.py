from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .routes import init_routes, router
from .websocket import ws_manager


def create_app(
    output_dir: str = "./outputs",
) -> FastAPI:
    """FastAPI application factory.

    Reference: opencode's Server HttpApi with modular routing.
    """
    app = FastAPI(
        title="DrawAgent API",
        version="0.1.0",
        description="AI-powered image generation agent system",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Wait for session_manager and interrupt_handler to be injected
    # via init_routes() from main.py
    @app.on_event("startup")
    async def on_startup():
        pass

    app.include_router(router)

    # WebSocket endpoint
    @app.websocket("/ws/sessions/{session_id}")
    async def session_websocket(ws: WebSocket, session_id: str):
        await ws_manager.connect(session_id, ws)
        try:
            while True:
                data = await ws.receive_text()
                import json
                msg = json.loads(data)
                if msg.get("type") == "interrupt":
                    from .routes import _interrupt_handler, _session_manager
                    if _interrupt_handler and _session_manager:
                        session = _session_manager.get_or_none(session_id)
                        if session:
                            await _interrupt_handler.handle(
                                session,
                                msg["action"],
                                msg.get("data"),
                            )
        except WebSocketDisconnect:
            pass
        finally:
            await ws_manager.disconnect(session_id, ws)

    # Mount static files for the UI
    static_dir = Path(__file__).parent.parent / "ui" / "static"
    if static_dir.exists():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    return app
