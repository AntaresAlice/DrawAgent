from __future__ import annotations

import asyncio
import json
from typing import Optional

from fastapi import WebSocket, WebSocketDisconnect


class WebSocketManager:
    """Manages WebSocket connections per session for real-time event broadcasting.

    Reference: opencode's EventV2 WebSocket push pattern.
    """

    def __init__(self):
        self._connections: dict[str, list[WebSocket]] = {}

    async def connect(self, session_id: str, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.setdefault(session_id, []).append(ws)

    async def disconnect(self, session_id: str, ws: WebSocket) -> None:
        if session_id in self._connections:
            try:
                self._connections[session_id].remove(ws)
            except ValueError:
                pass
            if not self._connections[session_id]:
                del self._connections[session_id]

    async def broadcast(self, session_id: str, event_type: str, **data: object) -> None:
        """Push an event to all WebSocket connections for a session."""
        connections = self._connections.get(session_id, [])
        if not connections:
            return

        payload = json.dumps({"type": event_type, **data}, ensure_ascii=False, default=str)
        dead: list[WebSocket] = []
        for ws in connections:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)

        for ws in dead:
            await self.disconnect(session_id, ws)

    async def broadcast_all(self, event_type: str, **data: object) -> None:
        """Broadcast to all connected sessions."""
        payload = json.dumps({"type": event_type, **data}, ensure_ascii=False, default=str)
        for session_id in list(self._connections.keys()):
            for ws in self._connections.get(session_id, []):
                try:
                    await ws.send_text(payload)
                except Exception:
                    pass

    @property
    def connection_count(self) -> int:
        return sum(len(conns) for conns in self._connections.values())


# Global singleton
ws_manager = WebSocketManager()
