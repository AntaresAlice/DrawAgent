"""Agentic loop — LLM-driven outer+inner iteration for DrawAgent.

Analogous to opencode's SessionRunner.run() with while(shouldRun) outer loop
and while(needsContinuation) inner loop for tool-call chaining.

Classic 5-phase loop (orchestrator/loop.py) is fully preserved and untouched.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import TYPE_CHECKING

from drawagent.core.events import EventBus, DrawEvent
from drawagent.orchestrator.guardrails import SessionGuardrails
from drawagent.orchestrator.context_builder import ContextBuilder
from drawagent.models.agentic_session import (
    AgenticSession, AgenticTurn, AgenticUserMessage,
    AgenticTurnResult, InputQueue,
)
from drawagent.providers.base import LLMMessage

if TYPE_CHECKING:
    from drawagent.agents.agent_a import AgentA
    from drawagent.tools.base import ToolRegistry
    from drawagent.orchestrator.session import SessionManager

logger = logging.getLogger("drawagent.agentic_loop")


class AgenticLoop:
    """LLM-driven generation loop for agentic mode.

    Owned by ServerRunner, created per session execution.
    """

    def __init__(
        self,
        session: AgenticSession,
        agent_a: "AgentA",
        registry: "ToolRegistry",
        config: dict,
        event_bus: EventBus,
        session_manager: "SessionManager",
        verbose: bool = False,
    ):
        self.session = session
        self.agent_a = agent_a
        self.registry = registry
        self.event_bus = event_bus
        self.session_manager = session_manager
        self.verbose = verbose
        agentic_cfg = config.get("agentic", {}) if isinstance(config, dict) else {}
        self._agentic_cfg = agentic_cfg
        self.guardrails = SessionGuardrails(agentic_cfg)
        self.max_agentic_rounds = agentic_cfg.get("max_agentic_rounds", 20)
        self.max_tool_rounds = agentic_cfg.get("max_tool_rounds", 10)
        self.compaction_enabled = (
            agentic_cfg.get("compaction", {}).get("enabled", True)
        )
        self.learning_enabled = (
            agentic_cfg.get("learning", {}).get("enabled", True)
        )
        self.ctx_builder = ContextBuilder(
            agentic_cfg, agent_a_config=config.get("agent_a", {}),
            agent_b_config=config.get("agent_b"),
            registry=registry,
        )
        self.queue: InputQueue | None = None

    def set_queue(self, queue: InputQueue) -> None:
        self.queue = queue

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    async def run(self, force_prompt: str | None = None) -> AgenticSession:
        """Run the agentic loop.

        Args:
            force_prompt: If provided, runs immediately without checking the queue.
                          Used for e2e tests and direct-execution scenarios.
        """
        if force_prompt:
            # Admit as queue item marked promoted so it doesn't cause duplicates
            self.session.messages.append(AgenticUserMessage(
                text=force_prompt,
                delivery="queue",
                seq=1,
                promoted_at=datetime.now(),  # already delivered
            ))

        outer_round = 0
        needs_rerun = True
        force_first_run = force_prompt is not None and len(self.session.turns) == 0

        while needs_rerun and outer_round < self.max_agentic_rounds:
            needs_rerun = False

            # ── Check if we have anything to do ──
            if not force_first_run:
                if self.queue and not await self.queue.has_pending("queue"):
                    if not await self.queue.has_pending("steer"):
                        undelivered = [m for m in self.session.messages if m.promoted_at is None and m.delivery == "queue"]
                        if not undelivered:
                            break
                    else:
                        await self.queue.promote_steers()
                elif self.queue:
                    await self.queue.promote_next_queued()
                    await self.queue.promote_steers()
            force_first_run = False

            # ── Guardrail: outer round limit ──
            if self.guardrails.check_agentic_rounds(outer_round):
                await self.event_bus.emit(DrawEvent.ERROR, **{
                    "message": f"Agentic max rounds reached ({self.max_agentic_rounds})",
                    "session_id": self.session.id,
                })
                break

            # ── INNER LOOP: tool-call chaining ──
            tool_round = 0
            needs_continuation = True
            _force_injected = False  # prevent infinite force-finalize injection
            self._consecutive_empty = 0  # guardrail: consecutive empty LLM responses
            self._consecutive_no_image = 0  # guardrail: consecutive turns without image gen

            while needs_continuation:
                # Guardrail: tool round limit (inject once, break on next round if ignored)
                if self.guardrails.check_tool_rounds(tool_round):
                    if _force_injected:
                        logger.warning("Force-finalize injected but LLM did not finalize — breaking")
                        self.session.errors.append({
                            "type": "max_tool_rounds",
                            "message": "LLM failed to call finalize after force instruction",
                        })
                        needs_continuation = False
                        break
                    self._inject_force_finalize_message()
                    _force_injected = True

                # 1. Build context
                system_prompt = self.ctx_builder.build_system_prompt(self.session)
                messages = self.ctx_builder.build_messages(self.session)
                materialization = self.registry.materialize_all()

                # 2. Compact if needed
                if self.compaction_enabled:
                    if self.guardrails.check_token_budget(
                        system_prompt, messages, materialization.definitions
                    ):
                        from drawagent.orchestrator.compactor import ContextCompactor
                        compactor = ContextCompactor(self.agent_a, {"agentic": self._agentic_cfg})
                        if await compactor.compact_if_needed(
                            self.session, system_prompt, messages, materialization.definitions
                        ):
                            system_prompt = self.ctx_builder.build_system_prompt(self.session)
                            messages = self.ctx_builder.build_messages(self.session)
                            await self.event_bus.emit("session.compacted", {
                                "session_id": self.session.id,
                            })

                # 3. Emit turn.started
                await self.event_bus.emit("turn.started", {
                    "session_id": self.session.id,
                })

                # 4. LLM call
                result = await self.agent_a.run_agentic_turn(
                    system_prompt=system_prompt,
                    messages=messages,
                    tools=materialization.definitions,
                    event_bus=self.event_bus,
                    verbose=self.verbose,
                )

                # 4b. Guardrail: empty responses
                if not result.text.strip() and not result.tool_results:
                    self._consecutive_empty += 1
                    if self.guardrails.check_empty_responses(self._consecutive_empty):
                        logger.warning("Too many empty responses — breaking inner loop")
                        self.session.errors.append({
                            "type": "empty_responses",
                            "message": f"LLM returned {self._consecutive_empty} empty responses",
                        })
                        needs_continuation = False
                        break
                else:
                    self._consecutive_empty = 0

                # 4c. Guardrail: no image generated
                has_gen = any(tc.tool_name == "generate_image" for tc in result.tool_results)
                if result.tool_results and not has_gen:
                    self._consecutive_no_image += 1
                    if self.guardrails.check_no_image_generated(self._consecutive_no_image):
                        logger.warning("Too many turns without generate_image — forcing finalize")
                        self._inject_force_finalize_message()
                        _force_injected = True
                elif has_gen:
                    self._consecutive_no_image = 0

                # 5. Emit turn.ended
                await self.event_bus.emit("turn.ended", {
                    "session_id": self.session.id,
                    "finish_reason": result.finish_reason,
                    "finalized": result.finalized,
                    "tokens_used": result.tokens_used,
                })

                # 6. Record turn (first turn carries initial message, subsequent turns don't)
                if len(self.session.turns) == 0 and self.session.messages:
                    turn_user_msg = self.session.messages[-1]
                else:
                    turn_user_msg = None
                turn = AgenticTurn(
                    user_message=turn_user_msg,
                    assistant_text=result.text,
                    tool_calls=result.tool_results,
                    finish_reason=result.finish_reason,
                    tokens_used=result.tokens_used,
                    started_at=datetime.now(),
                    completed_at=datetime.now(),
                )
                self.session.turns.append(turn)
                await self._persist_turn(turn)

                # 7. Determine continuity
                if result.finalized:
                    if self._verify_finalize(result):
                        needs_continuation = False
                        await self.event_bus.emit("session.finalized", {
                            "session_id": self.session.id,
                            "message": "Task completed successfully.",
                        })
                    else:
                        self.session.finalize_rejection_count += 1
                        if self.guardrails.check_finalize_rejections(self.session):
                            self._inject_finalize_rejection_message()
                        needs_continuation = True
                        tool_round += 1
                elif result.tool_results and tool_round < self.max_tool_rounds:
                    needs_continuation = True
                    tool_round += 1
                else:
                    needs_continuation = self._needs_continuation_check(result)
                    if needs_continuation:
                        tool_round += 1

                # 8. After settlement, check for new steer
                if not needs_continuation:
                    if self.queue and await self.queue.has_pending("steer"):
                        await self.queue.promote_steers()
                        needs_continuation = True
                        needs_rerun = True

            # 9. Reflect (learning) — inserted at outer loop level
            if self.learning_enabled and self.session.iterations:
                from drawagent.orchestrator.learner import ExperienceLearner
                learner = ExperienceLearner(self.agent_a, {"agentic": self._agentic_cfg})
                learner.set_event_bus(self.event_bus)
                await learner.reflect(self.session)

            # 10. Check for next queue item
            if self.queue and await self.queue.has_pending("queue"):
                needs_rerun = True

            outer_round += 1

        self.session.updated_at = datetime.now()
        return self.session

    # ------------------------------------------------------------------
    # Continuation / verification helpers
    # ------------------------------------------------------------------

    def _needs_continuation_check(self, result: AgenticTurnResult) -> bool:
        """Determine if the loop should continue after LLM returned text-only.

        Returns True = need to continue (ask LLM to do more).
        Returns False = can stop (LLM's answer is final).

        Logic:
        - Empty text → always continue (nothing produced)
        - Text but no image iterations yet → continue (LLM hasn't generated anything)
        - Text + images exist → allow stopping (LLM's judgment stands)
        """
        if not result.text or not result.text.strip():
            return True
        if not self.session.iterations:
            return True
        return False

    def _verify_finalize(self, result: AgenticTurnResult) -> bool:
        """Verify LLM's finalize declaration against actual inspection results.

        Walks backward through iterations to find the most recent inspection
        results. Returns True if all recent inspections passed, False if
        any failed. If no inspections exist at all, accepts the finalize
        (LLM is trusted, but this is logged).

        Returns True if finalize passes verification, False if rejected.
        """
        finalize_call = next(
            (tc for tc in result.tool_results
             if tc.tool_name == "finalize" and tc.status == "completed"),
            None
        )
        if not finalize_call:
            return False

        if not self.session.iterations:
            return True  # No inspections to verify against → accept

        for last in reversed(self.session.iterations):
            inspections = last.inspections
            if not inspections:
                continue
            fails = [i for i in inspections if not i.get("passed", True)]
            return len(fails) == 0

        return True  # No inspections found in any iteration → accept

    # ------------------------------------------------------------------
    # Message injection helpers
    # ------------------------------------------------------------------

    def _inject_finalize_rejection_message(self) -> None:
        """Inject system message explaining why finalize was rejected.

        Tells the LLM exactly which inspection items failed so it can fix them.
        """
        if not self.session.iterations:
            return
        last = self.session.iterations[-1]
        fails = [i for i in last.inspections if not i.get("passed", True)]
        fail_lines = []
        for f in fails:
            fail_lines.append(
                f"- [{f.get('task_name', '?')}] {f.get('observation', 'no detail')}"
            )
        msg_text = (
            "Your finalize was rejected because the following inspection checks FAILED:\n"
            + "\n".join(fail_lines)
            + "\n\nPlease fix these specific issues before calling finalize again. "
            "Do NOT call finalize until all FAIL items are resolved."
        )
        msg = AgenticUserMessage(
            text=msg_text,
            delivery="steer",
            promoted_at=datetime.now(),
        )
        self.session.messages.append(msg)

    def _inject_force_finalize_message(self) -> None:
        """Inject message forcing LLM to finalize (tool round limit reached)."""
        msg_text = (
            f"Maximum tool call rounds ({self.max_tool_rounds}) reached. "
            "You MUST call finalize NOW with whatever results you have. "
            "Be honest about any quality issues in the reason field."
        )
        msg = AgenticUserMessage(
            text=msg_text,
            delivery="steer",
            promoted_at=datetime.now(),
        )
        self.session.messages.append(msg)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    async def _persist_turn(self, turn: AgenticTurn) -> None:
        """Save turn + tool calls to DB."""
        try:
            seq = len(self.session.turns)
            await self.session_manager.save_agentic_turn(
                session_id=self.session.id,
                turn_id=turn.id,
                seq=seq,
                user_msg_id=turn.user_message.id if turn.user_message else None,
                assistant_text=turn.assistant_text,
                finish_reason=turn.finish_reason,
                tokens_used=turn.tokens_used,
                started_at=turn.started_at.isoformat() if turn.started_at else None,
                completed_at=turn.completed_at.isoformat() if turn.completed_at else None,
            )
            for tc in turn.tool_calls:
                await self.session_manager.save_agentic_tool_call(
                    session_id=self.session.id,
                    turn_id=turn.id,
                    call_id=tc.call_id,
                    tool_name=tc.tool_name,
                    arguments=str(tc.arguments),
                    status=tc.status,
                    result=str(tc.result) if tc.result else None,
                    error=tc.error,
                    started_at=tc.started_at.isoformat() if tc.started_at else None,
                    completed_at=tc.completed_at.isoformat() if tc.completed_at else None,
                )
        except Exception as exc:
            logger.warning("Failed to persist turn %s: %s", turn.id, exc)
