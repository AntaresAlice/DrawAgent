from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CompactedHistory:
    """Compressed representation of old iterations.

    Reference: opencode's CompactionRecord — structured summary preserving
    goal, progress, key decisions, and next steps.
    """

    goal: str = ""
    progress: list[str] = field(default_factory=list)
    key_decisions: list[str] = field(default_factory=list)
    prompt_evolution: list[str] = field(default_factory=list)
    best_image_ref: str | None = None
    remaining_issues: list[str] = field(default_factory=list)
    next_steps: str = ""

    def to_context_string(self) -> str:
        parts = ["<compacted_history>"]

        if self.goal:
            parts.append(f"<goal>{self.goal}</goal>")

        if self.progress:
            parts.append("<progress>")
            for item in self.progress:
                parts.append(f"  - {item}")
            parts.append("</progress>")

        if self.key_decisions:
            parts.append("<key_decisions>")
            for item in self.key_decisions:
                parts.append(f"  - {item}")
            parts.append("</key_decisions>")

        if self.prompt_evolution:
            parts.append("<prompt_evolution>")
            for item in self.prompt_evolution:
                parts.append(f"  - {item}")
            parts.append("</prompt_evolution>")

        if self.best_image_ref:
            parts.append(f"<best_image>{self.best_image_ref}</best_image>")

        if self.remaining_issues:
            parts.append("<remaining_issues>")
            for item in self.remaining_issues:
                parts.append(f"  - {item}")
            parts.append("</remaining_issues>")

        if self.next_steps:
            parts.append(f"<next_steps>{self.next_steps}</next_steps>")

        parts.append("</compacted_history>")
        return "\n".join(parts)

    @classmethod
    def from_iterations(cls, iterations: list[Any], user_request: str = "") -> CompactedHistory:
        """Create a compacted history from a list of Iteration objects."""
        ch = cls(goal=user_request)
        for it in iterations:
            ch.progress.append(f"Iteration {it.number}: prompt='{it.prompt[:80]}...'")
            if it.decision:
                ch.key_decisions.append(
                    f"Iter {it.number}: {'PASSED' if it.decision.passed else 'FAILED'} — "
                    f"{it.decision.reasoning[:100]}"
                )
            ch.prompt_evolution.append(f"Iter {it.number} prompt: {it.prompt[:100]}")
            if it.decision and it.decision.remaining_issues:
                for issue in it.decision.remaining_issues:
                    ch.remaining_issues.append(
                        f"[Iter {it.number}] {issue.get('issue', '')}"
                    )
        return ch
