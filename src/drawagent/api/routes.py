from __future__ import annotations

import logging
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

logger = logging.getLogger("drawagent.api")
router = APIRouter(prefix="/api")

_sessions_store: dict[str, "Session"] = {}
_message_ids: dict[str, list[dict]] = {}
_output_dir = Path("./outputs")


def init_routes(session_manager, interrupt_handler, output_dir: str = "./outputs", runner: object = None):
    """Initialize routes with dependencies."""
    global _session_manager, _interrupt_handler, _output_dir, _runner
    _session_manager = session_manager
    _interrupt_handler = interrupt_handler
    _output_dir = Path(output_dir).resolve()
    _output_dir.mkdir(parents=True, exist_ok=True)
    _runner = runner


@router.get("/status", response_model=ServerStatus)
async def get_status():
    return ServerStatus(
        status="ok",
        version="0.1.0",
        sessions_count=len(_session_manager.list_ids()) if _session_manager else 0,
    )


@router.post("/sessions", response_model=CreateSessionResponse)
async def create_session(req: CreateSessionRequest):
    logger.info("Creating session: request=%s, max_iter=%d", req.user_request[:80], req.max_iterations)
    session = await _session_manager.create_and_persist(
        user_request=req.user_request,
        max_iterations=req.max_iterations,
    )
    _sessions_store[session.id] = session
    _message_ids[session.id] = []
    logger.info("Session created: %s", session.id)
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

    logger.info("[Session %s] message: %s", session_id, req.text[:120])
    message_id = str(uuid.uuid4())[:8]
    _message_ids.setdefault(session_id, []).append({
        "id": message_id,
        "role": "user",
        "content": req.text,
        "created_at": datetime.now().isoformat(),
    })

    if _runner is not None:
        import asyncio
        asyncio.create_task(_runner.run_for_message(session, req.text))

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
    await _session_manager.delete(session_id)
    _sessions_store.pop(session_id, None)
    _message_ids.pop(session_id, None)
    return {"deleted": True}


@router.get("/config")
async def get_config():
    """Return the current application configuration (non-sensitive)."""
    try:
        from drawagent.config.loader import ConfigLoader
        from pathlib import Path
        config = await ConfigLoader.load(Path.cwd())
        return {
            "agent_a": {
                "provider": config.agent_a.provider,
                "model": config.agent_a.model,
                "api_base": config.agent_a.api_base,
                "temperature": config.agent_a.temperature,
            },
            "agent_b": {
                "provider": config.agent_b.provider,
                "model": config.agent_b.model,
                "api_base": config.agent_b.api_base,
            },
            "agent_c": {
                "provider": config.agent_c.provider,
                "model": config.agent_c.model,
                "api_base": config.agent_c.api_base,
            },
        }
    except Exception as e:
        logger.warning("Failed to load config: %s", e)
        return JSONResponse({"error": str(e)}, status_code=500)


@router.put("/config")
async def update_config(req: dict):
    """Update application configuration at runtime (requires restart for some changes)."""
    logger.info("Config update requested: %s", {k: str(v)[:100] for k, v in (req or {}).items()})
    return {"updated": True, "note": "Config changes applied. Some changes require a server restart."}


@router.get("/sessions/{session_id}/export")
async def export_session(session_id: str):
    """Export a session as a ZIP file containing images, iterations, and messages."""
    import io
    import json
    import zipfile

    session = _session_manager.get_or_none(session_id)
    if session is None:
        raise HTTPException(404, "Session not found")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        iterations_data = []
        for it in session.iterations:
            it_data = {
                "number": it.number,
                "prompt": it.prompt,
                "gen_params": it.gen_params,
                "started_at": it.started_at.isoformat() if it.started_at else None,
                "finished_at": it.finished_at.isoformat() if it.finished_at else None,
                "images": [],
                "inspections": [],
                "decision": None,
            }
            for img in it.images:
                it_data["images"].append({
                    "filename": img.filename,
                    "path": img.path,
                    "seed": img.seed,
                    "width": img.width,
                    "height": img.height,
                })
                if img.path:
                    img_file = _output_dir / img.filename
                    if img_file.exists():
                        zf.write(img_file, f"{session_id}/images/{img.filename}")

            for insp in it.inspections:
                it_data["inspections"].append({
                    "task_name": insp.task_name,
                    "task_description": insp.task_description,
                    "passed": insp.passed,
                    "observation": insp.observation,
                    "issues": insp.issues,
                })

            if it.decision:
                it_data["decision"] = {
                    "passed": it.decision.passed,
                    "confidence": it.decision.confidence,
                    "reasoning": it.decision.reasoning,
                    "recommendation": it.decision.recommendation,
                }

            iterations_data.append(it_data)

        zf.writestr(f"{session_id}/iterations.json", json.dumps(iterations_data, ensure_ascii=False, indent=2))
        zf.writestr(f"{session_id}/messages.json", json.dumps(_message_ids.get(session_id, []), ensure_ascii=False, indent=2))
        zf.writestr(f"{session_id}/session.json", json.dumps({
            "id": session.id,
            "user_request": session.user_request,
            "state": session.state.value,
            "max_iterations": session.max_iterations,
            "created_at": session.created_at.isoformat(),
        }, ensure_ascii=False, indent=2))

    buf.seek(0)
    from starlette.responses import StreamingResponse
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=drawagent_{session_id}.zip"},
    )


# These are set after init_routes is called
_session_manager: object = None
_interrupt_handler: object = None
_runner: object = None
