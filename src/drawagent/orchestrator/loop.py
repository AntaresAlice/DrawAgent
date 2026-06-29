from __future__ import annotations

import asyncio
import json
from datetime import datetime

from drawagent.agents.agent_a import AgentA
from drawagent.config.schema import LoopConfig
from drawagent.context.assembler import ContextAssembler
from drawagent.context.compaction import CompactedHistory
from drawagent.core.errors import SessionError
from drawagent.core.events import EventBus, DrawEvent
from drawagent.core.types import (
    ImageRecord,
    InspectionRecord,
    InspectionTaskResult,
    Iteration,
    QualityDecision,
    Session,
    SessionState,
)
from drawagent.orchestrator.interrupt import InterruptHandler
from drawagent.orchestrator.session import SessionManager
from drawagent.providers.base import LLMMessage
from drawagent.tools.base import ToolRegistry


class LoopResult:
    """Result of the inner loop execution."""

    def __init__(
        self,
        terminated_reason: str,
        final_images: list[ImageRecord] | None = None,
        iterations_completed: int = 0,
    ):
        self.terminated_reason = terminated_reason
        self.final_images = final_images or []
        self.iterations_completed = iterations_completed


class InnerLoop:
    """Program-driven state machine for image generation iteration.

    Reference: opencode's SessionRunCoordinator but adapted for a deterministic
    image generation workflow: each iteration goes through fixed phases
    (plan → refine → generate → inspect → evaluate).

    Key difference from opencode:
    - opencode: LLM autonomously decides when to call tools and when to stop
    - DrawAgent: Program drives fixed phases per iteration; A only decides within scope
    """

    def __init__(
        self,
        session: Session,
        agent_a: AgentA,
        tool_registry: ToolRegistry,
        session_manager: SessionManager,
        interrupt_handler: InterruptHandler,
        assembler: ContextAssembler,
        event_bus: EventBus,
        config: LoopConfig,
    ):
        self.session = session
        self.agent_a = agent_a
        self.registry = tool_registry
        self.session_mgr = session_manager
        self.interrupt = interrupt_handler
        self.assembler = assembler
        self.events = event_bus
        self.config = config

        self.images_history: list[list[ImageRecord]] = []
        self.observations_history: list[InspectionRecord] = []

    async def run(self, initial_prompt: str) -> LoopResult:
        """Execute the inner loop until termination."""
        iteration = 0
        current_prompt = initial_prompt

        await self.events.emit(DrawEvent.ITERATION_STARTED, iteration=0)

        compacted: CompactedHistory | None = None

        while True:
            # ── Context compaction check ──
            if len(self.session.iterations) > self.config.keep_recent_iterations + 1:
                estimated_tokens = self._estimate_context_tokens()
                if estimated_tokens > self.config.compaction_threshold_tokens:
                    old_iters = self.session.iterations[:-self.config.keep_recent_iterations]
                    compacted = CompactedHistory.from_iterations(
                        old_iters, user_request=self.session.user_request
                    )
                    self.assembler.set_compacted_history(compacted)
                    self.agent_a._compacted = compacted
                    logger = __import__("logging").getLogger("drawagent.loop")
                    logger.info("Context compacted: %d iterations → summary", len(old_iters))

            # ── Check interrupt before each iteration ──
            if self.session_mgr.is_interrupted(self.session):
                action_result = await self._handle_interrupt()
                if action_result == "terminate":
                    return LoopResult(
                        terminated_reason=f"user_{self.session.pending_action}",
                        final_images=self._extract_best_images(),
                        iterations_completed=iteration,
                    )
                if action_result == "steer":
                    current_prompt = self.session.steer_message or current_prompt
                    self.session_mgr.clear_interrupt(self.session)
                    await self.events.emit(DrawEvent.USER_STEER, prompt=current_prompt)
                if action_result == "rollback":
                    target = self._parse_rollback_target()
                    if target < len(self.session.iterations):
                        restored_iter = self.session.iterations[target]
                        current_prompt = restored_iter.prompt
                        self.observations_history = self.observations_history[:target]
                        self.images_history = self.images_history[:target]
                        iteration = target
                        await self.events.emit(
                            DrawEvent.USER_ROLLBACK,
                            target=target,
                            prompt=current_prompt,
                        )
                    self.session_mgr.clear_interrupt(self.session)

            iteration += 1
            if iteration > self.config.max_iterations:
                await self.events.emit(
                    DrawEvent.LOOP_TERMINATED,
                    reason="max_iterations",
                )
                return LoopResult(
                    terminated_reason="max_iterations",
                    final_images=self._extract_best_images(),
                    iterations_completed=iteration - 1,
                )

            await self.events.emit(DrawEvent.ITERATION_STARTED, iteration=iteration)

            # ── Phase 0: CLARIFICATION (iteration 1 only) ──
            if iteration == 1 and not self.session.iterations:
                clarification = await self.agent_a.clarify_request(
                    current_prompt=current_prompt,
                )
                if clarification:
                    await self.events.emit(DrawEvent.A_QUESTION, text=clarification)
                    # Pause loop until user confirms or modifies
                    self.session_mgr.set_interrupt(self.session, "clarifying", None)
                    self.session.interrupt_event.clear()
                    # Wait for clarify_accept or clarify_modify via WebSocket
                    try:
                        await asyncio.wait_for(
                            self.session.interrupt_event.wait(),
                            timeout=120.0,
                        )
                    except asyncio.TimeoutError:
                        pass
                    self.session_mgr.clear_interrupt(self.session)
                    # If user modified request, re-clarify on next iteration
                    if self.session.pending_action != "clarify_done":
                        self.session.pending_action = None
                        continue

            # ── Phase 1: PLANNING ──
            self.session_mgr.transition(self.session, SessionState.PLANNING)
            previous_issues = None
            if self.observations_history:
                last_decision = self.observations_history[-1].decision
                if last_decision and last_decision.remaining_issues:
                    previous_issues = last_decision.remaining_issues

            inspection_tasks = await self.agent_a.design_inspection_plan(
                current_prompt=current_prompt,
                iteration=iteration,
                previous_issues=previous_issues,
            )
            await self.events.emit(
                DrawEvent.INSPECTION_PLAN_READY,
                plan=inspection_tasks,
            )

            # ── Phase 2: PROMPT REFINEMENT (iteration 2+) ──
            if iteration > 1 and self.observations_history:
                issues_for_refinement = []
                for obs in self.observations_history[-1].tasks:
                    if not obs.passed:
                        issues_for_refinement.append({
                            "task": obs.task_name,
                            "observation": obs.observation,
                            "issues": obs.issues,
                        })
                if issues_for_refinement:
                    refined = await self.agent_a.refine_prompt(
                        current_prompt, issues_for_refinement
                    )
                    if refined:
                        await self.events.emit(
                            DrawEvent.PROMPT_REFINED,
                            before=current_prompt,
                            after=refined,
                        )
                        current_prompt = refined

            # ── Phase 3: GENERATING ──
            self.session_mgr.transition(self.session, SessionState.GENERATING)
            await self.events.emit(DrawEvent.GENERATION_STARTED)

            try:
                gen_turn = await self.agent_a.run_turn(
                    messages=[
                        LLMMessage(
                            role="user",
                            content=(
                                f"Generate images for this prompt using the generate_image tool:\n\n"
                                f"Prompt: {current_prompt}\n\n"
                                f"Iteration: {iteration}/{self.config.max_iterations}\n\n"
                                f"Call generate_image with appropriate parameters."
                            ),
                        ),
                    ],
                    enabled_tools={"generate_image"},
                )
            except Exception as gen_exc:
                await self.events.emit(
                    DrawEvent.ERROR,
                    message=f"Generation phase failed: {gen_exc}",
                )
                if iteration == 1:
                    current_prompt = f"{self.session.user_request} — high quality, detailed"
                    continue
                return LoopResult(
                    terminated_reason="generation_error",
                    final_images=self._extract_best_images(),
                    iterations_completed=iteration,
                )

            images = self._extract_images_from_tool_results(gen_turn.tool_results, current_prompt, iteration)
            self.images_history.append(images)
            await self.events.emit(DrawEvent.IMAGES_READY, images=images)

            if not images:
                if iteration > 1:
                    return LoopResult(
                        terminated_reason="generation_failed",
                        final_images=self._extract_best_images(),
                        iterations_completed=iteration,
                    )
                # On first iteration, try with a simplified prompt
                current_prompt = f"{self.session.user_request} — high quality, detailed"
                continue

            # ── Phase 4: INSPECTING ──
            self.session_mgr.transition(self.session, SessionState.INSPECTING)

            inspection_results: list[InspectionTaskResult] = []
            for task in inspection_tasks:
                if self.session_mgr.is_interrupted(self.session):
                    break

                task_aggregate_observation = ""
                task_passed = True
                task_issues: list[str] = []
                image_paths_text = "\n".join(
                    f"  Image {i+1}: {img.path}" for i, img in enumerate(images)
                )

                for img_idx, image in enumerate(images):
                    inspect_turn = await self.agent_a.run_turn(
                        messages=[
                            LLMMessage(
                                role="user",
                                content=(
                                    f"Inspect the generated image for this task:\n\n"
                                    f"Task: {task.get('name', 'inspect')}\n"
                                    f"Description: {task.get('description', '')}\n\n"
                                    f"Image to inspect: {image.path} (image {img_idx + 1}/{len(images)})\n"
                                    f"All generated images:\n{image_paths_text}\n\n"
                                    f"Call inspect_image with this image and the task description.\n"
                                    f"After inspection, end your response with:\n"
                                    f"VERDICT: PASS or VERDICT: FAIL\n"
                                    f"If FAIL, list the specific issues found."
                                ),
                            ),
                        ],
                        enabled_tools={"inspect_image"},
                    )

                    img_observation = ""
                    for tr in inspect_turn.tool_results:
                        if tr.success:
                            img_observation = tr.output
                        else:
                            task_issues.append(f"[Image {img_idx + 1}] Inspection failed: {tr.error}")
                            task_passed = False

                    agent_verdict = inspect_turn.text.upper()
                    if "VERDICT: FAIL" in agent_verdict:
                        task_passed = False
                        task_issues.append(f"[Image {img_idx + 1}] {img_observation[:200]}")
                    elif "VERDICT: PASS" in agent_verdict:
                        pass
                    elif img_observation:
                        negative_keywords = [
                            "error:", "issue:", "incorrect", "missing", "distorted",
                            "artifact", "blurry", "fused", "extra", "poor quality",
                            "not present", "doesn't match", "failed to",
                        ]
                        if any(kw in img_observation.lower() for kw in negative_keywords):
                            task_passed = False
                            task_issues.append(f"[Image {img_idx + 1}] {img_observation[:200]}")

                    if img_observation:
                        task_aggregate_observation += (
                            f"\n[Image {img_idx + 1}]: {img_observation}"
                        )

                result = InspectionTaskResult(
                    task_name=task.get("name", str(len(inspection_results))),
                    task_description=task.get("description", ""),
                    passed=task_passed,
                    observation=task_aggregate_observation.strip() or "No images to inspect",
                    issues=task_issues,
                )
                inspection_results.append(result)
                await self.events.emit(
                    DrawEvent.INSPECTION_TASK_DONE,
                    task=task.get("name"),
                    result=result,
                )

            await self.events.emit(
                DrawEvent.INSPECTION_COMPLETE,
                results=inspection_results,
            )

            # ── Phase 5: EVALUATING ──
            self.session_mgr.transition(self.session, SessionState.ANALYZING)

            decision = await self.agent_a.evaluate_quality(
                current_prompt=current_prompt,
                inspection_results=inspection_results,
                iteration=iteration,
            )
            await self.events.emit(
                DrawEvent.QUALITY_DECISION,
                decision=decision,
            )

            # Save this iteration
            iter_obj = Iteration(
                number=iteration,
                prompt=current_prompt,
                images=images,
                inspections=inspection_results,
                decision=decision,
                finished_at=datetime.now(),
            )
            await self.session_mgr.add_iteration(self.session, iter_obj)

            self.observations_history.append(InspectionRecord(
                iteration=iteration,
                prompt=current_prompt,
                tasks=inspection_results,
                decision=decision,
            ))

            if decision.passed:
                if decision.recommendation == "ask_user":
                    await self.events.emit(
                        DrawEvent.A_QUESTION,
                        text="Quality is acceptable but I'd like your confirmation. Accept?",
                    )
                    return LoopResult(
                        terminated_reason="awaiting_user",
                        final_images=images,
                        iterations_completed=iteration,
                    )
                else:
                    await self.events.emit(
                        DrawEvent.LOOP_TERMINATED,
                        reason="quality_passed",
                    )
                    return LoopResult(
                        terminated_reason="quality_passed",
                        final_images=images,
                        iterations_completed=iteration,
                    )

            # Check auto-accept threshold
            if (
                decision.confidence >= self.config.auto_accept_threshold / 10.0
                and not decision.remaining_issues
            ):
                await self.events.emit(
                    DrawEvent.LOOP_TERMINATED,
                    reason="auto_accepted",
                )
                return LoopResult(
                    terminated_reason="auto_accepted",
                    final_images=images,
                    iterations_completed=iteration,
                )

    async def _handle_interrupt(self) -> str:
        """Handle pending interrupt. Returns 'terminate', 'steer', 'rollback', or 'continue'."""
        action = self.session.pending_action
        if action == "accept":
            return "terminate"
        if action == "steer":
            return "steer"
        if action == "modify":
            return "steer"
        if action == "rollback":
            return "rollback"
        if action == "pause":
            self.session.state = SessionState.INTERRUPTED
        return "continue"

    def _parse_rollback_target(self) -> int:
        if self.session.steer_message:
            try:
                return int(self.session.steer_message)
            except ValueError:
                pass
        return max(0, len(self.images_history) - 2)

    def _extract_best_images(self) -> list[ImageRecord]:
        if self.images_history:
            for images in reversed(self.images_history):
                if images:
                    return images
        return []

    def _estimate_context_tokens(self) -> int:
        total_chars = 0
        for it in self.session.iterations:
            total_chars += len(it.prompt)
            for insp in it.inspections:
                total_chars += len(insp.observation or "")
            if it.decision:
                total_chars += len(it.decision.reasoning or "")
        for obs in self.observations_history:
            if obs.decision:
                total_chars += len(obs.decision.reasoning or "")
        total_chars += len(self.session.user_request or "")
        return total_chars // 4

    def _extract_images_from_tool_results(
        self,
        results: list,
        prompt: str,
        iteration: int,
    ) -> list[ImageRecord]:
        images: list[ImageRecord] = []
        for tr in results:
            if isinstance(tr, object) and hasattr(tr, "metadata"):
                for img_info in tr.metadata.get("images", []):
                    if "error" not in img_info:
                        images.append(ImageRecord(
                            filename=img_info.get("path", "").split("/")[-1],
                            path=img_info.get("path", ""),
                            iteration=iteration,
                            seed=img_info.get("seed", -1),
                            width=img_info.get("width", 1024),
                            height=img_info.get("height", 1024),
                            prompt=prompt,
                        ))
        return images
