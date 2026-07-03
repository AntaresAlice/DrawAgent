"""SteerController — agentic mode user interrupt/feedback handler.

Analogous to opencode's wake() + hasPending("steer") mechanism.
Replaces classic mode's InterruptHandler (pending_action + interrupt_event).

Named steer_controller.py to avoid collision with existing orchestrator/interrupt.py
(used by classic mode and fully preserved).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from drawagent.models.agentic_session import InputQueue
    from drawagent.api.websocket import WebSocketManager

logger = logging.getLogger("drawagent.steer_controller")


class SteerController:
    """Handles user feedback/steering messages in agentic mode.

    All async primitives use asyncio.Event (not threading.Event),
    consistent with the rest of the codebase's async architecture.
    """

    def __init__(
        self,
        input_queue: "InputQueue",
        ws_manager: "WebSocketManager | None" = None,
    ):
        self._queue = input_queue
        self._ws_manager = ws_manager
        self._new_steer = asyncio.Event()

    async def handle_user_message(
        self,
        session_id: str,
        text: str,
        delivery: str = "steer",
    ) -> None:
        """Called by WebSocket handler when user sends a message during an active session.

        Admits the message to InputQueue (persisted to DB) and sets the
        asyncio.Event to notify the running loop.
        """
        from drawagent.models.agentic_session import AgenticUserMessage

        msg = AgenticUserMessage(
            text=text,
            delivery=delivery,  # type: ignore
            admitted_at=datetime.now(),
        )
        # Admit to queue (the queue's _db persists it)
        await self._queue.admit_and_persist(text, delivery)  # type: ignore

        # Broadcast to frontend
        if self._ws_manager:
            await self._ws_manager.broadcast(
                session_id,
                "interrupt.accepted",
                **{"message": text, "delivery": delivery},
            )

        self._new_steer.set()
        logger.info("Steer message admitted for session %s: %s", session_id, text[:80])

    async def wait_for_pending(self, timeout: float = 0.1) -> bool:
        """Non-blocking check + short wait for new steer messages.

        Called by the agentic loop between turns to check if the user
        sent feedback while the LLM was working.

        Returns True if steer messages are pending, False otherwise.
        """
        # Check immediately
        if await self._queue.has_pending("steer"):
            self._new_steer.clear()
            return True
        # Wait briefly for new messages
        try:
            await asyncio.wait_for(self._new_steer.wait(), timeout=timeout)
            self._new_steer.clear()
            return await self._queue.has_pending("steer")
        except asyncio.TimeoutError:
            return False
