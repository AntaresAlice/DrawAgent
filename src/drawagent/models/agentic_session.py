"""Agentic mode data models — isolated from classic core/types.py:Session.

These models are used exclusively by the LLM-driven agentic loop.
Classic mode continues to use core/types.py:Session with zero changes.

Reference: opencode's Session.Info, Message types, session_message, session_input.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Literal
from uuid import uuid4

if TYPE_CHECKING:
    from drawagent.orchestrator.session import SessionManager


# ---------------------------------------------------------------------------
# Core data classes
# ---------------------------------------------------------------------------


@dataclass
class AgenticUserMessage:
    """User input message.

    Analogous to opencode's session_input row: admitted when user submits,
    promoted when fed to the LLM. Delivery discriminates steer vs queue.
    """

    text: str
    id: str = field(default_factory=lambda: f"umsg_{uuid4().hex[:8]}")
    delivery: Literal["steer", "queue"] = "steer"
    admitted_at: datetime = field(default_factory=datetime.now)
    promoted_at: datetime | None = None
    seq: int = 0


@dataclass
class AgenticToolCall:
    """One tool invocation within a turn.

    Analogous to opencode's AssistantTool — transitions through
    pending → running → completed / error states.
    """

    call_id: str = field(default_factory=lambda: f"call_{uuid4().hex[:8]}")
    tool_name: str = ""
    arguments: dict = field(default_factory=dict)
    status: Literal["pending", "running", "completed", "error"] = "pending"
    result: dict | None = None
    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


@dataclass
class AgenticTurn:
    """One LLM interaction: user message → assistant response (possibly with tool calls).

    Analogous to opencode's assistant message with its content[] array
    containing text blocks, reasoning blocks, and tool execution states.
    """

    id: str = field(default_factory=lambda: f"turn_{uuid4().hex[:8]}")
    user_message: AgenticUserMessage | None = None
    assistant_text: str | None = None
    tool_calls: list[AgenticToolCall] = field(default_factory=list)
    finish_reason: Literal["stop", "tool_calls", "error", "interrupted"] | None = None
    tokens_used: int = 0
    started_at: datetime | None = None
    completed_at: datetime | None = None


@dataclass
class AgenticTurnResult:
    """Return value from AgentA.run_agentic_turn()."""

    text: str = ""
    tool_results: list[AgenticToolCall] = field(default_factory=list)
    finish_reason: Literal["stop", "tool_calls", "error"] = "stop"
    finalized: bool = False
    tokens_used: int = 0


@dataclass
class AgenticCompaction:
    """Context compaction checkpoint.

    Analogous to opencode's compaction message type.
    Stores an LLM-generated summary that replaces older turns.
    """

    id: str = field(default_factory=lambda: f"comp_{uuid4().hex[:8]}")
    seq: int = 0
    summary: str = ""
    recent_context: str = ""
    compacted_turn_count: int = 0
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class AgenticIteration:
    """One outer-loop iteration — groups a set of turns + inspection results.

    Replaces the dict-based iterations list for type safety.
    """

    number: int = 0
    turns: list[str] = field(default_factory=list)  # turn IDs
    images: list[dict] = field(default_factory=list)   # {path, seed, width, height}
    inspections: list[dict] = field(default_factory=list)  # {path, score, passed, feedback, ...}
    decision: dict | None = None  # {action, passed, reasoning}
    summary: str = ""


@dataclass
class AgenticSession:
    """An agentic-mode conversation session.

    Analogous to opencode's Session.Info + projected session_message rows.
    Completely separate from core/types.py:Session — classic path untouched.
    """

    id: str = field(default_factory=lambda: f"ses_{uuid4().hex[:8]}")
    user_request: str = ""
    messages: list[AgenticUserMessage] = field(default_factory=list)
    turns: list[AgenticTurn] = field(default_factory=list)
    compactions: list[AgenticCompaction] = field(default_factory=list)
    learned_lessons: list[str] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)
    iterations: list[AgenticIteration] = field(default_factory=list)
    finalize_rejection_count: int = 0
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    def to_api_response(self) -> dict:
        return {
            "id": self.id,
            "user_request": self.user_request,
            "iterations": self.iterations,
            "learned_lessons": self.learned_lessons,
            "error": self.errors[-1] if self.errors else None,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "engine": "agentic",
            "message_count": len(self.messages),
            "turn_count": len(self.turns),
        }


# ---------------------------------------------------------------------------
# InputQueue — session-scoped steer/queue manager
# ---------------------------------------------------------------------------


class InputQueue:
    """Per-session input queue for agentic mode.

    Analogous to opencode's session_input table + promoteSteers/promoteNextQueued.

    Owned by SessionRunner (not a local variable in run_session).
    WebSocket handlers access it via runner reference to admit messages.
    """

    def __init__(self, session_id: str, db: SessionManager):
        self._session_id = session_id
        self._db = db
        self._seq_counter: int = 0

    def admit(self, text: str, delivery: Literal["steer", "queue"]) -> AgenticUserMessage:
        self._seq_counter += 1
        msg = AgenticUserMessage(
            text=text,
            delivery=delivery,
            seq=self._seq_counter,
            admitted_at=datetime.now(),
        )
        return msg

    async def admit_and_persist(self, text: str, delivery: Literal["steer", "queue"]) -> AgenticUserMessage:
        msg = self.admit(text, delivery)
        await self._db.save_agentic_message(
            session_id=self._session_id,
            msg_id=msg.id,
            seq=msg.seq,
            delivery=msg.delivery,
            text=msg.text,
            admitted_at=msg.admitted_at.isoformat(),
            promoted_at=None,
        )
        return msg

    async def has_pending(self, delivery: Literal["steer", "queue"]) -> bool:
        return await self._db.has_pending_agentic_messages(self._session_id, delivery)

    async def promote_steers(self, cutoff_seq: int | None = None) -> int:
        """Promote all unpromoted steer messages in DB. Returns count of promoted messages.

        Callers should only check count > 0; actual message content is loaded
        by ContextBuilder from session.messages (which must be populated separately).
        """
        return await self._db.promote_agentic_messages(
            self._session_id, "steer", cutoff_seq
        )

    async def promote_next_queued(self) -> int:
        """Promote all unpromoted queued messages. Returns count of promoted messages.

        Despite the name, this promotes ALL (not just one) — the docstring was
        inaccurate. For typical single-message-at-a-time HTTP flow this is harmless.
        """
        return await self._db.promote_agentic_messages(
            self._session_id, "queue", cutoff_seq=None
        )
