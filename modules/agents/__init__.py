"""
Ostrich Agents Package
======================
Closed-loop orchestrator and delegate execution agents.
"""

from modules.agents.context_agent import ContextAgent, get_context_agent
from modules.agents.file_agent import FileAgent, get_file_agent
from modules.agents.io_agent import IOAgent, get_io_agent
from modules.agents.orchestrator import Orchestrator, get_orchestrator
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
from modules.agents.state import (
    AgentFeedback,
    SharedState,
    StepRecord,
    TaskStatus,
)
from modules.agents.system_agent import SystemAgent, get_system_agent
from modules.agents.ui_agent import UIAgent, get_ui_agent

__all__ = [
    # State & Feedback Models
    "SharedState",
    "TaskStatus",
    "DelegateType",
    "StepRecord",
    "AgentFeedback",
    # Quick Decision & Fast Router
    "QuickDecisionNode",
    "QuickDecisionResult",
    "get_quick_decision_node",
    # Orchestrator & Qwen planner
    "Orchestrator",
    "get_orchestrator",
    "RoutingAgent",
    "get_routing_agent",
    "OrchestratorDecision",
    # Delegate Agents
    "UIAgent",
    "get_ui_agent",
    "IOAgent",
    "get_io_agent",
    "SystemAgent",
    "get_system_agent",
    "FileAgent",
    "get_file_agent",
    "ContextAgent",
    "get_context_agent",
]
