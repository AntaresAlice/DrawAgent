"""DrawAgent entry point — CLI and FastAPI server."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(
        prog="drawagent",
        description="AI-powered image generation agent system",
    )
    parser.add_argument(
        "--serve",
        action="store_true",
        help="Start the FastAPI web server",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Server port (default: 8000)",
    )
    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Server host (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="./outputs",
        help="Output directory for generated images",
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to config file",
    )

    args = parser.parse_args()

    if args.serve:
        asyncio.run(run_server(args))
    else:
        parser.print_help()


async def run_server(args):
    sys.path.insert(0, str(Path(__file__).parent.parent))

    # Load config
    from drawagent.config.loader import ConfigLoader

    config = await ConfigLoader.load(Path.cwd())

    # Create shared services
    from drawagent.core.events import EventBus
    from drawagent.orchestrator.interrupt import InterruptHandler
    from drawagent.orchestrator.session import SessionManager

    event_bus = EventBus()
    session_manager = SessionManager()
    interrupt_handler = InterruptHandler()

    # Create API app
    from drawagent.api.app import create_app
    from drawagent.api.routes import init_routes
    from drawagent.api.websocket import ws_manager

    app = create_app(output_dir=args.output_dir)
    init_routes(session_manager, interrupt_handler, args.output_dir)

    # Wire event bus to WebSocket broadcasting
    async def broadcast_event(event_type, data):
        data_dict = dict(data) if hasattr(data, "__iter__") and not isinstance(data, dict) else data
        # Try to get session_id from event data
        session_id = data_dict.get("session_id") if isinstance(data_dict, dict) else None
        if session_id:
            await ws_manager.broadcast(session_id, event_type.value, **data_dict)

    for evt in [
        "iteration.started",
        "iteration.completed",
        "prompt.refined",
        "generation.started",
        "images.ready",
        "inspection.task_done",
        "inspection.complete",
        "quality.decision",
        "loop.terminated",
        "user.interrupt",
        "error",
    ]:
        event_bus.on(evt, broadcast_event)

    print(f"DrawAgent API starting on http://{args.host}:{args.port}")
    print(f"Output directory: {Path(args.output_dir).resolve()}")

    import uvicorn
    uvicorn_config = uvicorn.Config(
        app,
        host=args.host,
        port=args.port,
        log_level="info",
    )
    server = uvicorn.Server(uvicorn_config)
    await server.serve()


if __name__ == "__main__":
    main()
