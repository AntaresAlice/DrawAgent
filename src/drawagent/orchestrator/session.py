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
