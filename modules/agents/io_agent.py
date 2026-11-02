"""
IO Delegate Agent
=================
Executes mouse movements, clicks, drag-selection, text typing, and keyboard
shortcuts using Needle complete() for model prediction, followed by deterministic
execution of the resolved tool function.
"""

from __future__ import annotations

import inspect
import logging
import re
from typing import Any, Callable, Optional

from config.models import get_needle_model
from modules.agents.state import AgentFeedback
from modules.tools.io import (
    IONavigator,
    get_io_navigator,
    keyboard_hotkey,
    keyboard_press_key,
    keyboard_type_text,
    mouse_click,
    mouse_double_click,
    mouse_move,
    mouse_select,
)

log = logging.getLogger(__name__)

IO_TOOLS = [
    mouse_move,
    mouse_click,
    mouse_double_click,
    mouse_select,
    keyboard_type_text,
    keyboard_press_key,
    keyboard_hotkey,
]


class IOAgent:
    """Delegate agent for low-level mouse and keyboard input execution."""

    def __init__(self, custom_tools: list[Any] | None = None) -> None:
        self.tools = custom_tools or IO_TOOLS
        self.tool_map: dict[str, Callable] = {
            t.__name__: t for t in self.tools if hasattr(t, "__name__")
        }
        self._executor: Any = None
        self._navigator: IONavigator | None = None

    @property
    def navigator(self) -> IONavigator:
        if self._navigator is None:
            self._navigator = get_io_navigator()
        return self._navigator

    @property
    def executor(self) -> Any:
        if self._executor is None:
            self._executor = get_needle_model(self.tools)
        return self._executor

    def _execute_tool(self, fn_name: str, fn_args: dict[str, Any], raw_instruction: str = "") -> tuple[str, Any]:
        """
        Deterministically invoke a tool by name with arguments and normalization.
        Returns (actual_fn_name, result) so callers always know what was really called.
        """
        inst_lower = raw_instruction.strip().lower()

        # ── Instruction-level overrides (catch model mispredictions) ──────────

        # 1. Clearly a hotkey instruction but model emitted keyboard_type_text
        _HOTKEY_SIGNALS = ("hotkey", "shortcut", "ctrl+", "alt+", "shift+", "super+", "meta+")
        if fn_name == "keyboard_type_text" and any(sig in inst_lower for sig in _HOTKEY_SIGNALS):
            combo_raw = re.sub(r"^(press\s+hotkey|hotkey|keyboard\s+shortcut|shortcut|press)\s+", "", inst_lower).strip()
            parts = [p.strip() for p in combo_raw.split("+") if p.strip()]
            log.info("[IOAgent] Override: keyboard_type_text → keyboard_hotkey(%s)", parts)
            return "keyboard_hotkey", self.navigator.hotkey(*parts)

        # 2. Clearly "press enter/return" but model emitted keyboard_type_text
        if fn_name == "keyboard_type_text" and any(sig in inst_lower for sig in ("press enter", "press return", "hit enter")):
            log.info("[IOAgent] Override: keyboard_type_text → keyboard_press_key(Return)")
            return "keyboard_press_key", self.navigator.press_key("Return")

        # ── Proper argument normalization for keyboard_hotkey ─────────────────

        if fn_name == "keyboard_hotkey":
            if "keys" in fn_args:
                k = fn_args["keys"]
                if isinstance(k, list):
                    return "keyboard_hotkey", self.navigator.hotkey(*k)
                elif isinstance(k, str):
                    return "keyboard_hotkey", self.navigator.hotkey(*[part.strip() for part in k.split("+")])
            if "key" in fn_args:
                k = str(fn_args["key"])
                return "keyboard_hotkey", self.navigator.hotkey(*[part.strip() for part in k.split("+")])

        # Special normalization for keyboard_press_key
        if fn_name == "keyboard_press_key":
            key_val = fn_args.get("key", "Return")
            if str(key_val).lower() in ("enter", "return"):
                key_val = "Return"
            return "keyboard_press_key", self.navigator.press_key(str(key_val))

        fn = self.tool_map.get(fn_name)
        if not fn:
            raise ValueError(f"Tool '{fn_name}' is not registered in IOAgent tool map.")

        sig = inspect.signature(fn)
        bound_args = {}
        for param in sig.parameters.values():
            if param.name in fn_args:
                bound_args[param.name] = fn_args[param.name]

        return fn_name, fn(**bound_args)

    def _fallback_deterministic_call(self, instruction: str) -> tuple[str, dict[str, Any], Any]:
        """
        Deterministic intent resolution when the model produces no function calls.
        Guarantees the intended mouse/keyboard action is executed.
        """
        inst_lower = instruction.strip().lower()

        # 1. Press Enter / Return
        if any(term in inst_lower for term in ("press enter", "press return", "hit enter", "send enter")):
            res = self.navigator.press_key("Return")
            return "keyboard_press_key", {"key": "Return"}, res

        # 2. Hotkey combinations (e.g. ctrl+shift+c, alt+f4)
        if any(term in inst_lower for term in ("hotkey", "shortcut")) or "+" in inst_lower:
            cleaned = re.sub(r"^(press\s+hotkey|hotkey|keyboard\s+shortcut|shortcut|press)\s+", "", inst_lower).strip()
            keys = [part.strip() for part in cleaned.split("+") if part.strip()]
            res = self.navigator.hotkey(*keys)
            return "keyboard_hotkey", {"keys": keys}, res

        # 3. Press single key
        if inst_lower.startswith(("press key ", "press ")):
            key = re.sub(r"^(press\s+key\s+|press\s+)", "", inst_lower).strip()
            if key in ("enter", "return"):
                key = "Return"
            res = self.navigator.press_key(key)
            return "keyboard_press_key", {"key": key}, res

        # 4. Type text
        if any(inst_lower.startswith(prefix) for prefix in ("type text ", "type ", "write text ", "write ")):
            # Match the raw string after the prefix to preserve casing
            m = re.match(r"^(type\s+text\s+|type\s+|write\s+text\s+|write\s+)(.*)$", instruction.strip(), re.IGNORECASE)
            text = m.group(2) if m else instruction.strip()
            # If wrapped in quotes, unwrap
            if (text.startswith("'") and text.endswith("'")) or (text.startswith('"') and text.endswith('"')):
                text = text[1:-1]
            res = self.navigator.type_text(text)
            return "keyboard_type_text", {"text": text}, res

        # 5. Mouse click
        if "click" in inst_lower:
            nums = [int(n) for n in re.findall(r"\d+", inst_lower)]
            x = nums[0] if len(nums) >= 2 else None
            y = nums[1] if len(nums) >= 2 else None
            btn = "right" if "right" in inst_lower else ("middle" if "middle" in inst_lower else "left")
            res = self.navigator.click(x=x, y=y, button=btn)
            return "mouse_click", {"x": x, "y": y, "button": btn}, res

        # 6. Mouse move
        if "move" in inst_lower:
            nums = [int(n) for n in re.findall(r"\d+", inst_lower)]
            if len(nums) >= 2:
                res = self.navigator.move(nums[0], nums[1])
                return "mouse_move", {"x": nums[0], "y": nums[1]}, res

        raise RuntimeError(f"Unable to resolve IO instruction: '{instruction}'")

    def run(
        self,
        instruction: str,
        parameters: Optional[dict[str, Any]] = None,
    ) -> AgentFeedback:
        """
        Execute an IO instruction using complete() followed by deterministic
        function invocation.
        """
        log.info("[IOAgent] Predicting tool for: '%s' (params: %s)", instruction, parameters)
        params = parameters or {}

        executed_tools: list[str] = []
        tool_results: list[Any] = []
        success = True
        error: str | None = None
        observation = ""

        try:
            # Direct parameter dispatch if explicit structured parameters provided
            action = params.get("action")
            if action == "click" and "x" in params and "y" in params:
                res = self.navigator.click(
                    x=int(params["x"]),
                    y=int(params["y"]),
                    button=params.get("button", "left"),
                )
                executed_tools.append("mouse_click")
                tool_results.append(res)
            elif action == "type" and "text" in params:
                res = self.navigator.type_text(str(params["text"]))
                executed_tools.append("keyboard_type_text")
                tool_results.append(res)
            elif action == "press" and "key" in params:
                key_name = str(params["key"])
                if key_name.lower() in ("enter", "return"):
                    key_name = "Return"
                res = self.navigator.press_key(key_name)
                executed_tools.append("keyboard_press_key")
                tool_results.append(res)
            elif action == "hotkey" and "keys" in params:
                keys = params["keys"]
                if isinstance(keys, str):
                    keys = [k.strip() for k in keys.split("+")]
                res = self.navigator.hotkey(*keys)
                executed_tools.append("keyboard_hotkey")
                tool_results.append(res)
            elif action == "move" and "x" in params and "y" in params:
                res = self.navigator.move(int(params["x"]), int(params["y"]))
                executed_tools.append("mouse_move")
                tool_results.append(res)
            else:
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
                        log.info("[IOAgent] Deterministically executing '%s' with args %s", fn_name, fn_args)
                        actual_name, result = self._execute_tool(fn_name, fn_args, raw_instruction=instruction)
                        executed_tools.append(actual_name)
                        tool_results.append(result)

                        if isinstance(result, dict) and not result.get("success", True):
                            success = False
                            error = result.get("message") or result.get("error")
                else:
                    # 3. Deterministic fallback if complete() returned no function calls
                    log.info("[IOAgent] No function_calls from model, using deterministic fallback for: '%s'", instruction)
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
                observation = "IO action executed successfully."

            return AgentFeedback(
                agent_name="io_agent",
                success=success,
                action_taken=", ".join(executed_tools) if executed_tools else instruction,
                output=tool_results[0] if len(tool_results) == 1 else tool_results,
                observation=observation or "IO action completed.",
                error=error,
                data={"executed_tools": executed_tools},
            )

        except Exception as exc:
            log.exception("[IOAgent] Execution error: %s", exc)
            return AgentFeedback(
                agent_name="io_agent",
                success=False,
                action_taken=instruction,
                output=None,
                observation=f"Failed to execute IO action: {exc}",
                error=str(exc),
            )


_io_agent_instance: IOAgent | None = None


def get_io_agent() -> IOAgent:
    """Return a singleton IOAgent instance."""
    global _io_agent_instance
    if _io_agent_instance is None:
        _io_agent_instance = IOAgent()
    return _io_agent_instance
