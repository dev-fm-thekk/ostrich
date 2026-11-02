"""
Quick Decision Node
===================
Determines whether a user instruction is a direct, single-step "quick" action
(e.g., volume, mute, brightness, wifi, bluetooth, window management) or
requires the full closed-loop orchestrator planning pipeline.

Supports two routing engines:
  1. **Ruleset Engine (Instant, <0.1ms)**: Fast-path matching based on keyword
     heuristics and intent patterns. Eliminates model latency and dependency issues.
  2. **Needle Model Engine**: Uses the local Needle tool-calling model loaded with
     routing meta-tools for semantic tool-selection.

By default, runs in **Hybrid Mode**:
  - Checks the fast ruleset first for zero-latency routing (<0.1ms).
  - Falls back to the Needle model for ambiguous natural language queries.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, List, Optional

log = logging.getLogger(__name__)

# Optional Needle import
try:
    import needle
    _HAS_NEEDLE = True
except ImportError:
    _HAS_NEEDLE = False


# ---------------------------------------------------------------------------
# Result Dataclass
# ---------------------------------------------------------------------------

@dataclass
class QuickDecisionResult:
    """
    Standard routing output contract compatible with the Orchestrator.

    Attributes:
        delegate: Target agent ('system_agent', 'ui_agent', 'io_agent', 'file_agent', or 'planning').
        is_quick: True if this is a single-step action needing no UI search or planning.
        fast_path: True if the orchestrator should bypass Qwen and execute directly.
        quick_confidence: Confidence score between 0.0 and 1.0.
        confidence: Alias for quick_confidence.
        model_used: Identification of the decision engine ('ruleset', 'needle', etc.).
    """
    delegate: str
    is_quick: bool
    fast_path: bool
    quick_confidence: float = 1.0
    model_used: str = "ruleset"

    @property
    def confidence(self) -> float:
        return self.quick_confidence


# ---------------------------------------------------------------------------
# Ruleset Knowledge Base
# ---------------------------------------------------------------------------

_SYSTEM_RULES: List[str] = [
    # Audio volume & mute
    "volume", "sound", "audio", "mute", "unmute", "louder", "quieter",
    # Display brightness
    "brightness", "dim screen", "brighten screen",
    # Network & wireless
    "wifi", "wi-fi", "internet", "bluetooth", "airplane mode",
    # Power & hardware session
    "battery", "power status", "lock screen", "sleep", "suspend", "hibernate",
]

_UI_RULES: List[str] = [
    "open app", "launch app", "start app", "close app",
    "open application", "launch application", "start application",
    "open program", "launch program",
    "open ", "launch ", "close window", "close this",
    "switch window", "focus window", "list windows", "show windows",
    "maximize", "minimize", "restore window", "split screen",
]

_IO_RULES: List[str] = [
    "click at", "mouse click", "double click", "right click",
    "move mouse", "move cursor",
    "press key", "type text", "keyboard shortcut", "hotkey",
    "press enter", "press tab", "press escape",
]

_FILE_RULES: List[str] = [
    "list files", "show directory", "show files", "list directory",
    "open folder", "show folder contents",
]

# Patterns that indicate multi-step or visual planning is required
_PLANNING_PATTERNS: List[re.Pattern] = [
    re.compile(r"\b(find|search for|look for)\b.*\b(and|then)\b", re.IGNORECASE),
    re.compile(r"\bclick\b.*\b(button|icon|link|menu|tab|checkbox|field|input)\b", re.IGNORECASE),
    re.compile(r"\b(then|after that|next|finally)\b", re.IGNORECASE),
    re.compile(r"\b(login|sign in|sign up|fill form|checkout|book|order)\b", re.IGNORECASE),
    re.compile(r"\b(navigate to|browse to|go to)\b", re.IGNORECASE),
    re.compile(r"\b(read|extract|copy|scrape)\b.*\b(from|page|screen)\b", re.IGNORECASE),
]


# ---------------------------------------------------------------------------
# Needle Routing Tools
# ---------------------------------------------------------------------------

def _build_needle_router_tools() -> list[Any]:
    """Define lightweight routing tools for the Needle model."""
    if not _HAS_NEEDLE:
        return []

    @needle.tool
    def control_system(action: str = "adjust"):
        """Hardware/system control: volume up/down, mute/unmute audio, screen brightness, wifi on/off, bluetooth, battery, lock screen."""
        return {"delegate": "system_agent", "is_quick": True}

    @needle.tool
    def control_window(action: str = "open"):
        """Window management: open application, launch program, close window, minimize, maximize, switch active window."""
        return {"delegate": "ui_agent", "is_quick": True}

    @needle.tool
    def control_input(action: str = "click"):
        """Direct input control: click at coordinates, move cursor, type text string, keyboard hotkeys or shortcuts."""
        return {"delegate": "io_agent", "is_quick": True}

    @needle.tool
    def control_filesystem(action: str = "list"):
        """Filesystem queries: list files in folder, show directory contents, inspect files."""
        return {"delegate": "file_agent", "is_quick": True}

    @needle.tool
    def route_to_planning(goal: str = "plan"):
        """Multi-step tasks requiring planning: searching UI elements, finding buttons on screen, complex workflows, web tasks."""
        return {"delegate": "planning", "is_quick": False}

    return [control_system, control_window, control_input, control_filesystem, route_to_planning]


# ---------------------------------------------------------------------------
# Quick Decision Node Implementation
# ---------------------------------------------------------------------------

class QuickDecisionNode:
    """
    Decides whether an instruction goes directly to quick tools or orchestrator planning.

    Modes:
      - 'hybrid' (default): checks fast ruleset first (<0.1ms). If confident, returns
        immediately. Falls back to Needle model for ambiguous queries.
      - 'ruleset': purely ruleset-driven (zero model latency).
      - 'needle': uses Needle model for all non-trivial classifications.
    """

    def __init__(self, mode: str = "hybrid", preload: bool = False) -> None:
        self.mode = mode.lower()
        self._needle_instance: Any = None
        self._needle_tools: list[Any] = []
        self._tool_map: dict[str, Any] = {}

        if preload and self.mode in ("hybrid", "needle"):
            self._ensure_needle()

        log.debug("[QuickDecisionNode] Initialized in mode='%s'", self.mode)

    def _ensure_needle(self) -> Any:
        """Lazy-initialize the Needle model executor."""
        if not _HAS_NEEDLE:
            log.warning("[QuickDecisionNode] Needle package not available; using ruleset fallback.")
            return None

        if self._needle_instance is None:
            log.info("[QuickDecisionNode] Initializing Needle router model...")
            self._needle_tools = _build_needle_router_tools()
            self._tool_map = {t.__name__: t for t in self._needle_tools if hasattr(t, "__name__")}
            self._needle_instance = needle.Needle(tools=self._needle_tools, stateless=True)
            log.info("[QuickDecisionNode] Needle router model ready.")

        return self._needle_instance

    def _classify_ruleset(self, query: str) -> Optional[QuickDecisionResult]:
        """
        Evaluate query against the instant ruleset (<0.1ms).
        Returns QuickDecisionResult if matched with high confidence, else None.
        """
        q = query.strip().lower()

        # 1. Multi-step or UI-search planning triggers override quick actions
        for pat in _PLANNING_PATTERNS:
            if pat.search(q):
                return QuickDecisionResult(
                    delegate="planning",
                    is_quick=False,
                    fast_path=False,
                    quick_confidence=0.95,
                    model_used="ruleset",
                )

        # 2. System hardware operations are always quick (volume, mute, wifi, brightness, etc.)
        if any(term in q for term in _SYSTEM_RULES):
            return QuickDecisionResult(
                delegate="system_agent",
                is_quick=True,
                fast_path=True,
                quick_confidence=0.95,
                model_used="ruleset",
            )

        # 3. Direct window management (e.g. "open calculator", "maximize", "switch window")
        if any(term in q for term in _UI_RULES):
            return QuickDecisionResult(
                delegate="ui_agent",
                is_quick=True,
                fast_path=True,
                quick_confidence=0.85,
                model_used="ruleset",
            )

        # 4. Direct coordinate or text input (e.g. "click at 200 400", "type hello")
        if any(term in q for term in _IO_RULES):
            return QuickDecisionResult(
                delegate="io_agent",
                is_quick=True,
                fast_path=True,
                quick_confidence=0.85,
                model_used="ruleset",
            )

        # 5. Direct filesystem inspection
        if any(term in q for term in _FILE_RULES):
            return QuickDecisionResult(
                delegate="file_agent",
                is_quick=True,
                fast_path=True,
                quick_confidence=0.85,
                model_used="ruleset",
            )

        return None

    def _classify_needle(self, query: str) -> QuickDecisionResult:
        """Execute semantic routing via Needle complete() and deterministic tool execution."""
        executor = self._ensure_needle()
        if executor is None:
            # Needle unavailable, default to planning
            return QuickDecisionResult(
                delegate="planning",
                is_quick=False,
                fast_path=False,
                quick_confidence=0.5,
                model_used="fallback",
            )

        try:
            res = executor.complete(query)
            # Only use confirmed function_calls — suppressed_calls are model-rejected predictions
            calls = res.get("function_calls", [])

            if calls and isinstance(calls[0], dict):
                first = calls[0]
                fn_name = first.get("name")
                fn = self._tool_map.get(fn_name)
                if fn:
                    tool_res = fn(**first.get("arguments", {}))
                    if isinstance(tool_res, dict):
                        delegate = tool_res.get("delegate", "planning")
                        is_quick = tool_res.get("is_quick", False)
                        fast_path = is_quick and delegate != "planning"
                        confidence = float(res.get("confidence", 0.8))

                        return QuickDecisionResult(
                            delegate=delegate,
                            is_quick=is_quick,
                            fast_path=fast_path,
                            quick_confidence=confidence,
                            model_used="needle",
                        )

            # If no tool was called, or called planning
            return QuickDecisionResult(
                delegate="planning",
                is_quick=False,
                fast_path=False,
                quick_confidence=0.7,
                model_used="needle",
            )

        except Exception as exc:
            log.warning("[QuickDecisionNode] Needle inference error: %s — falling back to planning", exc)
            return QuickDecisionResult(
                delegate="planning",
                is_quick=False,
                fast_path=False,
                quick_confidence=0.0,
                model_used="needle_error",
            )

    def classify(self, user_query: str) -> QuickDecisionResult:
        """
        Classify a user query to decide fast-path dispatch vs planning.

        Args:
            user_query: The natural language instruction from the user.

        Returns:
            QuickDecisionResult with delegate, is_quick, and fast_path indicators.
        """
        # Mode: purely Needle model
        if self.mode == "needle":
            return self._classify_needle(user_query)

        # Mode: purely Ruleset
        if self.mode == "ruleset":
            res = self._classify_ruleset(user_query)
            if res is not None:
                return res
            return QuickDecisionResult(
                delegate="planning",
                is_quick=False,
                fast_path=False,
                quick_confidence=0.5,
                model_used="ruleset",
            )

        # Mode: Hybrid (default) — Ruleset first (<0.1ms), then Needle if ambiguous
        ruleset_res = self._classify_ruleset(user_query)
        if ruleset_res is not None:
            log.debug("[QuickDecisionNode] Fast ruleset matched: %s -> %s", user_query, ruleset_res.delegate)
            return ruleset_res

        # Ambiguous query: consult the Needle model
        log.debug("[QuickDecisionNode] Ruleset ambiguous for '%s', consulting Needle model...", user_query)
        return self._classify_needle(user_query)


# Singleton instance helper
_quick_decision_node_instance: QuickDecisionNode | None = None


def get_quick_decision_node(mode: str = "hybrid") -> QuickDecisionNode:
    """Return a shared QuickDecisionNode instance."""
    global _quick_decision_node_instance
    if _quick_decision_node_instance is None:
        _quick_decision_node_instance = QuickDecisionNode(mode=mode)
    return _quick_decision_node_instance
