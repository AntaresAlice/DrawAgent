from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class DrawEvent(str, Enum):
    # Session events
    SESSION_CREATED = "session.created"
    SESSION_RESUMED = "session.resumed"

    # Outer loop events
    USER_MESSAGE = "user.message"
    A_QUESTION = "agent.question"
    USER_ANSWER = "user.answer"

    # Inner loop events
    ITERATION_STARTED = "iteration.started"
    INSPECTION_PLAN_READY = "inspection.plan_ready"
    PROMPT_REFINED = "prompt.refined"
    GEN_PARAMS_SELECTED = "gen.params_selected"
    GENERATION_STARTED = "generation.started"
    GENERATION_PROGRESS = "generation.progress"
    IMAGES_READY = "images.ready"
    INSPECTION_TASK_DONE = "inspection.task_done"
    INSPECTION_COMPLETE = "inspection.complete"
    QUALITY_DECISION = "quality.decision"
    LOOP_TERMINATED = "loop.terminated"

    # User interrupt events
    USER_INTERRUPT = "user.interrupt"
    USER_STEER = "user.steer"
    USER_ACCEPT = "user.accept"
    USER_ROLLBACK = "user.rollback"

    # Error event
    ERROR = "error"


EventHandler = Callable[..., Awaitable[None]]


@dataclass
class EventBus:
    """Simple event bus for decoupled component communication.

    Reference: opencode's EventV2 service pattern.
    """

    _listeners: dict[DrawEvent, list[EventHandler]] = field(default_factory=dict)

    def on(self, event_type: DrawEvent, handler: EventHandler) -> None:
        self._listeners.setdefault(event_type, []).append(handler)

    def off(self, event_type: DrawEvent, handler: EventHandler) -> None:
        handlers = self._listeners.get(event_type, [])
        if handler in handlers:
            handlers.remove(handler)

    async def emit(self, event_type: DrawEvent, **data: Any) -> None:
        for handler in self._listeners.get(event_type, []):
            await handler(event_type, data)
