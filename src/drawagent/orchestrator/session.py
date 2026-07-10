from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime
from pathlib import Path

from drawagent.core.errors import SessionError
from drawagent.core.types import (
    ImageRecord, InspectionRecord, InspectionTaskResult, Iteration,
    QualityDecision, Session, SessionState,
)


class SessionManager:
    """Manages Session lifecycle: create, get, delete, state transitions.

    Supports optional SQLite persistence via Database.
    """

    def __init__(self, db=None):
        self._sessions: dict[str, Session] = {}
        self._db = db

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

    async def create_and_persist(self, user_request: str = "", max_iterations: int = 7) -> Session:
        """Create a session and immediately persist to database."""
        session = self.create(user_request=user_request, max_iterations=max_iterations)
        if self._db is not None:
            await self._db.execute(
                "INSERT OR REPLACE INTO sessions (id, user_request, state, max_iterations, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, datetime('now'))",
                (session.id, session.user_request, session.state.value, session.max_iterations, session.created_at.isoformat()),
            )
            await self._db.commit()
        return session

    async def persist_session(self, session: Session) -> None:
        """Write session record to database."""
        if self._db is None:
            return
        await self._db.execute(
            "INSERT OR REPLACE INTO sessions (id, user_request, state, max_iterations, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, datetime('now'))",
            (session.id, session.user_request, session.state.value, session.max_iterations, session.created_at.isoformat()),
        )
        await self._db.commit()

    def get(self, session_id: str) -> Session:
        session = self._sessions.get(session_id)
        if session is None:
            raise SessionError(f"Session not found: {session_id}")
        return session

    def get_or_none(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)

    async def delete(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
        if self._db is not None:
            await self._db.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            await self._db.commit()

    def list_ids(self) -> list[str]:
        return list(self._sessions.keys())

    def transition(self, session: Session, new_state: SessionState) -> None:
        session.state = new_state

    async def add_iteration(self, session: Session, iteration: Iteration) -> None:
        session.iterations.append(iteration)

        if self._db is None:
            return

        gen_params_json = json.dumps(iteration.gen_params or {}, ensure_ascii=False)
        decision_json = None
        if iteration.decision:
            decision_json = json.dumps({
                "passed": iteration.decision.passed,
                "confidence": iteration.decision.confidence,
                "reasoning": iteration.decision.reasoning,
                "recommendation": iteration.decision.recommendation,
            }, ensure_ascii=False)

        cursor = await self._db.execute(
            "INSERT INTO iterations (session_id, number, prompt, gen_params, decision, started_at, finished_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (session.id, iteration.number, iteration.prompt, gen_params_json,
             decision_json, iteration.started_at.isoformat() if iteration.started_at else datetime.now().isoformat(),
             iteration.finished_at.isoformat() if iteration.finished_at else datetime.now().isoformat()),
        )
        iter_id = cursor.lastrowid

        for img in iteration.images:
            await self._db.execute(
                "INSERT INTO images (iteration_id, filename, path, seed, width, height, quality_score, has_artifact) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (iter_id, img.filename, img.path, img.seed, img.width, img.height,
                 img.quality_score, 1 if img.has_critical_artifact else 0),
            )

        for insp in iteration.inspections:
            issues_json = json.dumps(insp.issues or [], ensure_ascii=False)
            await self._db.execute(
                "INSERT INTO inspections (iteration_id, task_name, task_description, passed, observation, issues) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (iter_id, insp.task_name, insp.task_description, 1 if insp.passed else 0, insp.observation, issues_json),
            )

        await self._db.commit()

    async def load_all(self) -> list[Session]:
        """Restore all sessions from database into memory."""
        if self._db is None:
            return []

        rows = await self._db.execute("SELECT * FROM sessions ORDER BY created_at DESC")
        session_rows = await rows.fetchall()

        sessions = []
        for srow in session_rows:
            session = Session(
                id=srow["id"],
                created_at=datetime.fromisoformat(srow["created_at"]) if srow["created_at"] else datetime.now(),
                user_request=srow["user_request"] or "",
                max_iterations=srow["max_iterations"] or 7,
            )
            session.state = SessionState(srow["state"]) if srow["state"] else SessionState.IDLE

            iter_rows = await self._db.execute(
                "SELECT * FROM iterations WHERE session_id = ? ORDER BY number",
                (session.id,),
            )
            for irow in await iter_rows.fetchall():
                iteration = Iteration(
                    number=irow["number"],
                    prompt=irow["prompt"] or "",
                    gen_params=json.loads(irow["gen_params"]) if irow["gen_params"] else {},
                    started_at=datetime.fromisoformat(irow["started_at"]) if irow["started_at"] else datetime.now(),
                    finished_at=datetime.fromisoformat(irow["finished_at"]) if irow["finished_at"] else None,
                )

                if irow["decision"]:
                    d = json.loads(irow["decision"])
                    iteration.decision = QualityDecision(
                        passed=d.get("passed", False),
                        confidence=d.get("confidence", 0.5),
                        reasoning=d.get("reasoning", ""),
                        recommendation=d.get("recommendation", "iterate"),
                    )

                img_rows = await self._db.execute(
                    "SELECT * FROM images WHERE iteration_id = ?", (irow["id"],)
                )
                for imrow in await img_rows.fetchall():
                    iteration.images.append(ImageRecord(
                        filename=imrow["filename"] or "",
                        path=imrow["path"] or "",
                        iteration=iteration.number,
                        seed=imrow["seed"] or -1,
                        width=imrow["width"] or 1024,
                        height=imrow["height"] or 1024,
                        quality_score=imrow["quality_score"],
                        has_critical_artifact=bool(imrow["has_artifact"]),
                        prompt=iteration.prompt,
                    ))

                insp_rows = await self._db.execute(
                    "SELECT * FROM inspections WHERE iteration_id = ?", (irow["id"],)
                )
                for insrow in await insp_rows.fetchall():
                    iteration.inspections.append(InspectionTaskResult(
                        task_name=insrow["task_name"] or "",
                        task_description=insrow["task_description"] or "",
                        passed=bool(insrow["passed"]),
                        observation=insrow["observation"] or "",
                        issues=json.loads(insrow["issues"]) if insrow["issues"] else [],
                    ))

                session.iterations.append(iteration)

            self._sessions[session.id] = session
            sessions.append(session)

        return sessions

    async def load_session(self, session_id: str) -> Session | None:
        """Load a single session by ID from database with all iterations.

        Returns None if session not found.
        """
        if self._db is None:
            return None

        row = await self._db.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        )
        srows = await row.fetchall()
        if not srows:
            return None
        srow = srows[0]

        session = Session(
            id=srow["id"],
            created_at=datetime.fromisoformat(srow["created_at"]) if srow["created_at"] else datetime.now(),
            user_request=srow["user_request"] or "",
            max_iterations=srow["max_iterations"] or 7,
        )
        session.state = SessionState(srow["state"]) if srow["state"] else SessionState.IDLE

        iter_rows = await self._db.execute(
            "SELECT * FROM iterations WHERE session_id = ? ORDER BY number",
            (session.id,),
        )
        for irow in await iter_rows.fetchall():
            iteration = Iteration(
                number=irow["number"],
                prompt=irow["prompt"] or "",
                gen_params=json.loads(irow["gen_params"]) if irow["gen_params"] else {},
                started_at=datetime.fromisoformat(irow["started_at"]) if irow["started_at"] else datetime.now(),
                finished_at=datetime.fromisoformat(irow["finished_at"]) if irow["finished_at"] else None,
            )

            if irow["decision"]:
                d = json.loads(irow["decision"])
                iteration.decision = QualityDecision(
                    passed=d.get("passed", False),
                    confidence=d.get("confidence", 0.5),
                    reasoning=d.get("reasoning", ""),
                    recommendation=d.get("recommendation", "iterate"),
                )

            img_rows = await self._db.execute(
                "SELECT * FROM images WHERE iteration_id = ?", (irow["id"],)
            )
            for imrow in await img_rows.fetchall():
                iteration.images.append(ImageRecord(
                    filename=imrow["filename"] or "",
                    path=imrow["path"] or "",
                    iteration=iteration.number,
                    seed=imrow["seed"] or -1,
                    width=imrow["width"] or 1024,
                    height=imrow["height"] or 1024,
                    quality_score=imrow["quality_score"],
                    has_critical_artifact=bool(imrow["has_artifact"]),
                    prompt=iteration.prompt,
                ))

            insp_rows = await self._db.execute(
                "SELECT * FROM inspections WHERE iteration_id = ?", (irow["id"],)
            )
            for insrow in await insp_rows.fetchall():
                iteration.inspections.append(InspectionTaskResult(
                    task_name=insrow["task_name"] or "",
                    task_description=insrow["task_description"] or "",
                    passed=bool(insrow["passed"]),
                    observation=insrow["observation"] or "",
                    issues=json.loads(insrow["issues"]) if insrow["issues"] else [],
                ))

            session.iterations.append(iteration)

        self._sessions[session.id] = session
        return session

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

    # ===== Agentic mode DB operations (LLM-driven loop) =====

    async def save_agentic_message(self, session_id: str, msg_id: str, seq: int,
                                   delivery: str, text: str,
                                   admitted_at: str, promoted_at: str | None = None) -> None:
        if self._db is None:
            return
        await self._db.execute(
            "INSERT OR REPLACE INTO agentic_messages (id, session_id, seq, delivery, text, admitted_at, promoted_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (msg_id, session_id, seq, delivery, text, admitted_at, promoted_at),
        )
        await self._db.commit()

    async def promote_agentic_messages(self, session_id: str, delivery: str,
                                       cutoff_seq: int | None = None) -> int:
        if self._db is None:
            return 0
        now = datetime.now().isoformat()
        if cutoff_seq is not None:
            cursor = await self._db.execute(
                "UPDATE agentic_messages SET promoted_at = ? "
                "WHERE session_id = ? AND delivery = ? AND promoted_at IS NULL AND seq <= ?",
                (now, session_id, delivery, cutoff_seq),
            )
        else:
            cursor = await self._db.execute(
                "UPDATE agentic_messages SET promoted_at = ? "
                "WHERE session_id = ? AND delivery = ? AND promoted_at IS NULL",
                (now, session_id, delivery),
            )
        await self._db.commit()
        return cursor.rowcount

    async def has_pending_agentic_messages(self, session_id: str, delivery: str) -> bool:
        if self._db is None:
            return False
        cursor = await self._db.execute(
            "SELECT COUNT(*) as cnt FROM agentic_messages "
            "WHERE session_id = ? AND delivery = ? AND promoted_at IS NULL",
            (session_id, delivery),
        )
        row = await cursor.fetchone()
        return row["cnt"] > 0 if row else False

    async def save_agentic_turn(self, session_id: str, turn_id: str, seq: int,
                                user_msg_id: str | None, assistant_text: str | None,
                                finish_reason: str | None, tokens_used: int,
                                started_at: str | None, completed_at: str | None) -> None:
        if self._db is None:
            return
        await self._db.execute(
            "INSERT OR REPLACE INTO agentic_turns (id, session_id, seq, user_msg_id, assistant_text, "
            "finish_reason, tokens_used, started_at, completed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (turn_id, session_id, seq, user_msg_id, assistant_text, finish_reason,
             tokens_used, started_at, completed_at),
        )
        await self._db.commit()

    async def save_agentic_tool_call(self, session_id: str, turn_id: str,
                                     call_id: str, tool_name: str, arguments: str,
                                     status: str, result: str | None = None,
                                     error: str | None = None,
                                     started_at: str | None = None,
                                     completed_at: str | None = None) -> None:
        if self._db is None:
            return
        await self._db.execute(
            "INSERT OR REPLACE INTO agentic_tool_calls (id, turn_id, session_id, tool_name, arguments, "
            "status, result, error, started_at, completed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (call_id, turn_id, session_id, tool_name, arguments, status, result, error, started_at, completed_at),
        )
        await self._db.commit()

    async def save_agentic_compaction(self, session_id: str, comp_id: str, seq: int,
                                      summary: str, recent_context: str | None,
                                      compacted_turn_count: int, created_at: str) -> None:
        if self._db is None:
            return
        await self._db.execute(
            "INSERT OR REPLACE INTO agentic_compactions (id, session_id, seq, summary, recent_context, "
            "compacted_turn_count, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (comp_id, session_id, seq, summary, recent_context, compacted_turn_count, created_at),
        )
        await self._db.commit()

    async def save_agentic_lesson(self, session_id: str, lesson_id: str, seq: int,
                                  lesson: str, created_at: str) -> None:
        if self._db is None:
            return
        await self._db.execute(
            "INSERT OR REPLACE INTO agentic_lessons (id, session_id, seq, lesson, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (lesson_id, session_id, seq, lesson, created_at),
        )
        await self._db.commit()

    # ===== Agentic mode DB load operations =====

    async def load_agentic_messages(self, session_id: str) -> list[dict]:
        """Load user messages for an agentic session (for history display)."""
        if self._db is None:
            return []
        cursor = await self._db.execute(
            "SELECT id, seq, delivery, text, admitted_at, promoted_at "
            "FROM agentic_messages WHERE session_id = ? ORDER BY seq",
            (session_id,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def load_agentic_turns(self, session_id: str) -> list[dict]:
        """Load all turns with their tool calls for an agentic session."""
        if self._db is None:
            return []
        cursor = await self._db.execute(
            "SELECT id, seq, user_msg_id, assistant_text, finish_reason, "
            "tokens_used, started_at, completed_at "
            "FROM agentic_turns WHERE session_id = ? ORDER BY seq",
            (session_id,),
        )
        turn_rows = await cursor.fetchall()
        turns: list[dict] = []
        for tr in turn_rows:
            turn = dict(tr)
            tc_cursor = await self._db.execute(
                "SELECT call_id as id, tool_name, arguments, status, result, error, "
                "started_at, completed_at "
                "FROM agentic_tool_calls WHERE turn_id = ? ORDER BY call_id",
                (turn["id"],),
            )
            tc_rows = await tc_cursor.fetchall()
            turn["tool_calls"] = [dict(tc) for tc in tc_rows]
            turns.append(turn)
        return turns

    async def load_agentic_session(self, session_id: str):
        """Rebuild an AgenticSession from the database.
        Returns (AgenticSession, InputQueue) or None if no data exists.
        """
        from drawagent.models.agentic_session import (
            AgenticSession, AgenticUserMessage, AgenticTurn, AgenticToolCall, InputQueue,
        )
        msgs = await self.load_agentic_messages(session_id)
        raw_turns = await self.load_agentic_turns(session_id)
        if not msgs and not raw_turns:
            return None

        session = AgenticSession(id=session_id)

        # Restore messages
        for m in msgs:
            msg = AgenticUserMessage(
                text=m.get("text", ""),
                id=m.get("id", ""),
                delivery=m.get("delivery", "queue"),
                seq=m.get("seq", 0),
            )
            if m.get("promoted_at"):
                msg.promoted_at = datetime.fromisoformat(m["promoted_at"])
            session.messages.append(msg)

        # Restore turns with tool calls
        for rt in raw_turns:
            tool_calls = []
            for tc in rt.get("tool_calls", []):
                atc = AgenticToolCall(
                    call_id=tc.get("id", ""),
                    tool_name=tc.get("tool_name", ""),
                    arguments=json.loads(tc["arguments"]) if tc.get("arguments") and tc["arguments"] != "{}" else {},
                    status=tc.get("status", "completed"),
                    result=json.loads(tc["result"]) if tc.get("result") else None,
                    error=tc.get("error"),
                )
                if tc.get("started_at"):
                    atc.started_at = datetime.fromisoformat(tc["started_at"])
                if tc.get("completed_at"):
                    atc.completed_at = datetime.fromisoformat(tc["completed_at"])
                tool_calls.append(atc)

            # Find the user message for this turn (by user_msg_id)
            user_msg = None
            if rt.get("user_msg_id"):
                for m in session.messages:
                    if m.id == rt["user_msg_id"]:
                        user_msg = m
                        break
            elif session.messages:
                user_msg = session.messages[0]

            turn = AgenticTurn(
                id=rt.get("id", ""),
                user_message=user_msg,
                assistant_text=rt.get("assistant_text"),
                tool_calls=tool_calls,
                finish_reason=rt.get("finish_reason"),
                tokens_used=rt.get("tokens_used", 0),
            )
            if rt.get("started_at"):
                turn.started_at = datetime.fromisoformat(rt["started_at"])
            if rt.get("completed_at"):
                turn.completed_at = datetime.fromisoformat(rt["completed_at"])
            session.turns.append(turn)

        queue = InputQueue(session_id, self)
        return session, queue
        await self._db.commit()
