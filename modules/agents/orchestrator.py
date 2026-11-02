"""
Orchestrator Agent
==================
Master coordinator with a two-tier routing pipeline:

    user_input
        │
        ▼
    [Quick Decision Node]  ──── fast-path? ──── YES ──▶  system_tools / delegate agent
    (Needle / Ruleset)                                        (single shot, no Qwen)
        │
        │ NO (planning / complex task)
        ▼
    [Qwen2.5 1.4B]  ──── closed loop ──▶  delegate agent ──▶ feedback ──▶ re-plan
                         (until done or budget exhausted)

The Quick Decision Node inspects user input using a fast ruleset (<0.1ms) and
the Needle tool-calling model. For direct commands like "increase volume",
"mute", "turn off wifi", or "open calculator", it routes directly to the delegate
agent without touching Qwen at all.
"""

from __future__ import annotations

import logging
import sys
from typing import Any, Optional, Union

from modules.agents.context_agent import ContextAgent, get_context_agent
from modules.agents.file_agent import FileAgent, get_file_agent
from modules.agents.io_agent import IOAgent, get_io_agent
from modules.agents.quick_decision import (
    QuickDecisionNode,
    QuickDecisionResult,
    get_quick_decision_node,
)
from modules.agents.routing_agent import (
    DelegateType,
    OrchestratorDecision,
    RoutingAgent,
    get_routing_agent,
)
from modules.agents.state import AgentFeedback, SharedState, TaskStatus
from modules.agents.system_agent import SystemAgent, get_system_agent
from modules.agents.ui_agent import UIAgent, get_ui_agent

log = logging.getLogger(__name__)


class Orchestrator:
    """
    Master agent driving the two-tier task execution pipeline.

    Tier 1 — Quick Decision fast path:
        Single-step commands (e.g. "mute", "wifi off", "volume up 20%")
        are classified instantly via ruleset/Needle and dispatched directly
        to the matching delegate agent. No Qwen call is made.

    Tier 2 — Qwen2.5 closed loop:
        Complex or multi-step tasks go through iterative Qwen2.5 1.4B planning:
        plan → dispatch → feedback → re-plan until complete or budget runs out.
    """

    def __init__(
        self,
        quick_router: Optional[QuickDecisionNode] = None,
        router: Optional[RoutingAgent] = None,
        ui_agent: Optional[UIAgent] = None,
        io_agent: Optional[IOAgent] = None,
        context_agent: Optional[ContextAgent] = None,
        system_agent: Optional[SystemAgent] = None,
        file_agent: Optional[FileAgent] = None,
    ) -> None:
        # Tier 1: Quick decision router (Needle / Ruleset)
        self.quick_router = quick_router or get_quick_decision_node()

        # Tier 2: Qwen2.5 1.4B — planning router for complex tasks
        self.router = router or get_routing_agent()

        # Delegate execution agents
        self.ui_agent = ui_agent or get_ui_agent()
        self.io_agent = io_agent or get_io_agent()
        self.context_agent = context_agent or get_context_agent()
        self.system_agent = system_agent or get_system_agent()
        self.file_agent = file_agent or get_file_agent()

    # ------------------------------------------------------------------
    # Internal: dispatch a structured decision to the right delegate
    # ------------------------------------------------------------------

    def dispatch(self, decision: OrchestratorDecision) -> AgentFeedback:
        """Route a planning decision to the designated delegate agent (no state passed to tools)."""
        delegate = decision.delegate
        instruction = decision.instruction
        params = decision.parameters

        log.info("[Orchestrator] Dispatching to '%s': %s", delegate, instruction)

        if delegate == DelegateType.UI_AGENT:
            return self.ui_agent.run(instruction)

        elif delegate == DelegateType.IO_AGENT:
            return self.io_agent.run(instruction, parameters=params)

        elif delegate == DelegateType.CONTEXT_AGENT:
            target = params.get("target_name") or params.get("target")
            if target:
                return self.context_agent.resolve_target(
                    target_name=str(target),
                    action=params.get("action"),
                    role=params.get("role"),
                )
            return self.context_agent.run(instruction)

        elif delegate == DelegateType.SYSTEM_AGENT:
            return self.system_agent.run(instruction)

        elif delegate == DelegateType.FILE_AGENT:
            return self.file_agent.run(instruction)

        elif delegate == DelegateType.NONE:
            return AgentFeedback(
                agent_name="orchestrator",
                success=True,
                action_taken="none",
                observation="No action required.",
            )

        return AgentFeedback(
            agent_name="orchestrator",
            success=False,
            action_taken="unknown_delegate",
            observation=f"Delegate '{delegate}' is not supported.",
            error=f"unsupported_delegate_{delegate}",
        )

    # ------------------------------------------------------------------
    # Internal: dispatch directly from a fast route
    # ------------------------------------------------------------------

    def _dispatch_fast(
        self, fast_route: Any, user_query: str
    ) -> AgentFeedback:
        """
        Execute a fast-path dispatch using the quick classification result.
        Builds a minimal OrchestratorDecision and delegates directly without passing state.
        """
        try:
            delegate_type = DelegateType(fast_route.delegate)
        except ValueError:
            log.warning("[Orchestrator] Unknown delegate '%s', falling back.", fast_route.delegate)
            delegate_type = DelegateType.NONE

        decision = OrchestratorDecision(
            thought=f"[Fast-path: {fast_route.model_used}] delegate={fast_route.delegate}, confidence={fast_route.quick_confidence:.2f}",
            status=TaskStatus.IN_PROGRESS,
            delegate=delegate_type,
            instruction=user_query,
            parameters={},
        )
        return self.dispatch(decision)

    # ------------------------------------------------------------------
    # Public: run a user query through the two-tier pipeline
    # ------------------------------------------------------------------

    def run(self, user_query: str, max_iterations: int = 15) -> SharedState:
        """
        Execute a user query.

        Pipeline:
            user_query → QuickDecisionNode → fast-path (delegate agent)
                                          ↘ planning path (Qwen2.5 closed loop)
        """
        state = SharedState(
            user_query=user_query,
            max_iterations=max_iterations,
            status=TaskStatus.IN_PROGRESS,
        )

        print(f'\n[Ostrich] "{user_query}"')
        log.info("[Orchestrator] Task %s: %s", state.task_id, user_query)

        # ── Tier 1: Quick Decision classification ─────────────────────
        decision_res = self.quick_router.classify(user_query)
        print(
            f"[{decision_res.model_used.capitalize()}] delegate={decision_res.delegate} | "
            f"quick={decision_res.is_quick} ({decision_res.quick_confidence:.0%}) | "
            f"fast_path={decision_res.fast_path}"
        )

        if decision_res.fast_path:
            # Direct dispatch — skip Qwen entirely
            print(f"[Fast Path] → {decision_res.delegate}")
            feedback = self._dispatch_fast(decision_res, user_query)
            state.record_step(decision_res.delegate, user_query, feedback)
            state.status = TaskStatus.COMPLETED if feedback.success else TaskStatus.FAILED
            flag = "✓" if feedback.success else "✗"
            print(f"[{flag}] {feedback.observation}")
            return state

        # ── Tier 2: Qwen2.5 closed-loop planning ──────────────────────
        print("[Planning Path] → Qwen2.5 1.4B")

        while state.status == TaskStatus.IN_PROGRESS and state.iteration < state.max_iterations:
            print(f"\n--- [Cycle {state.iteration + 1}/{state.max_iterations}] ---")

            # 1. Ask Qwen to plan the next atomic step
            decision: OrchestratorDecision = self.router.plan_next_step(state)
            print(f"Thought : {decision.thought}")
            print(f"Action  : {decision.delegate.value} → '{decision.instruction}'")

            # 2. Terminal status from the model?
            if decision.status == TaskStatus.COMPLETED:
                state.status = TaskStatus.COMPLETED
                print(f"\n[Done] Task completed in {state.iteration} step(s).")
                break

            if decision.status in (TaskStatus.FAILED, TaskStatus.NEEDS_USER_INPUT):
                state.status = decision.status
                print(f"\n[Done] Task ended: {state.status.value}")
                break

            # 3. Dispatch to the chosen delegate (pure tool calling, no state passed)
            feedback = self.dispatch(decision)

            # 4. Record step + surface feedback (state updated exclusively by orchestrator)
            state.record_step(decision.delegate.value, decision.instruction, feedback)
            flag = "✓" if feedback.success else "✗"
            print(f"Feedback [{flag}]: {feedback.observation}")

            # 5. Cache any resolved coordinates & UI context into the shared state
            if feedback.data.get("center"):
                state.blackboard["target_center"] = feedback.data["center"]
                state.blackboard["target_bounds"] = feedback.data.get("bounds")
                state.blackboard["target_id"] = feedback.data.get("best_candidate_id")

            if feedback.data.get("candidates"):
                state.ui_candidates = feedback.data["candidates"]

            if feedback.data.get("active_window"):
                state.active_window = feedback.data["active_window"]

            if feedback.data.get("visible_windows"):
                state.blackboard["visible_windows"] = feedback.data["visible_windows"]

        # Budget exhausted
        if state.iteration >= state.max_iterations and state.status == TaskStatus.IN_PROGRESS:
            state.status = TaskStatus.FAILED
            print(f"\n[Halt] Reached max iteration budget ({state.max_iterations}).")

        return state

    # ------------------------------------------------------------------
    # Public: interactive terminal loop
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Interactive terminal loop — accepts user commands until exit."""
        print("=" * 60)
        print(" Ostrich AI Agent")
        print(" user_input → Quick Decision (Needle/Ruleset) → delegate | orchestrator")
        print(" Type 'exit' or 'quit' to stop.")
        print("=" * 60)

        while True:
            try:
                user_input = input("\nostrich> ").strip()
                if not user_input:
                    continue
                if user_input.lower() in ("exit", "quit", "q"):
                    print("Exiting Ostrich. Goodbye!")
                    break

                self.run(user_input)

            except KeyboardInterrupt:
                print("\nInterrupted. Exiting.")
                break
            except Exception as exc:
                print(f"[Error] {exc}", file=sys.stderr)
                log.exception("Orchestrator loop error: %s", exc)


def get_orchestrator() -> Orchestrator:
    """Return a configured Orchestrator instance."""
    return Orchestrator()


if __name__ == "__main__":
    Orchestrator().start()
