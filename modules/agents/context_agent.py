"""
Context Delegate Agent
======================
Performs AT-SPI desktop accessibility tree introspection, UI element grounding,
and candidate coordinate resolution using `modules.context.ui_tree.tree`.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from modules.agents.state import AgentFeedback
from modules.context.ui_tree.tree import (
    Candidate,
    describe,
    find_active_window,
    get_candidates,
    get_candidates_str,
    get_element_bounds,
)

log = logging.getLogger(__name__)


class ContextAgent:
    """Delegate agent for visual/semantic grounding and accessibility tree inspection."""

    def resolve_target(
        self,
        target_name: Optional[str] = None,
        action: Optional[str] = None,
        role: Optional[str] = None,
        limit: int = 10,
    ) -> AgentFeedback:
        """Find matching UI candidates in the currently active window."""
        win = find_active_window()
        if win is None:
            return AgentFeedback(
                agent_name="context_agent",
                success=False,
                action_taken="resolve_target",
                observation="No active desktop window detected.",
                error="no_active_window",
            )

        # Query candidates using optimized multi-filter tree search
        candidates: list[Candidate] = get_candidates(
            root=win,
            action=action,
            role=role,
            name=target_name,
            include_bounds=True,
        )

        win_info = None
        try:
            win_info = {
                "name": getattr(win, "get_name", lambda: "")(),
                "role": getattr(win, "get_role_name", lambda: "")(),
                "bounds": get_element_bounds(win),
            }
        except Exception:
            pass

        if not candidates:
            return AgentFeedback(
                agent_name="context_agent",
                success=False,
                action_taken=f"Search target '{target_name}' (action={action}, role={role})",
                observation=f"No matching UI elements found for target '{target_name}'.",
                error="element_not_found",
                data={"active_window": win_info} if win_info else {},
            )

        # Best candidate (first matching ranked candidate)
        best = candidates[0]
        center = best.center or (best.bounds[0] + best.bounds[2] // 2, best.bounds[1] + best.bounds[3] // 2) if best.bounds else None

        summary_str = get_candidates_str(candidates[:limit], include_bounds=True)
        observation = f"Resolved {len(candidates)} candidates. Primary match: '{best.name}' [{best.role}] at {center}."

        return AgentFeedback(
            agent_name="context_agent",
            success=True,
            action_taken=f"Resolved '{target_name}'",
            output=summary_str,
            observation=observation,
            data={
                "candidate_count": len(candidates),
                "candidates": candidates,
                "active_window": win_info,
                "best_candidate_id": best.id,
                "best_candidate_name": best.name,
                "best_candidate_role": best.role,
                "center": center,
                "bounds": best.bounds,
                "candidates_str": summary_str,
            },
        )

    def run(self, instruction: str) -> AgentFeedback:
        """Inspect and parse context based on instruction."""
        log.info("[ContextAgent] Executing: '%s'", instruction)
        # Check active window description
        win = find_active_window()
        if win is None:
            return AgentFeedback(
                agent_name="context_agent",
                success=False,
                action_taken=instruction,
                observation="No active window found.",
                error="no_active_window",
            )

        win_desc = describe(win)
        listing = get_candidates_str(win, include_bounds=True)
        obs = f"Active window: {win_desc}\nCandidates:\n{listing[:500]}"

        return AgentFeedback(
            agent_name="context_agent",
            success=True,
            action_taken=instruction,
            output=listing,
            observation=obs,
        )


def get_context_agent() -> ContextAgent:
    """Return a configured ContextAgent instance."""
    return ContextAgent()
