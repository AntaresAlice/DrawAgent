from __future__ import annotations

import os
from pathlib import Path

import aiosqlite

from drawagent.core.errors import SessionError

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS sessions (
    id              TEXT PRIMARY KEY,
    user_request    TEXT NOT NULL DEFAULT '',
    state           TEXT NOT NULL DEFAULT 'idle',
    max_iterations  INTEGER NOT NULL DEFAULT 7,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS iterations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    number          INTEGER NOT NULL,
    prompt          TEXT NOT NULL DEFAULT '',
    gen_params      TEXT NOT NULL DEFAULT '{}',
    decision        TEXT,
    started_at      TEXT NOT NULL DEFAULT (datetime('now')),
    finished_at     TEXT
);

CREATE TABLE IF NOT EXISTS images (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    iteration_id    INTEGER NOT NULL REFERENCES iterations(id) ON DELETE CASCADE,
    filename        TEXT NOT NULL,
    path            TEXT NOT NULL,
    seed            INTEGER NOT NULL,
    width           INTEGER NOT NULL DEFAULT 1024,
    height          INTEGER NOT NULL DEFAULT 1024,
    quality_score   REAL,
    has_artifact    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS inspections (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    iteration_id    INTEGER NOT NULL REFERENCES iterations(id) ON DELETE CASCADE,
    task_name       TEXT NOT NULL,
    task_description TEXT NOT NULL DEFAULT '',
    passed          INTEGER NOT NULL DEFAULT 0,
    observation     TEXT NOT NULL DEFAULT '',
    issues          TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role            TEXT NOT NULL,
    content         TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_iterations_session ON iterations(session_id, number);
CREATE INDEX IF NOT EXISTS idx_images_iteration ON images(iteration_id);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, created_at);
"""


class Database:
    """SQLite database for session persistence.

    Reference: opencode's Database service via Drizzle. DrawAgent uses
    raw aiosqlite for simplicity.
    """

    def __init__(self, path: str | Path = "~/.drawagent/sessions.db"):
        resolved = Path(path).expanduser().resolve()
        resolved.parent.mkdir(parents=True, exist_ok=True)
        self.path = str(resolved)
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> aiosqlite.Connection:
        if self._conn is not None:
            return self._conn
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        await self._migrate()
        return self._conn

    async def _migrate(self) -> None:
        assert self._conn is not None
        await self._conn.executescript(SCHEMA_SQL)
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def execute(self, sql: str, params: tuple = ()) -> aiosqlite.Cursor:
        conn = await self.connect()
        return await conn.execute(sql, params)

    async def commit(self) -> None:
        if self._conn is not None:
            await self._conn.commit()
