"""
Routing and Decision Agent
==========================
Uses the local Qwen2.5 1.4B model to plan next steps, route instructions
to delegate agents, and evaluate closed-loop feedback.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from openai import OpenAI
from pydantic import BaseModel, Field

from config.models import get_openai_client
from config.prompts import ORCHESTRATION_AGENT_INSTRUCTION
from modules.agents.state import DelegateType, SharedState, TaskStatus

log = logging.getLogger(__name__)


class OrchestratorDecision(BaseModel):
    """Structured decision returned by Qwen2.5 1.4B for closed-loop execution."""

    thought: str = Field(
        ...,
        description="Reasoning analyzing current desktop state, previous step feedback, and next goal",
    )
    status: TaskStatus = Field(
        ...,
        description="Current overall task status: in_progress, completed, failed, or needs_user_input",
    )
    delegate: DelegateType = Field(
        ...,
        description="Target delegate agent to execute next: ui_agent, io_agent, context_agent, system_agent, file_agent, or none",
    )
    instruction: str = Field(
        ...,
        description="Clear, atomic natural language instruction for the chosen delegate agent",
    )
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Extracted key parameters (e.g. app_name, x, y, text, action)",
    )
    verification_goal: Optional[str] = Field(
        None,
        description="Expected observation to verify that this step succeeded",
    )


class RoutingAgent:
    """Handles prompt construction and model invocation for the Orchestrator."""

    def __init__(self, client: Optional[OpenAI] = None, model_name: str = "local-model") -> None:
        self.client = client or get_openai_client()
        self.model_name = model_name

    def build_prompt_context(self, state: SharedState) -> str:
        """Serialize current shared state into a context prompt for Qwen2.5 1.4B."""
        sections = [
            f"User Goal: \"{state.user_query}\"",
            f"Current Iteration: {state.iteration} / {state.max_iterations}",
        ]

        # Active window context
        if state.active_window:
            w = state.active_window
            sections.append(f"Active Window: '{w.get('name', 'Unknown')}' [{w.get('role', 'window')}]")
        else:
            sections.append("Active Window: None / Desktop")

        # Blackboard variables (e.g., coordinates, IDs)
        if state.blackboard:
            bb_items = [f"{k}={v}" for k, v in list(state.blackboard.items())[:6]]
            sections.append(f"Blackboard Context: {', '.join(bb_items)}")

        # Last Feedback
        if state.last_feedback:
            fb = state.last_feedback
            status_text = "SUCCESS" if fb.success else f"FAILED: {fb.error}"
            sections.append(
                f"Last Agent Feedback [{fb.agent_name}]:\n"
                f"  Action: {fb.action_taken}\n"
                f"  Status: {status_text}\n"
                f"  Observation: {fb.observation[:300]}"
            )
            if fb.agent_name == "system_agent" and fb.success:
                sections.append("System control executed successfully. If the user goal is complete, return status='completed' and delegate='none'.")
        else:
            sections.append("Last Agent Feedback: None (initial turn)")
            query_lower = state.user_query.lower()
            quick_system_keywords = ("volume", "brightness", "mute", "unmute", "wifi", "wi-fi", "bluetooth", "battery", "lock screen")
            if any(kw in query_lower for kw in quick_system_keywords):
                sections.append("Quick Operation: System hardware/environment control detected. Route directly to system_agent.")

        # History summary
        history_summary = state.get_history_summary(max_steps=4)
        sections.append(f"Execution History:\n{history_summary}")

        sections.append(
            "\nDecide the NEXT atomic step. Choose the delegate agent, provide its instruction, "
            "and output valid JSON matching the schema."
        )

        return "\n\n".join(sections)

    def plan_next_step(self, state: SharedState) -> OrchestratorDecision:
        """Call Qwen2.5 1.4B to generate the next routing decision."""
        user_prompt = self.build_prompt_context(state)

        # Attempt structured output parsing
        try:
            completion = self.client.beta.chat.completions.parse(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": ORCHESTRATION_AGENT_INSTRUCTION},
                    {"role": "user", "content": user_prompt},
                ],
                response_format=OrchestratorDecision,
                temperature=0,
            )
            msg = completion.choices[0].message
            if msg.parsed is not None:
                return msg.parsed
            raw_content = msg.content or ""
        except Exception as exc:
            log.warning("Structured parse failed (%s); attempting JSON text extraction", exc)
            # Standard completion fallback
            resp = self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": ORCHESTRATION_AGENT_INSTRUCTION},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0,
            )
            raw_content = resp.choices[0].message.content or ""

        # Fallback: Extract JSON block from response text
        return self._extract_json_decision(raw_content, state)

    def _extract_json_decision(self, raw_text: str, state: SharedState) -> OrchestratorDecision:
        """Extract and validate JSON block from model response text."""
        # Match JSON object in markdown or raw text
        match = re.search(r"\{.*\}", raw_text, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(0))
                return OrchestratorDecision.model_validate(data)
            except Exception as exc:
                log.debug("JSON extraction validation error: %s", exc)

        # Fallback decision if model response could not be parsed
        log.warning("Unable to parse decision from model output: %r", raw_text)
        return OrchestratorDecision(
            thought=f"Raw model response could not be parsed as JSON: {raw_text[:100]}",
            status=TaskStatus.FAILED,
            delegate=DelegateType.NONE,
            instruction="Unable to determine next step.",
        )


def get_routing_agent() -> RoutingAgent:
    """Return a configured RoutingAgent instance."""
    return RoutingAgent()
