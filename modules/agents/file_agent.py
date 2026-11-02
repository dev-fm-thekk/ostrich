"""
File Delegate Agent
===================
Executes filesystem queries and directory operations using Needle complete()
for model prediction, followed by deterministic execution of the resolved tool function.
"""

from __future__ import annotations

import inspect
import logging
import re
from typing import Any, Callable, Optional

from config.models import get_needle_model
from modules.agents.state import AgentFeedback
from modules.tools.file import FileNavigator, get_file_navigator, list_files

log = logging.getLogger(__name__)

FILE_TOOLS = [
    list_files,
]


class FileAgent:
    """Delegate agent for filesystem operations."""

    def __init__(self, custom_tools: list[Any] | None = None) -> None:
        self.tools = custom_tools or FILE_TOOLS
        self.tool_map: dict[str, Callable] = {
            t.__name__: t for t in self.tools if hasattr(t, "__name__")
        }
        self._executor: Any = None
        self._navigator: FileNavigator | None = None

    @property
    def navigator(self) -> FileNavigator:
        if self._navigator is None:
            self._navigator = get_file_navigator()
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
            raise ValueError(f"Tool '{fn_name}' is not registered in FileAgent tool map.")

        sig = inspect.signature(fn)
        bound_args = {}
        for param in sig.parameters.values():
            if param.name in fn_args:
                bound_args[param.name] = fn_args[param.name]

        return fn(**bound_args)

    def _fallback_deterministic_call(self, instruction: str) -> tuple[str, dict[str, Any], Any]:
        """
        Deterministic intent resolution when the model produces no function calls.
        Guarantees the intended filesystem tool is executed.
        """
        inst_lower = instruction.strip().lower()

        # Extract path if provided
        path_arg = "."
        m = re.search(r"(?:in|path|dir|directory|files|folder)\s+([~/A-Za-z0-9_.\-]+)", instruction, re.IGNORECASE)
        if m:
            path_arg = m.group(1).strip()
        elif inst_lower.startswith("list files ") or inst_lower.startswith("show files "):
            path_arg = re.sub(r"^(list\s+files\s+|show\s+files\s+)", "", instruction.strip()).strip()

        args = {"path": path_arg or "."}
        res = list_files(**args)
        return "list_files", args, res

    def run(self, instruction: str) -> AgentFeedback:
        """
        Execute a filesystem instruction using complete() followed by
        deterministic function invocation.
        """
        log.info("[FileAgent] Predicting tool for: '%s'", instruction)

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
                    log.info("[FileAgent] Deterministically executing '%s' with args %s", fn_name, fn_args)
                    result = self._execute_tool(fn_name, fn_args)
                    executed_tools.append(fn_name)
                    tool_results.append(result)

                    if isinstance(result, dict) and not result.get("success", True):
                        success = False
                        error = result.get("message") or result.get("error")
            else:
                # 3. Deterministic fallback if complete() returned no function calls
                log.info("[FileAgent] No function_calls from model, using deterministic fallback for: '%s'", instruction)
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
                observation = "File action executed successfully."

            return AgentFeedback(
                agent_name="file_agent",
                success=success,
                action_taken=", ".join(executed_tools) if executed_tools else instruction,
                output=tool_results[0] if len(tool_results) == 1 else tool_results,
                observation=observation or "File action completed.",
                error=error,
                data={"executed_tools": executed_tools},
            )

        except Exception as exc:
            log.exception("[FileAgent] Execution error: %s", exc)
            return AgentFeedback(
                agent_name="file_agent",
                success=False,
                action_taken=instruction,
                output=None,
                observation=f"Failed to execute file action: {exc}",
                error=str(exc),
            )


_file_agent_instance: FileAgent | None = None


def get_file_agent() -> FileAgent:
    """Return a singleton FileAgent instance."""
    global _file_agent_instance
    if _file_agent_instance is None:
        _file_agent_instance = FileAgent()
    return _file_agent_instance
