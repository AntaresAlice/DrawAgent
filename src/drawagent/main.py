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
    sub = parser.add_subparsers(dest="command", help="Commands")

    # serve
    serve_p = sub.add_parser("serve", help="Start the FastAPI web server")
    serve_p.add_argument("--port", type=int, default=8000)
    serve_p.add_argument("--host", type=str, default="127.0.0.1")
    serve_p.add_argument("--output-dir", type=str, default="./outputs")
    serve_p.add_argument("--config", type=str, default=None)

    # cli
    cli_p = sub.add_parser("cli", help="Run interactive CLI mode")
    cli_p.add_argument("--output-dir", type=str, default="./outputs")
    cli_p.add_argument("--config", type=str, default=None)
    cli_p.add_argument("--resume", type=str, default=None, metavar="SESSION_ID",
                       help="Resume a session from the database")
    cli_p.add_argument("--from-iteration", type=int, default=0, metavar="N",
                       help="Start from iteration N when resuming (0=auto, continues from last)")
    cli_p.add_argument("--rerun-last", action="store_true",
                       help="When resuming, re-run the last completed iteration")
    cli_p.add_argument("--step", action="store_true",
                       help="Enable step-by-step mode (pause after each iteration)")
    cli_p.add_argument("--db", type=str, default=None,
                       help="Enable session persistence to SQLite DB path")

    args = parser.parse_args()

    if args.command == "serve":
        asyncio.run(run_server(args))
    elif args.command == "cli":
        asyncio.run(run_cli(args))
    else:
        parser.print_help()


async def run_server(args):
    sys.path.insert(0, str(Path(__file__).parent.parent))

    from drawagent.config.loader import ConfigLoader
    from drawagent.core.events import EventBus, DrawEvent
    from drawagent.orchestrator.interrupt import InterruptHandler
    from drawagent.orchestrator.session import SessionManager
    from drawagent.persistence.database import Database
    from drawagent.api.app import create_app
    from drawagent.api.routes import init_routes
    from drawagent.api.websocket import ws_manager
    from drawagent.tools.base import ToolRegistry
    from drawagent.tools.generate_image import GenerateImageTool
    from drawagent.tools.inspect_image import InspectImageTool
    from drawagent.memory.tools import LoadMemoryTool, SearchMemoryTool, SaveMemoryTool
    from drawagent.memory.store import MemoryStore
    from drawagent.memory.index import MemoryIndex
    from drawagent.orchestrator.server_runner import ServerRunner

    config = await ConfigLoader.load(Path.cwd())
    event_bus = EventBus()

    db = Database()
    await db.connect()
    session_manager = SessionManager(db=db)
    interrupt_handler = InterruptHandler()

    restored = await session_manager.load_all()
    if restored:
        print(f"Restored {len(restored)} session(s) from database")

    registry = ToolRegistry()
    gen_tool = GenerateImageTool(config=config.agent_b, output_dir=args.output_dir)
    inspect_tool = InspectImageTool(vision_provider=None)
    registry.register(gen_tool)
    registry.register(inspect_tool)

    memory_dir = Path(config.memory.base_dir).expanduser()
    store = MemoryStore(memory_dir)
    index = MemoryIndex(memory_dir)
    registry.register(LoadMemoryTool(store))
    registry.register(SearchMemoryTool(store))
    registry.register(SaveMemoryTool(store, index))

    runner = ServerRunner(
        config=config,
        tool_registry=registry,
        session_manager=session_manager,
        interrupt_handler=interrupt_handler,
        event_bus=event_bus,
        output_dir=args.output_dir,
    )

    app = create_app(output_dir=args.output_dir)
    init_routes(session_manager, interrupt_handler, args.output_dir, runner)

    async def broadcast_event(event_type, data):
        data_dict = dict(data) if not isinstance(data, dict) else data
        session_id = data_dict.pop("session_id", None) if isinstance(data_dict, dict) else None
        if session_id:
            await ws_manager.broadcast(session_id, event_type if isinstance(event_type, str) else event_type.value, **data_dict)

    for evt in [
        "iteration.started", "prompt.refined", "generation.started",
        "images.ready", "inspection.task_done", "inspection.complete",
        "quality.decision", "loop.terminated", "user.interrupt", "error",
        "agent.question", "user.steer", "user.rollback",
    ]:
        event_bus.on(evt, broadcast_event)

    print(f"DrawAgent API starting on http://{args.host}:{args.port}")
    print(f"Output dir: {Path(args.output_dir).resolve()}")

    import uvicorn
    server = uvicorn.Server(uvicorn.Config(app, host=args.host, port=args.port, log_level="info"))
    await server.serve()


async def run_cli(args):
    """Interactive CLI mode for DrawAgent."""
    sys.path.insert(0, str(Path(__file__).parent.parent))

    from datetime import datetime

    from drawagent.config.loader import ConfigLoader
    from drawagent.core.events import DrawEvent, EventBus
    from drawagent.core.types import Session
    from drawagent.orchestrator.interrupt import InterruptHandler
    from drawagent.orchestrator.session import SessionManager
    from drawagent.agents.agent_a import AgentA
    from drawagent.agents.prompts import BASE_SYSTEM_PROMPT
    from drawagent.config.schema import AgentBConfig, LoopConfig
    from drawagent.context.assembler import ContextAssembler
    from drawagent.providers.factory import ProviderFactory
    from drawagent.tools.base import ToolRegistry
    from drawagent.tools.generate_image import GenerateImageTool
    from drawagent.tools.inspect_image import InspectImageTool
    from drawagent.tools.human_input import AskUserTool
    from drawagent.persistence.database import Database

    config = await ConfigLoader.load(Path.cwd())
    print("=" * 60)
    print("  DrawAgent CLI v0.1.0")
    print(f"  Agent A: {config.agent_a.model}")
    print(f"  Agent B: {config.agent_b.model} @ {config.agent_b.api_base}")
    print(f"  Agent C: {config.agent_c.model}")
    if args.step:
        print("  Mode: Step-by-step (pause after each iteration)")
    if args.resume:
        print(f"  Resume: {args.resume}")
    print("=" * 60)
    print()

    # Database (if enabled)
    db = None
    if args.db or args.resume:
        db_path = args.db or "~/.drawagent/sessions.db"
        db = Database(Path(db_path).expanduser())
        await db.connect()

    session_mgr = SessionManager(db=db)
    interrupt_handler = InterruptHandler()
    event_bus = EventBus()

    # Set up event listeners for CLI output
    async def on_iteration_start(evt_type, data):
        print(f"\n  >>> Iteration {data.get('iteration', '?')} started")
    async def on_prompt_refined(evt_type, data):
        print(f"  [Refine] Prompt updated")
    async def on_gen_start(evt_type, data):
        print(f"  [Generate] Calling Agent B...")
    async def on_images_ready(evt_type, data):
        images = data.get("images", [])
        for img in images:
            print(f"  [Image] {img.filename} (seed={img.seed}, {img.width}x{img.height})")
    async def on_inspection_done(evt_type, data):
        task = data.get("task", "?")
        result = data.get("result")
        passed = result.passed if result else False
        icon = "[PASS]" if passed else "[FAIL]"
        print(f"  [Inspect {icon}] {task}")
    async def on_quality_decision(evt_type, data):
        d = data.get("decision")
        if d:
            icon = "[PASS]" if d.passed else "[FAIL]"
            print(f"  [Quality {icon}] {d.reasoning[:120]}")
    async def on_loop_end(evt_type, data):
        print(f"\n  *** Loop ended: {data.get('reason', 'completed')} ***\n")
    async def on_error(evt_type, data):
        print(f"\n  !!! Error: {data.get('message', 'unknown')} !!!\n")
    async def on_user_interrupt(evt_type, data):
        """Handle step-mode pause — read user input from thread pool."""
        msg = data.get("message", "Iteration complete")
        print(f"\n  [Step] {msg}")
        print("  /next (Enter) | /accept | /steer <msg> | /rollback | /quit | /status")
        loop = asyncio.get_running_loop()
        user_input = (await loop.run_in_executor(None, input, "  > ")).strip().lower()
        if user_input in ("", "/next", "/step", "/continue"):
            session.pending_action = "next"
        elif user_input == "/accept":
            session.pending_action = "accept"
        elif user_input.startswith("/steer"):
            session.steer_message = user_input[len("/steer"):].strip()
            session.pending_action = "steer"
        elif user_input == "/rollback":
            session.pending_action = "rollback"
        elif user_input == "/quit":
            session.pending_action = "quit"
        elif user_input == "/status":
            print(f"  Session: {session.id} | Iterations: {len(session.iterations)}")
            session.pending_action = "next"
        else:
            session.pending_action = "next"
        session.interrupt_event.set()

    event_bus.on(DrawEvent.ITERATION_STARTED, on_iteration_start)
    event_bus.on(DrawEvent.PROMPT_REFINED, on_prompt_refined)
    event_bus.on(DrawEvent.GENERATION_STARTED, on_gen_start)
    event_bus.on(DrawEvent.IMAGES_READY, on_images_ready)
    event_bus.on(DrawEvent.INSPECTION_TASK_DONE, on_inspection_done)
    event_bus.on(DrawEvent.QUALITY_DECISION, on_quality_decision)
    event_bus.on(DrawEvent.LOOP_TERMINATED, on_loop_end)
    event_bus.on(DrawEvent.ERROR, on_error)
    event_bus.on(DrawEvent.USER_INTERRUPT, on_user_interrupt)

    try:
        provider_a = ProviderFactory.create_agent_a(config.agent_a)
        provider_c = ProviderFactory.create_agent_c(config.agent_c)
    except Exception as e:
        print(f"Failed to create providers: {e}")
        print("Set OPENAI_API_KEY environment variable or configure api_key in config.")
        return

    registry = ToolRegistry()
    gen_tool = GenerateImageTool(config=config.agent_b, output_dir=args.output_dir)
    inspect_tool = InspectImageTool(vision_provider=provider_c)
    ask_tool = AskUserTool()
    registry.register(gen_tool)
    registry.register(inspect_tool)
    registry.register(ask_tool)

    from drawagent.memory.tools import LoadMemoryTool, SearchMemoryTool, SaveMemoryTool
    from drawagent.memory.store import MemoryStore
    from drawagent.memory.index import MemoryIndex

    memory_dir = Path(config.memory.base_dir).expanduser()
    store = MemoryStore(memory_dir)
    index = MemoryIndex(memory_dir)
    registry.register(LoadMemoryTool(store))
    registry.register(SearchMemoryTool(store))
    registry.register(SaveMemoryTool(store, index))

    # Session management
    session = None
    start_iteration = 0

    if args.resume:
        if db is None:
            print("Error: --resume requires --db or implicit database path")
            return
        session = await session_mgr.load_session(args.resume)
        if session is None:
            print(f"Session {args.resume} not found in database")
            print("Available sessions:")
            all_sessions = await session_mgr.load_all()
            for s in all_sessions:
                iters = len(s.iterations)
                print(f"  {s.id[:12]}... | {s.user_request[:50]}... | {iters} iterations | state={s.state.value}")
            return
        print(f"Resumed session: {session.id[:12]}...")
        print(f"  User request: {session.user_request[:80]}...")
        print(f"  Completed iterations: {len(session.iterations)}")
        for it in session.iterations:
            passed = it.decision.passed if it.decision else "?"
            print(f"    Iteration {it.number}: {'PASS' if passed else 'FAIL'} | {it.prompt[:60]}...")

        if args.from_iteration > 0:
            start_iteration = args.from_iteration
            # Trim iterations after start point
            session.iterations = session.iterations[:start_iteration]
            print(f"  Starting from iteration {start_iteration}")
        elif args.rerun_last and session.iterations:
            start_iteration = max(0, len(session.iterations) - 1)
            session.iterations = session.iterations[:start_iteration]
            print(f"  Re-running last iteration (starting from {start_iteration})")
        else:
            start_iteration = len(session.iterations)
            print(f"  Auto-resuming from iteration {start_iteration + 1}")
    else:
        session = Session(
            id=f"cli-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
            user_request="",
            max_iterations=config.loop.max_iterations,
        )
        if db:
            await session_mgr.persist_session(session)
            print(f"Session persisted: {session.id}")

    print()
    print("Describe the image you want, and I'll generate it.")
    print("Commands: /quit, /help, /status")
    if args.step:
        print("  Step mode: /next, /accept, /steer <msg>, /rollback, /quit")
    print()

    from drawagent.orchestrator.loop import InnerLoop

    agent_a = AgentA(provider=provider_a, tool_registry=registry, session=session)
    assembler = ContextAssembler(agent_b_config=config.agent_b)

    loop = InnerLoop(
        session=session,
        agent_a=agent_a,
        tool_registry=registry,
        session_manager=session_mgr,
        interrupt_handler=interrupt_handler,
        assembler=assembler,
        event_bus=event_bus,
        config=config.loop,
    )

    current_prompt = ""

    while True:
        try:
            user_input = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if not user_input:
            continue

        # Global commands
        if user_input == "/quit":
            print("Goodbye!")
            break
        if user_input == "/help":
            print("Commands: /quit, /help, /status")
            if args.step:
                print("  Step mode: /next, /accept, /steer <msg>, /rollback")
            print("Describe an image to start generation.")
            continue
        if user_input == "/status":
            print(f"Session: {session.id}")
            print(f"State: {session.state.value}")
            print(f"Iterations: {len(session.iterations)}")
            if session.iterations:
                for it in session.iterations:
                    p = it.decision
                    status = "PASS" if (p and p.passed) else "FAIL" if p else "?"
                    print(f"  Iter {it.number}: {status} | {it.prompt[:50]}...")
            continue

        # Generate
        session.user_request = user_input
        current_prompt = user_input
        agent_a.session = session
        loop.session = session
        print(f"\nProcessing: \"{user_input}\"")
        print("-" * 40)

        try:
            result = await loop.run(
                initial_prompt=user_input,
                start_iteration=start_iteration if start_iteration > 0 else 0,
                step_mode=args.step,
            )
            print(f"Result: {result.terminated_reason}")
            print(f"Iterations: {result.iterations_completed}")
            if result.final_images:
                print("Final images:")
                for img in result.final_images:
                    print(f"  {img.path}")
        except Exception as e:
            print(f"Loop error: {e}")
        finally:
            print("-" * 40 + "\n")
            start_iteration = 0  # Reset for next prompt

    if db:
        await db.close()


if __name__ == "__main__":
    main()
