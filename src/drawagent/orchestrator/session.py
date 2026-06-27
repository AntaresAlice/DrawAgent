from __future__ import annotations

import asyncio
import uuid
from datetime import datetime

from drawagent.core.errors import SessionError
from drawagent.core.types import Iteration, Session, SessionState


class SessionManager:
    """Manages Session lifecycle: create, get, delete, state transitions.

    Reference: opencode's SessionExecution coordination.
    """

    def __init__(self):
        self._sessions: dict[str, Session] = {}

    def create(self, user_request: str = "", max_iterations: int = 7) -> Session:
        session_id = str(uuid.uuid4())[:8]
        session = Session(
            id=session_id,
            created_at=datetime.now(),
            user_request=user_request,
            max_iterations=max_iterations,
        )
        self._sessions[session_id] = session
        return session

    def get(self, session_id: str) -> Session:
        session = self._sessions.get(session_id)
        if session is None:
            raise SessionError(f"Session not found: {session_id}")
        return session

    def get_or_none(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)

    def delete(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def list_ids(self) -> list[str]:
        return list(self._sessions.keys())

    def transition(self, session: Session, new_state: SessionState) -> None:
        session.state = new_state

    def add_iteration(self, session: Session, iteration: Iteration) -> None:
        session.iterations.append(iteration)

    def set_interrupt(self, session: Session, action: str, message: str | None = None) -> None:
        session.pending_action = action
        session.steer_message = message
        session.interrupt_event.set()

    def clear_interrupt(self, session: Session) -> None:
        session.pending_action = None
        session.steer_message = None
        session.interrupt_event.clear()

    def is_interrupted(self, session: Session) -> bool:
        return session.interrupt_event.is_set()
