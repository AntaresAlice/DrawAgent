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
    serve_p.add_argument("--config", type=str, default=None, metavar="PATH",
                         help="Path to config YAML file (highest priority overrides)")

    # cli (interactive)
    cli_p = sub.add_parser("cli", help="Run interactive CLI mode")
    cli_p.add_argument("--output-dir", type=str, default="./outputs")
    cli_p.add_argument("--config", type=str, default=None, metavar="PATH",
                       help="Path to config YAML file (highest priority overrides)")
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

    # run (non-interactive, debug-first one-shot)
    run_p = sub.add_parser("run", help="Non-interactive one-shot generation (debug mode)")
    run_p.add_argument("prompt", nargs="?", default=None, help="The image generation request")
    run_p.add_argument("--prompt", type=str, default=None, dest="prompt_text",
                       help="Prompt text (alternative to positional)")
    run_p.add_argument("--negative-prompt", type=str, default="", dest="negative_prompt",
                       help="Negative prompt")
    run_p.add_argument("--output-dir", type=str, default="./outputs")
    run_p.add_argument("--config", type=str, default=None, metavar="PATH",
                       help="Path to config YAML file")
    run_p.add_argument("--db", type=str, default=None,
                       help="SQLite database path (required for --resume/--fork)")
    # Execution control
    run_p.add_argument("--resume", type=str, default=None, metavar="SESSION_ID",
                       help="Resume a session from the database")
    run_p.add_argument("--from-iteration", type=int, default=0, metavar="N",
                       help="Start from iteration N (0=skip none; -1=last completed, the default for resume)")
    run_p.add_argument("--steps", type=int, default=None, metavar="N",
                       help="Iterations to execute (default: all for new session, 1 for resume, 0=unlimited)")
    run_p.add_argument("--fork", action="store_true",
                       help="Fork a new session instead of modifying the original")
    run_p.add_argument("--user-input", type=str, default=None, dest="user_input", metavar="TEXT",
                       help="Inject a steering instruction at the current iteration")
    # Generation params
    run_p.add_argument("--max-iterations", type=int, default=None, metavar="N",
                       help="Maximum iterations (overrides config)")
    run_p.add_argument("--width", type=int, default=None, metavar="PX")
    run_p.add_argument("--height", type=int, default=None, metavar="PX")
    run_p.add_argument("--steps-param", type=int, default=None, dest="steps_param", metavar="N",
                       help="Diffusion inference steps (1-50)")
    run_p.add_argument("--guidance", type=float, default=None, metavar="N")
    run_p.add_argument("--seed", type=int, default=None, metavar="N")
    run_p.add_argument("--num-images", type=int, default=None, metavar="N")
    # Agent overrides
    run_p.add_argument("--model-a", type=str, default=None)
    run_p.add_argument("--api-key-a", type=str, default=None)
    run_p.add_argument("--api-base-a", type=str, default=None)
    run_p.add_argument("--temperature-a", type=float, default=None)
    run_p.add_argument("--model-c", type=str, default=None)
    run_p.add_argument("--api-key-c", type=str, default=None)
    run_p.add_argument("--api-base-c", type=str, default=None)
    run_p.add_argument("--temperature-c", type=float, default=None)
    run_p.add_argument("--agent-b-type", type=str, default=None, choices=["http", "mcp"])
    run_p.add_argument("--agent-b-url", type=str, default=None)
    run_p.add_argument("--agent-b-endpoint", type=str, default=None)
    run_p.add_argument("--mcp-command", type=str, default=None)

    args = parser.parse_args()

    if args.command == "serve":
        asyncio.run(run_server(args))
    elif args.command == "cli":
        asyncio.run(run_cli(args))
    elif args.command == "run":
        asyncio.run(run_cli_noninteractive(args))
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

    config = await ConfigLoader.load(Path.cwd(), config_file=args.config)
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

    config = await ConfigLoader.load(Path.cwd(), config_file=args.config)
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


async def run_cli_noninteractive(args):
    """Non-interactive one-shot generation (debug mode)."""
    sys.path.insert(0, str(Path(__file__).parent.parent))

    from datetime import datetime

    from drawagent.config.loader import ConfigLoader
    from drawagent.core.events import DrawEvent, EventBus
    from drawagent.core.types import Session, Iteration, QualityDecision
    from drawagent.orchestrator.interrupt import InterruptHandler
    from drawagent.orchestrator.session import SessionManager
    from drawagent.agents.agent_a import AgentA
    from drawagent.context.assembler import ContextAssembler
    from drawagent.providers.factory import ProviderFactory
    from drawagent.tools.base import ToolRegistry
    from drawagent.tools.generate_image import GenerateImageTool
    from drawagent.tools.inspect_image import InspectImageTool
    from drawagent.persistence.database import Database

    config = await ConfigLoader.load(Path.cwd(), config_file=args.config)
    _apply_run_overrides(args, config)

    db = None
    if args.db or args.resume:
        db_path = args.db or "~/.drawagent/sessions.db"
        db = Database(Path(db_path).expanduser())
        await db.connect()

    session_mgr = SessionManager(db=db)
    interrupt_handler = InterruptHandler()
    event_bus = EventBus()

    # Event output
    async def on_iter_start(evt_type, data):
        print(f"  >>> Iteration {data.get('iteration', '?')} started")
    async def on_gen_start(evt_type, data):
        print(f"  [Generate] Calling Agent B...")
    async def on_images_ready(evt_type, data):
        for img in data.get("images", []):
            print(f"  [Image] {img.filename} (seed={img.seed}, {img.width}x{img.height})")
    async def on_inspect_done(evt_type, data):
        task = data.get("task", "?")
        result = data.get("result")
        passed = result.passed if result else False
        print(f"  [Inspect {'PASS' if passed else 'FAIL'}] {task}")
    async def on_quality(evt_type, data):
        d = data.get("decision")
        if d:
            icon = "[PASS]" if d.passed else "[FAIL]"
            print(f"  [Quality {icon}] {d.reasoning[:150]}")
    async def on_error(evt_type, data):
        print(f"  Error: {data.get('message', 'unknown')}", file=sys.stderr)

    event_bus.on(DrawEvent.ITERATION_STARTED, on_iter_start)
    event_bus.on(DrawEvent.GENERATION_STARTED, on_gen_start)
    event_bus.on(DrawEvent.IMAGES_READY, on_images_ready)
    event_bus.on(DrawEvent.INSPECTION_TASK_DONE, on_inspect_done)
    event_bus.on(DrawEvent.QUALITY_DECISION, on_quality)
    event_bus.on(DrawEvent.ERROR, on_error)

    try:
        provider_a = ProviderFactory.create_agent_a(config.agent_a)
        provider_c = ProviderFactory.create_agent_c(config.agent_c)
    except Exception as e:
        print(f"Failed to create providers: {e}", file=sys.stderr)
        sys.exit(1)

    registry = ToolRegistry()
    gen_tool = GenerateImageTool(config=config.agent_b, output_dir=args.output_dir)
    inspect_tool = InspectImageTool(vision_provider=provider_c)
    registry.register(gen_tool)
    registry.register(inspect_tool)

    # ── Session resolution ──
    original_session_id = None
    start_iteration = 0
    step_limit = args.steps
    prompt = args.prompt_text or args.prompt or ""

    if args.resume:
        if db is None:
            print("Error: --resume requires --db", file=sys.stderr)
            sys.exit(1)
        source = await session_mgr.load_session(args.resume)
        if source is None:
            print(f"Session {args.resume} not found in database", file=sys.stderr)
            all_s = await session_mgr.load_all()
            if all_s:
                print("Available sessions:")
                for s in all_s:
                    print(f"  {s.id[:16]}... | {s.user_request[:40]}... | {len(s.iterations)} iters")
            sys.exit(1)

        original_session_id = source.id
        if not prompt:
            prompt = source.user_request

        # ── Step 1: Fork (instantaneous copy) ──
        if args.fork:
            fork_id = f"fork-{source.id[:12]}-{datetime.now().strftime('%H%M%S')}"
            session = Session(
                id=fork_id,
                user_request=source.user_request,
                max_iterations=source.max_iterations,
            )
            session.iterations = list(source.iterations)
            if db:
                await session_mgr.persist_session(session)
                for it in session.iterations:
                    await session_mgr.add_iteration(session, it)
            print(f"Forked: {source.id[:16]}... -> {fork_id}")
            print(f"  (original session untouched)")
            # Fork without explicit --steps: just fork, no execution
            if step_limit is None:
                step_limit = -1  # sentinel: pure fork
        else:
            session = source
            print(f"Session: {source.id[:16]}...")
            # Resume without --steps: 1 step (debug mode default)
            if step_limit is None:
                step_limit = 1

        # ── Step 2: Trim iterations to starting point ──
        if args.from_iteration > 0:
            start_iteration = args.from_iteration
            print(f"  Trimming to iteration {start_iteration} (removing iterations {start_iteration}+)")
            session.iterations = session.iterations[:start_iteration]
        elif args.from_iteration == 0:
            start_iteration = len(session.iterations)

        # ── Step 3: Inject user input ──
        if args.user_input:
            session.pending_action = "steer"
            session.steer_message = args.user_input
            print(f"  User input: \"{args.user_input[:80]}\"")
    else:
        # New session
        if not prompt:
            print("Error: prompt required. Usage: drawagent run 'your prompt'", file=sys.stderr)
            sys.exit(1)
        session = Session(
            id=f"run-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
            user_request=prompt,
            max_iterations=config.loop.max_iterations,
        )
        if db:
            await session_mgr.persist_session(session)
        print(f"Session: {session.id[:16]}...")
        # New session without --steps: run all (None = unlimited)
        # step_limit stays None

    # ── Print execution plan ──
    print(f"Prompt:  \"{prompt[:80]}{'...' if len(prompt)>80 else ''}\"")
    print(f"  Agent A: {config.agent_a.model} @ {config.agent_a.api_base}")
    print(f"  Agent B: {config.agent_b.type} @ {config.agent_b.api_base}{config.agent_b.endpoint}")
    print(f"  Agent C: {config.agent_c.model} @ {config.agent_c.api_base}")
    gen = config.agent_b.default_params
    print(f"  Image: {gen.get('width', 1024)}x{gen.get('height', 1024)}, "
          f"steps={gen.get('steps', 8)}, guidance={gen.get('guidance', 3.5)}")
    if start_iteration > 0:
        print(f"  Start:  iteration {start_iteration} (have {len(session.iterations)} completed)")
    if step_limit == -1:
        print(f"  Steps:  0 (fork only, no execution)")
    elif step_limit is None:
        print(f"  Steps:  until termination (max {config.loop.max_iterations})")
    else:
        print(f"  Steps:  {step_limit} iteration(s)")
    print("-" * 50)

    # Handle --steps 0 (user explicitly wants unlimited)
    if step_limit == 0:
        step_limit = None
    if step_limit == -1:
        print("Fork complete. No steps executed.")
        if db:
            await db.close()
        return

    # ── Execute ──
    agent_a = AgentA(provider=provider_a, tool_registry=registry, session=session)
    assembler = ContextAssembler(agent_b_config=config.agent_b)

    from drawagent.orchestrator.loop import InnerLoop

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

    if start_iteration > 0:
        loop.reconstruct_state()

    print(f"Session: {session.id[:16]}...")
    print(f"Prompt:  \"{prompt[:80]}{'...' if len(prompt)>80 else ''}\"")
    print(f"  Agent A: {config.agent_a.model} @ {config.agent_a.api_base}")
    print(f"  Agent B: {config.agent_b.type} @ {config.agent_b.api_base}{config.agent_b.endpoint}")
    print(f"  Agent C: {config.agent_c.model} @ {config.agent_c.api_base}")
    gen = config.agent_b.default_params
    print(f"  Image: {gen.get('width', 1024)}x{gen.get('height', 1024)}, "
          f"steps={gen.get('steps', 8)}, guidance={gen.get('guidance', 3.5)}")
    if start_iteration > 0:
        print(f"  Start:  iteration {start_iteration}")
    if step_limit is not None:
        print(f"  Steps:  {step_limit} iteration(s)")
    else:
        print(f"  Steps:  until termination (max {config.loop.max_iterations})")
    print("-" * 50)

    try:
        result = await loop.run(
            initial_prompt=prompt,
            start_iteration=start_iteration,
            step_mode=False,
            step_limit=step_limit,
        )
        print(f"\nResult: {result.terminated_reason}")
        print(f"Iterations completed: {result.iterations_completed}")
        if result.final_images:
            print("Images:")
            for img in result.final_images:
                print(f"  {img.path}")
        else:
            print("No images generated.")
        if session.id != original_session_id:
            print(f"Session: {session.id}")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        if db:
            await db.close()


def _apply_run_overrides(args, config):
    """Apply CLI --flags to config, overriding YAML values."""
    if args.max_iterations is not None:
        config.loop.max_iterations = args.max_iterations

    gen = config.agent_b.default_params
    if args.width is not None:
        gen["width"] = args.width
    if args.height is not None:
        gen["height"] = args.height
    if args.steps_param is not None:
        gen["steps"] = args.steps_param
    if args.guidance is not None:
        gen["guidance"] = args.guidance
    if args.seed is not None:
        gen["seed"] = args.seed

    # Agent A overrides
    if args.model_a is not None:
        config.agent_a.model = args.model_a
    if args.api_key_a is not None:
        config.agent_a.api_key = args.api_key_a
    if args.api_base_a is not None:
        config.agent_a.api_base = args.api_base_a
    if args.temperature_a is not None:
        config.agent_a.temperature = args.temperature_a

    # Agent C overrides
    if args.model_c is not None:
        config.agent_c.model = args.model_c
    if args.api_key_c is not None:
        config.agent_c.api_key = args.api_key_c
    if args.api_base_c is not None:
        config.agent_c.api_base = args.api_base_c
    if args.temperature_c is not None:
        config.agent_c.temperature = args.temperature_c

    # Agent B overrides
    if args.agent_b_type is not None:
        config.agent_b.type = args.agent_b_type
    if args.agent_b_url is not None:
        config.agent_b.api_base = args.agent_b_url
    if args.agent_b_endpoint is not None:
        config.agent_b.endpoint = args.agent_b_endpoint
    if args.mcp_command is not None:
        config.agent_b.mcp_command = args.mcp_command.split()
        config.agent_b.type = "mcp"


if __name__ == "__main__":
    main()
