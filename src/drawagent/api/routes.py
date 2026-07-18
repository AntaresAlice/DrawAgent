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
        session = _session_manager.get_or_none(sid)
        if session is None:
            continue
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
        asyncio.create_task(
            _runner.run_for_message(session, req.text, req.generation_params)
        )

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
            inspections=[
                {
                    "task_name": insp.task_name,
                    "task_description": insp.task_description,
                    "passed": insp.passed,
                    "observation": insp.observation,
                    "issues": insp.issues,
                }
                for insp in it.inspections
            ],
            passed=it.decision.passed if it.decision else False,
            decision_reasoning=it.decision.reasoning if it.decision else "",
        ))

    # Load agentic turns from DB if this session uses agentic engine
    agentic_turns: list[dict] = []
    engine = "classic"
    all_messages = list(_message_ids.get(session_id, []))
    try:
        if _runner is not None:
            state = _runner.get_agentic_state(session_id)
            if state is not None:
                engine = "agentic"
                agentic_session, _ = state
                for turn in agentic_session.turns:
                    at = {
                        "id": turn.id,
                        "assistant_text": turn.assistant_text,
                        "finish_reason": turn.finish_reason,
                        "tokens_used": turn.tokens_used,
                        "started_at": turn.started_at.isoformat() if turn.started_at else None,
                        "completed_at": turn.completed_at.isoformat() if turn.completed_at else None,
                        "user_msg": turn.user_message.text if turn.user_message else None,
                        "tool_calls": [],
                    }
                    for tc in turn.tool_calls:
                        at["tool_calls"].append({
                            "call_id": tc.call_id,
                            "tool_name": tc.tool_name,
                            "arguments": tc.arguments,
                            "status": tc.status,
                            "result": tc.result,
                            "error": tc.error,
                        })
                    agentic_turns.append(at)
            else:
                db_turns = await _session_manager.load_agentic_turns(session_id)
                if db_turns:
                    engine = "agentic"
                    agentic_turns = db_turns

        if engine == "agentic":
            db_msgs = await _session_manager.load_agentic_messages(session_id)
            for dm in db_msgs:
                if not any(m.get("id") == dm["id"] for m in all_messages):
                    all_messages.append({
                        "id": dm["id"],
                        "role": "user",
                        "content": dm["text"],
                        "created_at": dm.get("admitted_at") or "",
                    })
    except Exception:
        logger.exception("Failed to load agentic history for session %s", session_id)

    return SessionHistoryResponse(
        session_id=session.id,
        user_request=session.user_request,
        state=session.state.value,
        iterations=iterations,
        messages=all_messages,
        agentic_turns=agentic_turns,
        engine=engine,
    )


@router.get("/images/{filename}")
async def serve_image(filename: str):
    image_path = (_output_dir / filename).resolve()
    try:
        image_path.relative_to(_output_dir)
    except ValueError:
        raise HTTPException(403, "Access denied")
    if not image_path.exists():
        raise HTTPException(404, "Image not found")
    return FileResponse(image_path, media_type="image/png")


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    await _session_manager.delete(session_id)
    _sessions_store.pop(session_id, None)
    _message_ids.pop(session_id, None)
    if _runner is not None and hasattr(_runner, "cleanup_session"):
        _runner.cleanup_session(session_id)
    return {"deleted": True}


@router.get("/config")
async def get_config():
    """Return the current runtime configuration (from the runner, which respects --config)."""
    if _runner is not None and hasattr(_runner, "config"):
        cfg = _runner.config
        return {
            "agent_a": {
                "provider": cfg.agent_a.provider,
                "model": cfg.agent_a.model,
                "api_base": cfg.agent_a.api_base,
                "temperature": cfg.agent_a.temperature,
                "max_tokens": cfg.agent_a.max_tokens,
            },
            "agent_b": {
                "provider": cfg.agent_b.provider,
                "model": cfg.agent_b.model,
                "type": cfg.agent_b.type,
                "api_base": cfg.agent_b.api_base,
                "endpoint": cfg.agent_b.endpoint,
                "mcp_command": " ".join(cfg.agent_b.mcp_command) if isinstance(cfg.agent_b.mcp_command, list) else (cfg.agent_b.mcp_command or ""),
                "mcp_url": cfg.agent_b.mcp_url,
                "mcp_tool_name": cfg.agent_b.mcp_tool_name,
                "mcp_keep_alive": cfg.agent_b.mcp_keep_alive,
                "model_hints": cfg.agent_b.model_hints,
                "prompt_format": cfg.agent_b.prompt_format,
            },
            "agent_c": {
                "provider": cfg.agent_c.provider,
                "model": cfg.agent_c.model,
                "api_base": cfg.agent_c.api_base,
                "temperature": cfg.agent_c.temperature,
                "max_tokens": cfg.agent_c.max_tokens,
            },
            "loop": {
                "engine": cfg.loop.engine,
                "max_iterations": cfg.loop.max_iterations,
                "auto_accept_threshold": cfg.loop.auto_accept_threshold,
                "step_mode": cfg.loop.step_mode,
                "agentic": {
                    "max_tool_rounds": cfg.loop.agentic.max_tool_rounds,
                    "max_agentic_rounds": cfg.loop.agentic.max_agentic_rounds,
                    "max_finalize_rejections": cfg.loop.agentic.max_finalize_rejections,
                    "max_images_per_inspection": cfg.loop.agentic.max_images_per_inspection,
                },
            },
        }
    # Fallback: load from file (without --config awareness)
    try:
        from drawagent.config.loader import ConfigLoader
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
                "type": config.agent_b.type,
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
    """Update application configuration at runtime.

    Accepts a dict with sections matching AppConfig fields
    (agent_a, agent_b, agent_c). Updates runtime config and clears
    cached providers so next request uses new settings.
    """
    _log_safe = {}
    for k, v in (req or {}).items():
        if isinstance(v, dict):
            _log_safe[k] = {sk: (str(sv)[:100] if sk != "api_key" else "***") for sk, sv in v.items()}
        else:
            _log_safe[k] = str(v)[:100] if k != "api_key" else "***"
    logger.info("Config update requested: %s", _log_safe)
    if _runner is not None:
        _runner.update_config(req)
        return {"updated": True, "note": "Config applied and persisted to file. Providers will be recreated on next request."}
    return {"updated": False, "error": "Server runner not initialized"}


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
