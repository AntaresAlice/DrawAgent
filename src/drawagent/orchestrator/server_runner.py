from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from drawagent.agents.agent_a import AgentA
from drawagent.config.schema import AppConfig
from drawagent.context.assembler import ContextAssembler
from drawagent.core.events import EventBus, DrawEvent
from drawagent.core.types import Session
from drawagent.models.agentic_session import AgenticSession, InputQueue
from drawagent.orchestrator.agentic_loop import AgenticLoop
from drawagent.orchestrator.interrupt import InterruptHandler
from drawagent.orchestrator.loop import InnerLoop
from drawagent.orchestrator.session import SessionManager
from drawagent.providers.base import LLMProvider, VisionProvider
from drawagent.tools.base import ToolRegistry
from drawagent.core.errors import ConfigError

logger = logging.getLogger("drawagent.server_runner")


class ServerRunner:
    """Manages InnerLoop execution for the web server mode.

    Created once at server startup; enqueues user messages as background
    tasks that run the full 5-phase generation loop and broadcast events
    to WebSocket clients via the EventBus.

    Providers are created lazily on first message to avoid blocking server
    startup when API keys are not yet configured.
    """

    def __init__(
        self,
        config: AppConfig,
        tool_registry: ToolRegistry,
        session_manager: SessionManager,
        interrupt_handler: InterruptHandler,
        event_bus: EventBus,
        output_dir: str = "./outputs",
        config_file: str | None = None,
    ):
        self.config = config
        self.tool_registry = tool_registry
        self.session_manager = session_manager
        self.interrupt_handler = interrupt_handler
        self.event_bus = event_bus
        self.output_dir = Path(output_dir).resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._config_file = Path(config_file) if config_file else None

        self._provider_a: LLMProvider | None = None
        self._provider_c: VisionProvider | None = None
        self._provider_init_attempted = False
        self._active_tasks: dict[str, asyncio.Task] = {}
        self._agentic_state: dict[str, tuple[AgenticSession, InputQueue]] = {}

    async def run_for_message(self, session: Session, text: str) -> None:
        """Launch the inner loop as a background task for a user message."""
        session_id = session.id

        if session_id in self._active_tasks:
            existing = self._active_tasks[session_id]
            if not existing.done():
                logger.warning("Session %s already has an active task", session_id)
                return

        task = asyncio.create_task(
            self._execute_loop(session, text),
            name=f"loop-{session_id}",
        )
        self._active_tasks[session_id] = task

    async def _get_or_create_providers(self) -> tuple[LLMProvider, VisionProvider]:
        from drawagent.providers.factory import ProviderFactory
        from drawagent.tools.inspect_image import InspectImageTool

        if self._provider_a is not None and self._provider_c is not None:
            return self._provider_a, self._provider_c

        self._provider_a = ProviderFactory.create_agent_a(self.config.agent_a)
        self._provider_c = ProviderFactory.create_agent_c(self.config.agent_c)

        inspect_tool = self.tool_registry.get("inspect_image")
        if inspect_tool is not None:
            inspect_tool.provider = self._provider_c

        compare_tool = self.tool_registry.get("compare_images")
        if compare_tool is not None:
            compare_tool.provider = self._provider_c

        return self._provider_a, self._provider_c

    async def _execute_loop(self, session: Session, text: str) -> None:
        engine = self.config.loop.engine
        if engine == "agentic":
            await self._run_agentic_loop(session, text)
            return
        # ===== Classic path (unchanged) =====
        await self._run_classic_loop(session, text)

    async def _run_classic_loop(self, session: Session, text: str) -> None:
        session_id = session.id
        # Preserve original user request on feedback messages
        is_feedback = bool(session.iterations and session.user_request)
        if is_feedback:
            session.steer_message = text
            logger.info("Session %s received feedback: %s", session_id, text[:120])
        else:
            session.user_request = text

        try:
            provider_a, provider_c = await self._get_or_create_providers()
        except ConfigError as e:
            logger.warning("Session %s provider init failed: %s", session_id, e)
            await self.event_bus.emit(
                DrawEvent.ERROR,
                message=f"API 配置错误: {e}\n请在系统设置中配置 API Key 和 API Base URL，或在环境变量中设置 OPENAI_API_KEY",
                session_id=session_id,
            )
            return
        except Exception as e:
            logger.exception("Session %s provider init unexpected error", session_id)
            await self.event_bus.emit(
                DrawEvent.ERROR,
                message=f"初始化 AI 服务失败: {e}",
                session_id=session_id,
            )
            return

        agent_a = AgentA(
            provider=provider_a,
            tool_registry=self.tool_registry,
            session=session,
        )
        assembler = ContextAssembler(agent_b_config=self.config.agent_b)

        loop = InnerLoop(
            session=session,
            agent_a=agent_a,
            tool_registry=self.tool_registry,
            session_manager=self.session_manager,
            interrupt_handler=self.interrupt_handler,
            assembler=assembler,
            event_bus=self.event_bus,
            config=self.config.loop,
        )

        try:
            has_previous = bool(session.iterations)
            start_iter = len(session.iterations) if is_feedback and has_previous else 0
            if is_feedback and has_previous:
                text = session.iterations[-1].prompt  # continue from last known prompt
            result = await loop.run(initial_prompt=text, start_iteration=start_iter)
            logger.info(
                "Session %s loop finished: reason=%s, iterations=%d, images=%d",
                session_id,
                result.terminated_reason,
                result.iterations_completed,
                len(result.final_images),
            )
            await self.event_bus.emit(
                DrawEvent.LOOP_TERMINATED,
                reason=result.terminated_reason,
                session_id=session_id,
                iterations_completed=result.iterations_completed,
            )
        except Exception as exc:
            logger.exception("Session %s loop error: %s", session_id, exc)
            await self.event_bus.emit(
                DrawEvent.ERROR,
                message=str(exc),
                session_id=session_id,
            )
        finally:
            self._active_tasks.pop(session_id, None)

    async def _run_agentic_loop(self, classic_session: Session, text: str) -> None:
        """Agentic mode — LLM-driven generation loop.

        Creates or reuses an AgenticSession per session_id so that
        multi-turn conversations preserve context across messages.
        The classic Session object is used only to carry the session ID.
        """
        session_id = classic_session.id

        # Reuse or create agentic state for this session
        if session_id in self._agentic_state:
            agentic_session, input_queue = self._agentic_state[session_id]
            msg = await input_queue.admit_and_persist(text, "queue")
            agentic_session.messages.append(msg)
            logger.info("Session %s agentic: reusing state (turns=%d, messages=%d)",
                        session_id, len(agentic_session.turns), len(agentic_session.messages))
        else:
            agentic_session = AgenticSession(
                id=session_id,
                user_request=classic_session.user_request or text,
            )
            input_queue = InputQueue(session_id, self.session_manager)
            msg = await input_queue.admit_and_persist(
                classic_session.user_request or text, "queue"
            )
            agentic_session.messages.append(msg)
            self._agentic_state[session_id] = (agentic_session, input_queue)

        try:
            provider_a, provider_c = await self._get_or_create_providers()
        except ConfigError as e:
            logger.warning("Session %s agentic provider init failed: %s", session_id, e)
            await self.event_bus.emit(
                DrawEvent.ERROR,
                message=f"API config error: {e}",
                session_id=session_id,
            )
            return
        except Exception as e:
            logger.exception("Session %s agentic provider init unexpected error", session_id)
            await self.event_bus.emit(
                DrawEvent.ERROR,
                message=f"AI service init failed: {e}",
                session_id=session_id,
            )
            return

        agent_a = AgentA(
            provider=provider_a,
            tool_registry=self.tool_registry,
            session=classic_session,  # AgentA still needs classic Session for provider/session access
        )

        # Build config dict for agentic loop (include agent_a + agent_b subsections)
        loop_config = self.config.loop.model_dump() if hasattr(self.config.loop, "model_dump") else {}
        loop_config["agent_a"] = self.config.agent_a.model_dump() if hasattr(self.config.agent_a, "model_dump") else {}
        loop_config["agent_b"] = self.config.agent_b
        agentic_loop = AgenticLoop(
            session=agentic_session,
            agent_a=agent_a,
            registry=self.tool_registry,
            config=loop_config,
            event_bus=self.event_bus,
            session_manager=self.session_manager,
        )
        agentic_loop.set_queue(input_queue)

        try:
            result = await agentic_loop.run()
            logger.info(
                "Session %s agentic loop finished: turns=%d, lessons=%d",
                session_id,
                len(result.turns),
                len(result.learned_lessons),
            )
            await self.event_bus.emit(
                DrawEvent.LOOP_TERMINATED,
                reason="agentic_completed",
                session_id=session_id,
                iterations_completed=len(result.iterations),
            )
        except Exception as exc:
            logger.exception("Session %s agentic loop error: %s", session_id, exc)
            await self.event_bus.emit(
                DrawEvent.ERROR,
                message=str(exc),
                session_id=session_id,
            )
        finally:
            self._active_tasks.pop(session_id, None)

    async def cancel(self, session_id: str) -> bool:
        """Cancel an active loop task for a session."""
        task = self._active_tasks.get(session_id)
        if task and not task.done():
            task.cancel()
            return True
        return False

    def cleanup_session(self, session_id: str) -> None:
        """Remove agentic state for a deleted session to prevent memory leak."""
        self._agentic_state.pop(session_id, None)
        self._active_tasks.pop(session_id, None)

    def get_agentic_state(self, session_id: str) -> tuple[AgenticSession, InputQueue] | None:
        """Return agentic session + input queue if this session uses agentic mode."""
        return self._agentic_state.get(session_id)

    async def handle_agentic_steer(self, session_id: str, text: str) -> None:
        """Route a user steer message to the agentic input queue.

        Called by WebSocket handler when a user sends feedback during
        an active agentic session.
        """
        state = self._agentic_state.get(session_id)
        if state is None:
            logger.warning("Agentic steer for unknown session %s", session_id)
            return
        _agentic_session, input_queue = state
        msg = await input_queue.admit_and_persist(text, "steer")
        _agentic_session.messages.append(msg)
        await self.event_bus.emit("interrupt.accepted", **{
            "session_id": session_id,
            "message": text,
            "delivery": "steer",
        })
        logger.info("Agentic steer admitted for session %s: %s", session_id, text[:80])

    def update_config(self, config_dict: dict) -> None:
        """Update runtime config from a dict (e.g., from frontend system settings).

        Clears cached providers so the next message recreates them with new config.
        """
        for section_name, section_data in config_dict.items():
            section = getattr(self.config, section_name, None)
            if section is None:
                logger.warning("Unknown config section: %s", section_name)
                continue
            if not isinstance(section_data, dict):
                logger.warning("Config section %s is not a dict, skipping", section_name)
                continue
            for key, value in section_data.items():
                if hasattr(section, key):
                    if key == "api_key" and value and not isinstance(value, str):
                        logger.warning("Invalid api_key type for %s.%s, skipping", section_name, key)
                        continue
                    setattr(section, key, value)
                    logger.info("Config updated: %s.%s = %s", section_name, key, value if key != "api_key" else "***")
        self._provider_a = None
        self._provider_c = None
        self._provider_init_attempted = False

        # Reset Agent B MCP provider so it reconnects with new config
        gen_tool = self.tool_registry.get("generate_image")
        if gen_tool is not None and hasattr(gen_tool, "_mcp_provider"):
            if gen_tool._mcp_provider is not None:
                import asyncio
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    loop = asyncio.new_event_loop()
                loop.create_task(gen_tool._mcp_provider.close())
            gen_tool._mcp_provider = None

        logger.info("Config updated, providers cleared for recreation")

        # Persist to config file so changes survive restart
        if self._config_file:
            self._save_config()

    def _save_config(self) -> None:
        """Persist current runtime config to the config file.

        Note: This saves API keys to disk. For production use, set keys via
        environment variables instead and keep the config file key-free.
        """
        import yaml

        def _model_to_dict(obj):
            if hasattr(obj, "model_dump"):
                return obj.model_dump(exclude_none=True, mode="json")
            return obj

        config_dict = _model_to_dict(self.config)
        try:
            with open(self._config_file, "w", encoding="utf-8") as f:
                yaml.safe_dump(config_dict, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
            logger.info("Config persisted to %s", self._config_file)
        except Exception as e:
            logger.warning("Failed to persist config to %s: %s", self._config_file, e)
