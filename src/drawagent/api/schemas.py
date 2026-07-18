"""API request/response Pydantic models."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class CreateSessionRequest(BaseModel):
    user_request: str = ""
    max_iterations: int = Field(default=7, ge=1, le=20)


class CreateSessionResponse(BaseModel):
    session_id: str


class SendMessageRequest(BaseModel):
    text: str
    generation_params: dict | None = None


class SendMessageResponse(BaseModel):
    session_id: str
    accepted: bool
    message_id: str


class InterruptRequest(BaseModel):
    action: str  # pause | resume | accept_current | steer | modify_prompt | rollback
    data: dict | None = None


class InterruptResponse(BaseModel):
    session_id: str
    action: str
    accepted: bool


class ImageRef(BaseModel):
    path: str
    filename: str
    seed: int
    width: int
    height: int
    iteration: int


class IterationSummary(BaseModel):
    number: int
    prompt: str
    images: list[ImageRef] = Field(default_factory=list)
    inspections: list[dict] = Field(default_factory=list)
    passed: bool = False
    decision_reasoning: str = ""


class SessionInfo(BaseModel):
    id: str
    created_at: str
    state: str
    user_request: str
    iteration_count: int


class SessionHistoryResponse(BaseModel):
    session_id: str
    user_request: str
    state: str
    iterations: list[IterationSummary] = Field(default_factory=list)
    messages: list[dict] = Field(default_factory=list)
    agentic_turns: list[dict] = Field(default_factory=list)
    engine: str = "classic"


class ServerStatus(BaseModel):
    status: str = "ok"
    version: str = "0.1.0"
    sessions_count: int = 0
