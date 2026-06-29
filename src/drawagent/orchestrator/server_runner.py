from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from drawagent.agents.agent_a import AgentA
from drawagent.config.schema import AppConfig
from drawagent.context.assembler import ContextAssembler
from drawagent.core.events import EventBus, DrawEvent
from drawagent.core.types import Session
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
    ):
        self.config = config
        self.tool_registry = tool_registry
        self.session_manager = session_manager
        self.interrupt_handler = interrupt_handler
        self.event_bus = event_bus
        self.output_dir = Path(output_dir).resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self._provider_a: LLMProvider | None = None
        self._provider_c: VisionProvider | None = None
        self._provider_init_attempted = False
        self._active_tasks: dict[str, asyncio.Task] = {}

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

        return self._provider_a, self._provider_c

    async def _execute_loop(self, session: Session, text: str) -> None:
        session_id = session.id
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
            result = await loop.run(initial_prompt=text)
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

    async def cancel(self, session_id: str) -> bool:
        """Cancel an active loop task for a session."""
        task = self._active_tasks.get(session_id)
        if task and not task.done():
            task.cancel()
            return True
        return False

    def update_config(self, config_dict: dict) -> None:
        """Update runtime config from a dict (e.g., from frontend system settings).

        Clears cached providers so the next message recreates them with new config.
        """
        for section_name, section_data in config_dict.items():
            section = getattr(self.config, section_name, None)
            if section is None:
                logger.warning("Unknown config section: %s", section_name)
                continue
            for key, value in section_data.items():
                if hasattr(section, key):
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
