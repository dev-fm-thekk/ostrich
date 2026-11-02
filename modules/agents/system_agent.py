"""
System Delegate Agent
=====================
Executes system controls (volume, brightness, wifi, bluetooth, battery, lock)
using Needle complete() for model prediction, followed by deterministic
execution of the resolved tool function.
"""

from __future__ import annotations

import inspect
import logging
import re
from typing import Any, Callable, Optional

from config.models import get_needle_model
from modules.agents.state import AgentFeedback
from modules.tools.system import (
    SystemNavigator,
    connect_wifi,
    disconnect_wifi,
    get_battery_status,
    get_bluetooth_status,
    get_brightness,
    get_system_info,
    get_system_navigator,
    get_volume,
    get_wifi_status,
    lock_screen,
    mute_volume,
    scan_wifi,
    set_bluetooth,
    set_brightness,
    set_mute,
    set_volume,
    set_wifi,
)

log = logging.getLogger(__name__)

SYSTEM_TOOLS = [
    get_system_info,
    get_volume,
    set_volume,
    set_mute,
    mute_volume,
    get_brightness,
    set_brightness,
    get_wifi_status,
    set_wifi,
    scan_wifi,
    connect_wifi,
    disconnect_wifi,
    get_bluetooth_status,
    set_bluetooth,
    get_battery_status,
    lock_screen,
]


class SystemAgent:
    """Delegate agent for hardware controls and OS environment settings."""

    def __init__(self, custom_tools: list[Any] | None = None) -> None:
        self.tools = custom_tools or SYSTEM_TOOLS
        self.tool_map: dict[str, Callable] = {
            t.__name__: t for t in self.tools if hasattr(t, "__name__")
        }
        self._executor: Any = None
        self._navigator: SystemNavigator | None = None

    @property
    def navigator(self) -> SystemNavigator:
        if self._navigator is None:
            self._navigator = get_system_navigator()
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
            raise ValueError(f"Tool '{fn_name}' is not registered in SystemAgent tool map.")

        sig = inspect.signature(fn)
        bound_args = {}
        for param in sig.parameters.values():
            if param.name in fn_args:
                val = fn_args[param.name]
                # Coerce integer levels if required
                if param.name == "level" and isinstance(val, (str, float)):
                    try:
                        val = int(val)
                    except ValueError:
                        pass
                bound_args[param.name] = val

        return fn(**bound_args)

    def _fallback_deterministic_call(self, instruction: str) -> tuple[str, dict[str, Any], Any]:
        """
        Deterministic intent resolution when the model produces no function calls.
        Guarantees the intended system control tool is executed.
        """
        inst_lower = instruction.strip().lower()

        # 1. Volume / Mute
        if "unmute" in inst_lower:
            args = {"mute": False}
            res = set_mute(**args)
            return "set_mute", args, res
        if "mute" in inst_lower:
            args = {}
            res = mute_volume()
            return "mute_volume", args, res
        if any(term in inst_lower for term in ("volume", "sound", "audio")):
            nums = re.findall(r"\d+", inst_lower)
            if nums:
                level = int(nums[0])
                args = {"level": level}
                res = set_volume(**args)
                return "set_volume", args, res
            else:
                args = {}
                res = get_volume()
                return "get_volume", args, res

        # 2. Brightness
        if "brightness" in inst_lower:
            nums = re.findall(r"\d+", inst_lower)
            if nums:
                level = int(nums[0])
                args = {"level": level}
                res = set_brightness(**args)
                return "set_brightness", args, res
            else:
                args = {}
                res = get_brightness()
                return "get_brightness", args, res

        # 3. Wi-Fi
        if any(term in inst_lower for term in ("wifi", "wi-fi", "wireless")):
            if any(term in inst_lower for term in ("on", "enable", "start")):
                args = {"enabled": True}
                res = set_wifi(**args)
                return "set_wifi", args, res
            elif any(term in inst_lower for term in ("off", "disable", "stop")):
                args = {"enabled": False}
                res = set_wifi(**args)
                return "set_wifi", args, res
            elif "scan" in inst_lower:
                args = {}
                res = scan_wifi()
                return "scan_wifi", args, res
            else:
                args = {}
                res = get_wifi_status()
                return "get_wifi_status", args, res

        # 4. Bluetooth
        if "bluetooth" in inst_lower:
            if any(term in inst_lower for term in ("on", "enable")):
                args = {"enabled": True}
                res = set_bluetooth(**args)
                return "set_bluetooth", args, res
            elif any(term in inst_lower for term in ("off", "disable")):
                args = {"enabled": False}
                res = set_bluetooth(**args)
                return "set_bluetooth", args, res
            else:
                args = {}
                res = get_bluetooth_status()
                return "get_bluetooth_status", args, res

        # 5. Battery
        if any(term in inst_lower for term in ("battery", "power")):
            args = {}
            res = get_battery_status()
            return "get_battery_status", args, res

        # 6. Lock screen
        if "lock" in inst_lower:
            args = {}
            res = lock_screen()
            return "lock_screen", args, res

        # 7. System info
        if any(term in inst_lower for term in ("system info", "hardware", "cpu", "memory", "specs")):
            args = {}
            res = get_system_info()
            return "get_system_info", args, res

        raise RuntimeError(f"Unable to resolve system instruction: '{instruction}'")

    def run(self, instruction: str) -> AgentFeedback:
        """
        Execute a system management instruction using complete() followed by
        deterministic function invocation.
        """
        log.info("[SystemAgent] Predicting tool for: '%s'", instruction)

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
                    log.info("[SystemAgent] Deterministically executing '%s' with args %s", fn_name, fn_args)
                    result = self._execute_tool(fn_name, fn_args)
                    executed_tools.append(fn_name)
                    tool_results.append(result)

                    if isinstance(result, dict) and not result.get("success", True):
                        success = False
                        error = result.get("message") or result.get("error")
            else:
                # 3. Deterministic fallback if complete() returned no function calls
                log.info("[SystemAgent] No function_calls from model, using deterministic fallback for: '%s'", instruction)
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
                observation = "System action executed successfully."

            return AgentFeedback(
                agent_name="system_agent",
                success=success,
                action_taken=", ".join(executed_tools) if executed_tools else instruction,
                output=tool_results[0] if len(tool_results) == 1 else tool_results,
                observation=observation or "System action completed.",
                error=error,
                data={"executed_tools": executed_tools},
            )

        except Exception as exc:
            log.exception("[SystemAgent] Execution error: %s", exc)
            return AgentFeedback(
                agent_name="system_agent",
                success=False,
                action_taken=instruction,
                output=None,
                observation=f"Failed to execute system action: {exc}",
                error=str(exc),
            )


_system_agent_instance: SystemAgent | None = None


def get_system_agent() -> SystemAgent:
    """Return a singleton SystemAgent instance."""
    global _system_agent_instance
    if _system_agent_instance is None:
        _system_agent_instance = SystemAgent()
    return _system_agent_instance
