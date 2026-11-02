"""
Shared State and Agent Feedback Models
======================================
Defines the centralized state, step execution records, and feedback models
for the closed-loop orchestrator architecture.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class TaskStatus(str, Enum):
    INITIALIZING = "initializing"
    IN_PROGRESS = "in_progress"
    AWAITING_FEEDBACK = "awaiting_feedback"
    COMPLETED = "completed"
    FAILED = "failed"
    NEEDS_USER_INPUT = "needs_user_input"


class DelegateType(str, Enum):
    CONTEXT_AGENT = "context_agent"
    UI_AGENT = "ui_agent"
    IO_AGENT = "io_agent"
    SYSTEM_AGENT = "system_agent"
    FILE_AGENT = "file_agent"
    NONE = "none"


@dataclass
class AgentFeedback:
    """Standardized response contract returned by any delegate agent."""

    agent_name: str
    success: bool
    action_taken: str
    output: Any = None
    observation: str = ""
    error: Optional[str] = None
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_name": self.agent_name,
            "success": self.success,
            "action_taken": self.action_taken,
            "output": self.output,
            "observation": self.observation,
            "error": self.error,
            "data": self.data,
        }

    def __str__(self) -> str:
        status_str = "SUCCESS" if self.success else f"FAILED: {self.error}"
        return f"[{self.agent_name}] {self.action_taken} -> {status_str} | Obs: {self.observation}"


@dataclass
class StepRecord:
    """Historical trace record of a single micro-instruction executed by a delegate."""

    iteration: int
    delegate: str
    instruction: str
    success: bool
    output: Any = None
    observation: str = ""
    error: Optional[str] = None
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "iteration": self.iteration,
            "delegate": self.delegate,
            "instruction": self.instruction,
            "success": self.success,
            "output": self.output,
            "observation": self.observation,
            "error": self.error,
            "timestamp": self.timestamp,
        }


@dataclass
class SharedState:
    """Common shared state maintained across the orchestrator and all delegate agents."""

    task_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    user_query: str = ""
    status: TaskStatus = TaskStatus.INITIALIZING
    iteration: int = 0
    max_iterations: int = 15

    # Active Desktop Environment Context
    active_window: Optional[dict[str, Any]] = None
    ui_candidates: list[Any] = field(default_factory=list)

    # Dynamic Cross-Agent Blackboard
    blackboard: dict[str, Any] = field(default_factory=dict)

    # Execution History
    history: list[StepRecord] = field(default_factory=list)
    last_feedback: Optional[AgentFeedback] = None

    def record_step(self, delegate: str, instruction: str, feedback: AgentFeedback) -> StepRecord:
        """Record the outcome of a delegate execution into history."""
        self.iteration += 1
        record = StepRecord(
            iteration=self.iteration,
            delegate=delegate,
            instruction=instruction,
            success=feedback.success,
            output=feedback.output,
            observation=feedback.observation,
            error=feedback.error,
        )
        self.history.append(record)
        self.last_feedback = feedback
        return record

    def get_history_summary(self, max_steps: int = 5) -> str:
        """Return a formatted string of the most recent execution steps."""
        if not self.history:
            return "No previous steps executed."
        recent = self.history[-max_steps:]
        lines = []
        for r in recent:
            status = "✓ OK" if r.success else f"✗ ERROR ({r.error})"
            lines.append(f"Step {r.iteration} [{r.delegate}]: '{r.instruction}' -> {status} ({r.observation})")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "user_query": self.user_query,
            "status": self.status.value,
            "iteration": self.iteration,
            "max_iterations": self.max_iterations,
            "active_window": self.active_window,
            "blackboard": self.blackboard,
            "history": [r.to_dict() for r in self.history],
            "last_feedback": self.last_feedback.to_dict() if self.last_feedback else None,
        }
