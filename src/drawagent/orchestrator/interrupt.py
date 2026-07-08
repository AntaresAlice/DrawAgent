from __future__ import annotations

from drawagent.core.types import Session, SessionState


class InterruptHandler:
    """Handles user interrupts during the generation loop.

    Reference: opencode's Steer mechanism — user control injected at checkpoints.
    DrawAgent uses named Actions for more precise intent (vs opencode's text steer).

    Supported actions:
    - pause: Freeze current state, wait for resume
    - resume: Continue from frozen state
    - accept_current: Accept current image, terminate loop
    - steer: Modify direction with new guidance
    - modify_prompt: Directly edit the current prompt
    - rollback: Return to a previous iteration
    """

    VALID_ACTIONS: dict[str, str] = {
        "pause": "Freeze execution",
        "resume": "Resume execution",
        "accept_current": "Accept current image and stop",
        "steer": "Change direction with new guidance",
        "modify_prompt": "Manually edit the current prompt",
        "rollback": "Roll back to a specific iteration",
    }

    async def handle(
        self,
        session: Session,
        action: str,
        data: dict | None = None,
    ) -> str:
        """Process a user interrupt. Returns the action type for the loop to handle."""
        data = data or {}

        if action == "pause":
            session.state = SessionState.INTERRUPTED
            session.pending_action = "pause"
            session.interrupt_event.set()

        elif action == "resume":
            session.state = SessionState.GENERATING
            session.pending_action = None
            session.interrupt_event.clear()

        elif action == "accept_current":
            session.pending_action = "accept"
            session.interrupt_event.set()

        elif action == "steer":
            session.pending_action = "steer"
            session.steer_message = data.get("message", "")
            session.interrupt_event.set()

        elif action == "modify_prompt":
            session.pending_action = "modify"
            session.steer_message = data.get("prompt", "")
            session.interrupt_event.set()

        elif action == "rollback":
            session.pending_action = "rollback"
            session.steer_message = str(data.get("target_iteration", 0))
            session.interrupt_event.set()

        return action
