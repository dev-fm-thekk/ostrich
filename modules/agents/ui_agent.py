"""
UI Delegate Agent
=================
Executes desktop application launching, window switching, state changes,
and split-screen layouts using Needle complete() for model prediction,
followed by deterministic execution of the resolved tool function.
"""

from __future__ import annotations

import inspect
import logging
import re
from typing import Any, Callable, Optional

from config.models import get_needle_model
from modules.agents.state import AgentFeedback
from modules.tools.window import (
    DesktopNavigator,
    get_desktop_navigator,
    list_windows,
    maximize_window,
    minimize_window,
    open_app,
    split_screen,
    switch_window,
)

log = logging.getLogger(__name__)

UI_TOOLS = [
    open_app,
    list_windows,
    switch_window,
    maximize_window,
    minimize_window,
    split_screen,
]


class UIAgent:
    """Delegate agent for application and window management operations."""

    def __init__(self, custom_tools: list[Any] | None = None) -> None:
        self.tools = custom_tools or UI_TOOLS
        self.tool_map: dict[str, Callable] = {
            t.__name__: t for t in self.tools if hasattr(t, "__name__")
        }
        self._executor: Any = None
        self._navigator: DesktopNavigator | None = None

    @property
    def navigator(self) -> DesktopNavigator:
        if self._navigator is None:
            self._navigator = get_desktop_navigator()
        return self._navigator

    @property
    def executor(self) -> Any:
        if self._executor is None:
            self._executor = get_needle_model(self.tools)
        return self._executor

    def _execute_tool(self, fn_name: str, fn_args: dict[str, Any]) -> Any:
        """Deterministically invoke a tool by name with arguments."""
        fn = self.tool_map.get(fn_name)
        if not fn:
            raise ValueError(f"Tool '{fn_name}' is not registered in UIAgent tool map.")

        sig = inspect.signature(fn)
        bound_args = {}
        for param in sig.parameters.values():
            if param.name in fn_args:
                bound_args[param.name] = fn_args[param.name]

        return fn(**bound_args)

    def _fallback_deterministic_call(self, instruction: str) -> tuple[str, dict[str, Any], Any]:
        """
        Deterministic intent resolution when the model produces no function calls.
        Guarantees the intended tool is executed deterministically.
        """
        inst_lower = instruction.strip().lower()

        # 1. Open / launch application
        if any(inst_lower.startswith(prefix) for prefix in ("open ", "launch ", "start ")):
            app = re.sub(r"^(open|launch|start)\s+(app\s+|application\s+|program\s+)?", "", inst_lower).strip()
            args = {"app_name": app}
            res = open_app(**args)
            return "open_app", args, res

        # 2. List windows
        if "list" in inst_lower and "window" in inst_lower:
            args: dict[str, Any] = {}
            res = list_windows()
            return "list_windows", args, res

        # 3. Switch / focus window
        if any(inst_lower.startswith(prefix) for prefix in ("switch ", "focus ")):
            target = re.sub(r"^(switch\s+to\s+|switch\s+window\s+|switch\s+|focus\s+window\s+|focus\s+)", "", inst_lower).strip()
            args = {"title": target}
            res = switch_window(**args)
            return "switch_window", args, res

        # 4. Maximize window
        if "maximize" in inst_lower:
            args = {}
            res = maximize_window()
            return "maximize_window", args, res

        # 5. Minimize window
        if "minimize" in inst_lower:
            args = {}
            res = minimize_window()
            return "minimize_window", args, res

        # 6. Split screen
        if "split" in inst_lower:
            args = {"left_target": "", "right_target": ""}
            res = split_screen(**args)
            return "split_screen", args, res

        raise RuntimeError(f"Unable to resolve UI instruction: '{instruction}'")

    def run(self, instruction: str) -> AgentFeedback:
        """
        Execute a UI / window navigation instruction using complete() followed by
        deterministic function invocation.
        """
        log.info("[UIAgent] Predicting tool for: '%s'", instruction)

        executed_tools: list[str] = []
        tool_results: list[Any] = []
        success = True
        error: str | None = None
        observation = ""

        try:
            # 1. Ask Needle to complete and predict function call(s)
            completion = self.executor.complete(instruction)
            # Only use confirmed function_calls — suppressed_calls are unreliable partial
            # predictions that the model itself rejected; skip them and fall to deterministic.
            calls = completion.get("function_calls", [])

            # 2. Deterministically invoke the predicted function(s)
            if calls:
                for call in calls:
                    fn_name = call.get("name")
                    fn_args = call.get("arguments", {})
                    log.info("[UIAgent] Deterministically executing '%s' with args %s", fn_name, fn_args)
                    result = self._execute_tool(fn_name, fn_args)
                    executed_tools.append(fn_name)
                    tool_results.append(result)

                    if isinstance(result, dict) and not result.get("success", True):
                        success = False
                        error = result.get("message") or result.get("error")
            else:
                # 3. Deterministic fallback if complete() returned no function calls
                log.info("[UIAgent] No function_calls from model, using deterministic fallback for: '%s'", instruction)
                fn_name, fn_args, result = self._fallback_deterministic_call(instruction)
                executed_tools.append(fn_name)
                tool_results.append(result)

                if isinstance(result, dict) and not result.get("success", True):
                    success = False
                    error = result.get("message") or result.get("error")

            # Extract observation from result
            if tool_results:
                primary = tool_results[0]
                if isinstance(primary, dict):
                    observation = primary.get("message") or str(primary)
                else:
                    observation = str(primary)
            else:
                observation = "UI action executed successfully."

            # Query visible windows for feedback state context
            data: dict[str, Any] = {"executed_tools": executed_tools}
            try:
                windows_res = self.navigator.list_windows()
                if isinstance(windows_res, dict) and windows_res.get("windows"):
                    wins = windows_res["windows"]
                    data["visible_windows"] = wins
                    if wins:
                        data["active_window"] = wins[0]
            except Exception as exc:
                log.debug("Failed querying active windows: %s", exc)

            return AgentFeedback(
                agent_name="ui_agent",
                success=success,
                action_taken=", ".join(executed_tools) if executed_tools else instruction,
                output=tool_results[0] if len(tool_results) == 1 else tool_results,
                observation=observation or "UI action completed.",
                error=error,
                data=data,
            )

        except Exception as exc:
            log.exception("[UIAgent] Execution error: %s", exc)
            return AgentFeedback(
                agent_name="ui_agent",
                success=False,
                action_taken=instruction,
                output=None,
                observation=f"Failed to execute UI action: {exc}",
                error=str(exc),
            )


_ui_agent_instance: UIAgent | None = None


def get_ui_agent() -> UIAgent:
    """Return a singleton UIAgent instance."""
    global _ui_agent_instance
    if _ui_agent_instance is None:
        _ui_agent_instance = UIAgent()
    return _ui_agent_instance
