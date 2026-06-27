from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException
from starlette.responses import FileResponse
from fastapi.responses import JSONResponse

from .schemas import (
    CreateSessionRequest,
    CreateSessionResponse,
    ImageRef,
    InterruptRequest,
    InterruptResponse,
    IterationSummary,
    SendMessageRequest,
    SendMessageResponse,
    ServerStatus,
    SessionHistoryResponse,
    SessionInfo,
)

router = APIRouter(prefix="/api")

_sessions_store: dict[str, "Session"] = {}
_message_ids: dict[str, list[dict]] = {}
_output_dir = Path("./outputs")


def init_routes(session_manager, interrupt_handler, output_dir: str = "./outputs"):
    """Initialize routes with dependencies."""
    global _session_manager, _interrupt_handler, _output_dir
    _session_manager = session_manager
    _interrupt_handler = interrupt_handler
    _output_dir = Path(output_dir).resolve()
    _output_dir.mkdir(parents=True, exist_ok=True)


@router.get("/status", response_model=ServerStatus)
async def get_status():
    return ServerStatus(
        status="ok",
        version="0.1.0",
        sessions_count=len(_session_manager.list_ids()) if _session_manager else 0,
    )


@router.post("/sessions", response_model=CreateSessionResponse)
async def create_session(req: CreateSessionRequest):
    session = _session_manager.create(
        user_request=req.user_request,
        max_iterations=req.max_iterations,
    )
    _sessions_store[session.id] = session
    _message_ids[session.id] = []
    return CreateSessionResponse(session_id=session.id)


@router.get("/sessions", response_model=list[SessionInfo])
async def list_sessions():
    result = []
    for sid in _session_manager.list_ids():
        session = _session_manager.get(sid)
        result.append(SessionInfo(
            id=session.id,
            created_at=session.created_at.isoformat(),
            state=session.state.value,
            user_request=session.user_request,
            iteration_count=len(session.iterations),
        ))
    return result


@router.post("/sessions/{session_id}/message", response_model=SendMessageResponse)
async def send_message(session_id: str, req: SendMessageRequest):
    session = _session_manager.get_or_none(session_id)
    if session is None:
        raise HTTPException(404, "Session not found")

    message_id = str(uuid.uuid4())[:8]
    _message_ids.setdefault(session_id, []).append({
        "id": message_id,
        "role": "user",
        "content": req.text,
        "created_at": datetime.now().isoformat(),
    })

    return SendMessageResponse(
        session_id=session_id,
        accepted=True,
        message_id=message_id,
    )


@router.post("/sessions/{session_id}/interrupt", response_model=InterruptResponse)
async def interrupt_session(session_id: str, req: InterruptRequest):
    session = _session_manager.get_or_none(session_id)
    if session is None:
        raise HTTPException(404, "Session not found")

    await _interrupt_handler.handle(session, req.action, req.data)
    return InterruptResponse(
        session_id=session_id,
        action=req.action,
        accepted=True,
    )


@router.get("/sessions/{session_id}/history", response_model=SessionHistoryResponse)
async def get_history(session_id: str):
    session = _session_manager.get_or_none(session_id)
    if session is None:
        raise HTTPException(404, "Session not found")

    iterations = []
    for it in session.iterations:
        images = [
            ImageRef(
                path=img.path,
                filename=img.filename,
                seed=img.seed,
                width=img.width,
                height=img.height,
                iteration=it.number,
            )
            for img in it.images
        ]
        iterations.append(IterationSummary(
            number=it.number,
            prompt=it.prompt,
            images=images,
            passed=it.decision.passed if it.decision else False,
            decision_reasoning=it.decision.reasoning if it.decision else "",
        ))

    return SessionHistoryResponse(
        session_id=session.id,
        user_request=session.user_request,
        state=session.state.value,
        iterations=iterations,
        messages=_message_ids.get(session_id, []),
    )


@router.get("/images/{filename}")
async def serve_image(filename: str):
    image_path = _output_dir / filename
    if not image_path.exists():
        raise HTTPException(404, "Image not found")
    return FileResponse(image_path, media_type="image/png")


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    _session_manager.delete(session_id)
    _sessions_store.pop(session_id, None)
    _message_ids.pop(session_id, None)
    return {"deleted": True}


# These are set after init_routes is called
_session_manager: object = None
_interrupt_handler: object = None
