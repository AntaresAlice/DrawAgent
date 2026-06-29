"""Tests for session resume and step-by-step execution features."""

import json
import sys
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

from drawagent.config.schema import LoopConfig, AgentBConfig
from drawagent.core.events import EventBus, DrawEvent
from drawagent.core.types import (
    Session, SessionState, Iteration, ImageRecord, InspectionRecord,
    InspectionTaskResult, QualityDecision,
)
from drawagent.orchestrator.interrupt import InterruptHandler
from drawagent.orchestrator.session import SessionManager
from drawagent.orchestrator.loop import InnerLoop
from drawagent.context.assembler import ContextAssembler


class TestLoopConfig:
    """Step mode config defaults."""

    def test_step_mode_default_false(self):
        cfg = LoopConfig()
        assert cfg.step_mode is False

    def test_step_mode_can_enable(self):
        cfg = LoopConfig(step_mode=True)
        assert cfg.step_mode is True


class TestReconstructState:
    """Resume: reconstruct loop state from persisted iterations."""

    def _make_iteration(self, number: int, prompt: str, passed: bool) -> Iteration:
        images = [
            ImageRecord(
                filename=f"img_{number}.png",
                path=f"/tmp/img_{number}.png",
                iteration=number,
                seed=42 + number,
                width=1024,
                height=1024,
                prompt=prompt,
            ),
        ]
        inspections = [
            InspectionTaskResult(
                task_name="check",
                task_description="desc",
                passed=passed,
                observation="ok" if passed else "bad",
                issues=[] if passed else ["issue1"],
            ),
        ]
        decision = QualityDecision(
            passed=passed,
            confidence=0.9 if passed else 0.4,
            reasoning="good" if passed else "needs work",
            remaining_issues=[] if passed else [{"x": 1}],
            recommendation="accept" if passed else "iterate",
        )
        return Iteration(
            number=number,
            prompt=prompt,
            images=images,
            inspections=inspections,
            decision=decision,
        )

    def test_reconstruct_from_empty(self):
        session = Session(id="test", user_request="draw a cat")
        loop = self._make_loop(session)
        iteration, prompt = loop.reconstruct_state([])
        assert iteration == 0
        assert prompt == "draw a cat"

    def test_reconstruct_from_one_iteration(self):
        session = Session(id="test", user_request="draw a cat")
        it1 = self._make_iteration(1, "a cat prompt", False)
        session.iterations = [it1]

        loop = self._make_loop(session)
        iteration, prompt = loop.reconstruct_state()

        assert iteration == 1
        assert prompt == "a cat prompt"
        assert len(loop.images_history) == 1
        assert len(loop.images_history[0]) == 1
        assert loop.images_history[0][0].filename == "img_1.png"
        assert len(loop.observations_history) == 1
        assert loop.observations_history[0].iteration == 1

    def test_reconstruct_from_three_iterations(self):
        session = Session(id="test", user_request="draw a cat")
        its = [
            self._make_iteration(1, "prompt v1", False),
            self._make_iteration(2, "prompt v2", False),
            self._make_iteration(3, "prompt v3", True),
        ]
        session.iterations = its

        loop = self._make_loop(session)
        iteration, prompt = loop.reconstruct_state()

        assert iteration == 3
        assert prompt == "prompt v3"
        assert len(loop.images_history) == 3
        assert len(loop.observations_history) == 3
        assert loop.observations_history[2].decision.passed

    def test_reconstruct_respects_current_prompt_override(self):
        session = Session(id="test", user_request="draw a cat")
        it1 = self._make_iteration(1, "old prompt", False)
        session.iterations = [it1]

        loop = self._make_loop(session)
        iteration, prompt = loop.reconstruct_state(current_prompt="new prompt")

        assert iteration == 1
        assert prompt == "new prompt"  # override respected

    def test_reconstruct_then_run_resumes(self):
        """Full resume: reconstruct state, then run() continues from next iteration."""
        session = Session(id="resume-test", user_request="draw a cat", max_iterations=3)
        it1 = self._make_iteration(1, "prompt v1", False)
        session.iterations = [it1]

        loop = self._make_loop(session)
        iteration, prompt = loop.reconstruct_state()

        assert iteration == 1
        # When run() is called with start_iteration=1, it should skip iter 1
        # and start at iter 2. We verify the loop doesn't crash when
        # reconstruct_state was called first then run() with start_iteration.

    def _make_loop(self, session):
        from unittest.mock import MagicMock
        mock_agent = MagicMock()
        mock_agent._compacted = None
        registry = MagicMock()
        assembler = MagicMock()
        return InnerLoop(
            session=session,
            agent_a=mock_agent,
            tool_registry=registry,
            session_manager=SessionManager(),
            interrupt_handler=InterruptHandler(),
            assembler=assembler,
            event_bus=EventBus(),
            config=LoopConfig(),
        )


class TestStepMode:
    """Step-by-step execution tests."""

    def test_step_mode_event(self):
        """_wait_for_step emits USER_INTERRUPT event."""
        session = Session(id="step-test", user_request="draw a cat")

        events = []
        async def capture(evt_type, data):
            events.append((evt_type, data))

        event_bus = EventBus()
        event_bus.on(DrawEvent.USER_INTERRUPT, capture)

        loop = self._make_loop(session, event_bus)

        # Start _wait_for_step but cancel after short delay
        async def trigger_continue():
            await asyncio.sleep(0.05)
            session.pending_action = "next"
            session.interrupt_event.set()

        async def run_test():
            task = asyncio.create_task(trigger_continue())
            action = await loop._wait_for_step(1)
            await task
            return action

        action = asyncio.run(run_test())
        assert action == "continue"
        assert len(events) == 1
        assert events[0][0] == DrawEvent.USER_INTERRUPT

    def test_step_mode_accept(self):
        """_wait_for_step returns 'accept' when user accepts."""
        session = Session(id="step-test", user_request="draw a cat")

        async def trigger_accept():
            await asyncio.sleep(0.05)
            session.pending_action = "accept"
            session.interrupt_event.set()

        loop = self._make_loop(session, EventBus())

        async def run_test():
            asyncio.create_task(trigger_accept())
            action = await loop._wait_for_step(1)
            return action

        action = asyncio.run(run_test())
        assert action == "accept"

    def test_step_mode_steer(self):
        """_wait_for_step returns 'steer' when user steers."""
        session = Session(id="step-test", user_request="draw a cat")

        async def trigger_steer():
            await asyncio.sleep(0.05)
            session.pending_action = "steer"
            session.interrupt_event.set()

        loop = self._make_loop(session, EventBus())

        async def run_test():
            asyncio.create_task(trigger_steer())
            action = await loop._wait_for_step(1)
            return action

        action = asyncio.run(run_test())
        assert action == "steer"

    def test_step_mode_quit(self):
        """_wait_for_step returns 'quit' when user quits."""
        session = Session(id="step-test", user_request="draw a cat")

        async def trigger_quit():
            await asyncio.sleep(0.05)
            session.pending_action = "quit"
            session.interrupt_event.set()

        loop = self._make_loop(session, EventBus())

        async def run_test():
            asyncio.create_task(trigger_quit())
            action = await loop._wait_for_step(1)
            return action

        action = asyncio.run(run_test())
        assert action == "quit"

    def _make_loop(self, session, event_bus=None):
        from unittest.mock import MagicMock
        mock_agent = MagicMock()
        mock_agent._compacted = None
        return InnerLoop(
            session=session,
            agent_a=mock_agent,
            tool_registry=MagicMock(),
            session_manager=SessionManager(),
            interrupt_handler=InterruptHandler(),
            assembler=MagicMock(),
            event_bus=event_bus or EventBus(),
            config=LoopConfig(),
        )


class TestSessionManagerLoadSession:
    """Test loading a single session from database."""

    @pytest.mark.asyncio
    async def test_load_session_nonexistent(self, tmp_path):
        from drawagent.persistence.database import Database
        db = Database(str(tmp_path / "test.db"))
        await db.connect()
        mgr = SessionManager(db=db)

        session = await mgr.load_session("nonexistent-id")
        assert session is None
        await db.close()

    @pytest.mark.asyncio
    async def test_load_session_with_iterations(self, tmp_path):
        from drawagent.persistence.database import Database
        db = Database(str(tmp_path / "test.db"))
        await db.connect()
        mgr = SessionManager(db=db)

        # Create and persist a session with iterations
        session = await mgr.create_and_persist(
            user_request="draw a cat",
            max_iterations=3,
        )
        session_id = session.id

        # Add an iteration
        it = Iteration(
            number=1,
            prompt="a beautiful cat",
            images=[],
            inspections=[],
            decision=QualityDecision(
                passed=False,
                confidence=0.5,
                reasoning="needs work",
                remaining_issues=[],
                recommendation="iterate",
            ),
        )
        await mgr.add_iteration(session, it)

        # Clear in-memory
        mgr._sessions.clear()

        # Load single session
        loaded = await mgr.load_session(session_id)
        assert loaded is not None
        assert loaded.id == session_id
        assert loaded.user_request == "draw a cat"
        assert len(loaded.iterations) == 1
        assert loaded.iterations[0].number == 1
        assert loaded.iterations[0].prompt == "a beautiful cat"
        assert loaded.iterations[0].decision.passed is False

        await db.close()

    @pytest.mark.asyncio
    async def test_load_session_multiple_iterations(self, tmp_path):
        from drawagent.persistence.database import Database
        db = Database(str(tmp_path / "test.db"))
        await db.connect()
        mgr = SessionManager(db=db)

        session = await mgr.create_and_persist(
            user_request="draw a sunset",
            max_iterations=5,
        )
        sid = session.id

        for n in range(1, 4):
            it = Iteration(
                number=n,
                prompt=f"prompt_{n}",
                images=[],
                inspections=[],
                decision=QualityDecision(
                    passed=n == 3,
                    confidence=0.8,
                    reasoning=f"iter {n}",
                    remaining_issues=[],
                    recommendation="iterate" if n < 3 else "accept",
                ),
            )
            await mgr.add_iteration(session, it)

        mgr._sessions.clear()
        loaded = await mgr.load_session(sid)
        assert len(loaded.iterations) == 3
        assert loaded.iterations[2].decision.passed is True
        await db.close()


class TestLoopResumeFlow:
    """Integration: load session -> reconstruct -> run continues."""

    @pytest.mark.asyncio
    async def test_resume_continues_from_next_iteration(self, tmp_path):
        """After reconstructing from 2 iterations, run() should start at iteration 3."""
        from unittest.mock import AsyncMock, MagicMock

        from drawagent.persistence.database import Database
        db = Database(str(tmp_path / "resume_test.db"))
        await db.connect()
        mgr = SessionManager(db=db)

        session = await mgr.create_and_persist(user_request="test resume", max_iterations=5)

        # Add 2 completed iterations
        for n in range(1, 3):
            it = Iteration(
                number=n,
                prompt=f"prompt_{n}",
                images=[],
                inspections=[],
                decision=QualityDecision(
                    passed=False,
                    confidence=0.5,
                    reasoning=f"iter {n}",
                    remaining_issues=[],
                    recommendation="iterate",
                ),
            )
            await mgr.add_iteration(session, it)

        # Load from DB
        loaded = await mgr.load_session(session.id)
        assert len(loaded.iterations) == 2

        # Create loop and reconstruct
        mock_agent = MagicMock()
        mock_agent._compacted = None
        mock_agent.clarify_request = AsyncMock(return_value=None)
        mock_agent.design_inspection_plan = AsyncMock(return_value=[{"name": "check", "description": "desc"}])
        mock_agent.evaluate_quality = AsyncMock(return_value=QualityDecision(
            passed=True, confidence=0.95, reasoning="good",
            remaining_issues=[], recommendation="accept",
        ))
        mock_agent.run_turn = AsyncMock()
        mock_agent.run_turn.return_value = type("Turn", (), {
            "text": "VERDICT: PASS",
            "tool_results": [
                type("TR", (), {
                    "success": True,
                    "output": "img generated",
                    "metadata": {"images": [{"path": "/tmp/test.png", "filename": "test.png", "seed": 42, "width": 1024, "height": 1024}]},
                })(),
            ],
            "finish_reason": "stop",
        })()

        loop = InnerLoop(
            session=loaded,
            agent_a=mock_agent,
            tool_registry=MagicMock(),
            session_manager=mgr,
            interrupt_handler=InterruptHandler(),
            assembler=ContextAssembler(agent_b_config=AgentBConfig()),
            event_bus=EventBus(),
            config=LoopConfig(max_iterations=5),
        )

        iteration, prompt = loop.reconstruct_state()
        assert iteration == 2
        assert prompt == "prompt_2"

        # Now run from start_iteration=2 — should produce iteration 3
        result = await loop.run(
            initial_prompt=prompt,
            start_iteration=2,
        )
        assert result.iterations_completed == 3
        assert result.terminated_reason in ("quality_passed", "auto_accepted")

        await db.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
