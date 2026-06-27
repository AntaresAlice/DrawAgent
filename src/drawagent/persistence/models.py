from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class SessionRecord:
    """Persistent session row."""

    id: str
    user_request: str = ""
    state: str = "idle"
    max_iterations: int = 7
    created_at: str = ""
    updated_at: str = ""

    @classmethod
    def from_row(cls, row: dict) -> SessionRecord:
        return cls(
            id=row["id"],
            user_request=row["user_request"],
            state=row["state"],
            max_iterations=row["max_iterations"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


@dataclass
class IterationRecord:
    """Persistent iteration row."""

    id: int | None = None
    session_id: str = ""
    number: int = 0
    prompt: str = ""
    gen_params: str = "{}"
    decision: str | None = None
    started_at: str = ""
    finished_at: str | None = None

    @classmethod
    def from_row(cls, row: dict) -> IterationRecord:
        return cls(
            id=row["id"],
            session_id=row["session_id"],
            number=row["number"],
            prompt=row["prompt"],
            gen_params=row["gen_params"],
            decision=row["decision"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
        )


@dataclass
class ImageRecord:
    """Persistent image row."""

    id: int | None = None
    iteration_id: int = 0
    filename: str = ""
    path: str = ""
    seed: int = -1
    width: int = 1024
    height: int = 1024
    quality_score: float | None = None
    has_artifact: bool = False

    @classmethod
    def from_row(cls, row: dict) -> ImageRecord:
        return cls(
            id=row["id"],
            iteration_id=row["iteration_id"],
            filename=row["filename"],
            path=row["path"],
            seed=row["seed"],
            width=row["width"],
            height=row["height"],
            quality_score=row["quality_score"],
            has_artifact=bool(row["has_artifact"]),
        )


@dataclass
class MessageRecord:
    """Persistent message row."""

    id: int | None = None
    session_id: str = ""
    role: str = ""
    content: str = ""
    created_at: str = ""

    @classmethod
    def from_row(cls, row: dict) -> MessageRecord:
        return cls(
            id=row["id"],
            session_id=row["session_id"],
            role=row["role"],
            content=row["content"],
            created_at=row["created_at"],
        )
