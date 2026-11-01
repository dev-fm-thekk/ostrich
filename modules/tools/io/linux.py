"""
Linux IO Navigator
==================
Implementation of IONavigator for Linux combining:
- Mouse interaction using evdev / uinput with smooth gliding and safety release
- Keyboard interaction using ydotool
"""

from __future__ import annotations

import re
import subprocess
import time
from typing import Any

from modules.tools.io.base import IONavigator, KeyboardNavigator, MouseNavigator

try:
    from evdev import AbsInfo, UInput, ecodes as e
    _HAS_EVDEV = True
except ImportError:
    _HAS_EVDEV = False


class LinuxIONavigator(IONavigator):
    """Linux implementation of IONavigator combining mouse and keyboard capabilities."""

    def __init__(self, screen_size: tuple[int, int] | None = None) -> None:
        self._screen_size = screen_size
        self._ui: Any = None
        self._cur_pos: tuple[int, int] = (500, 500)

    # -----------------------------------------------------------------------
    # Mouse helper methods
    # -----------------------------------------------------------------------
    def _get_screen_size(self) -> tuple[int, int]:
        """Fetch screen dimensions via gdbus or xrandr with 1920x1080 default."""
        if self._screen_size:
            return self._screen_size

        # Try gdbus GNOME Shell Introspect
        try:
            cmd = [
                "gdbus", "call", "--session",
                "--dest", "org.gnome.Shell.Introspect",
                "--object-path", "/org/gnome/Shell/Introspect",
                "--method", "org.freedesktop.DBus.Properties.Get",
                "org.gnome.Shell.Introspect", "ScreenSize",
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
            if res.returncode == 0:
                nums = re.findall(r"\d+", res.stdout)
                if len(nums) >= 2:
                    self._screen_size = (int(nums[0]), int(nums[1]))
                    return self._screen_size
        except Exception:
            pass

        # Try xrandr
        try:
            res = subprocess.run(["xrandr"], capture_output=True, text=True, timeout=3)
            match = re.search(r"current\s+(\d+)\s*x\s*(\d+)", res.stdout)
            if match:
                self._screen_size = (int(match.group(1)), int(match.group(2)))
                return self._screen_size
        except Exception:
            pass

        self._screen_size = (1920, 1080)
        return self._screen_size

    def _get_current_pos(self) -> tuple[int, int]:
        """Fetch current cursor coordinates from X11 or internal cache."""
        try:
            import ctypes
            x11 = ctypes.cdll.LoadLibrary("libX11.so.6")
            d = x11.XOpenDisplay(None)
            if d:
                root = x11.XDefaultRootWindow(d)
                rr, cr = ctypes.c_ulong(), ctypes.c_ulong()
                rx, ry, wx, wy = ctypes.c_int(), ctypes.c_int(), ctypes.c_int(), ctypes.c_int()
                mask = ctypes.c_uint()
                x11.XQueryPointer(
                    d, root, ctypes.byref(rr), ctypes.byref(cr),
                    ctypes.byref(rx), ctypes.byref(ry),
                    ctypes.byref(wx), ctypes.byref(wy), ctypes.byref(mask)
                )
                x11.XCloseDisplay(d)
                self._cur_pos = (rx.value, ry.value)
                return self._cur_pos
        except Exception:
            pass
        return self._cur_pos

    def _get_device(self) -> Any:
        """Create or return reusable virtual UInput device."""
        if not _HAS_EVDEV:
            raise RuntimeError("evdev is not installed or available on this system.")

        if self._ui is None:
            w, h = self._get_screen_size()
            cap = {
                e.EV_KEY: [e.BTN_LEFT, e.BTN_RIGHT, e.BTN_MIDDLE],
                e.EV_ABS: [
                    (e.ABS_X, AbsInfo(0, 0, w - 1, 0, 0, 0)),
                    (e.ABS_Y, AbsInfo(0, 0, h - 1, 0, 0, 0)),
                ],
            }
            self._ui = UInput(cap, name="agent-mouse")
            time.sleep(0.1)
        return self._ui

    def _move_raw(self, ui: Any, x: float, y: float) -> None:
        ui.write(e.EV_ABS, e.ABS_X, int(x))
        ui.write(e.EV_ABS, e.ABS_Y, int(y))
        ui.syn()

    def _glide(self, ui: Any, x0: float, y0: float, x1: float, y1: float, steps: int = 25, delay: float = 0.008) -> None:
        """Interpolate movement between two coordinates smoothly."""
        for i in range(1, steps + 1):
            t = i / steps
            smooth_t = t * t * (3 - 2 * t)
            self._move_raw(ui, x0 + (x1 - x0) * smooth_t, y0 + (y1 - y0) * smooth_t)
            time.sleep(delay)

    def _btn_code(self, button: str) -> int:
        btn = button.lower()
        if btn == "right":
            return e.BTN_RIGHT
        if btn == "middle":
            return e.BTN_MIDDLE
        return e.BTN_LEFT

    # -----------------------------------------------------------------------
    # MouseNavigator implementation
    # -----------------------------------------------------------------------
    def move(self, x: int, y: int, smooth: bool = True) -> dict:
        """Move mouse cursor to coordinates (x, y) with smooth gliding."""
        try:
            ui = self._get_device()
            if smooth:
                x0, y0 = self._get_current_pos()
                dist = ((x - x0) ** 2 + (y - y0) ** 2) ** 0.5
                steps = max(10, min(35, int(dist / 30)))
                self._glide(ui, x0, y0, x, y, steps=steps, delay=0.008)
            else:
                self._move_raw(ui, x, y)
            self._cur_pos = (x, y)
            return {"success": True, "message": f"Moved mouse to ({x}, {y}).", "x": x, "y": y}
        except Exception as exc:
            return {"success": False, "message": f"Failed to move mouse: {exc}", "x": x, "y": y}

    def click(self, x: int | None = None, y: int | None = None, button: str = "left", smooth: bool = True) -> dict:
        """Perform a visible mouse click."""
        try:
            btn_key = self._btn_code(button)
            ui = self._get_device()
        except Exception as exc:
            return {"success": False, "message": f"Failed to initialize mouse device: {exc}"}

        pressed = False
        try:
            if x is not None and y is not None:
                self.move(x, y, smooth=smooth)
                time.sleep(0.06)

            ui.write(e.EV_KEY, btn_key, 1)
            ui.syn()
            pressed = True
            time.sleep(0.08)

            ui.write(e.EV_KEY, btn_key, 0)
            ui.syn()
            pressed = False

            pos_str = f" at ({x}, {y})" if x is not None and y is not None else ""
            return {"success": True, "message": f"Performed {button} click{pos_str}."}
        except Exception as exc:
            return {"success": False, "message": f"Failed to click: {exc}"}
        finally:
            if pressed:
                ui.write(e.EV_KEY, btn_key, 0)
                ui.syn()

    def double_click(self, x: int | None = None, y: int | None = None, button: str = "left", smooth: bool = True) -> dict:
        """Perform a visible double click."""
        try:
            btn_key = self._btn_code(button)
            ui = self._get_device()
        except Exception as exc:
            return {"success": False, "message": f"Failed to initialize mouse device: {exc}"}

        pressed = False
        try:
            if x is not None and y is not None:
                self.move(x, y, smooth=smooth)
                time.sleep(0.06)

            # Click 1
            ui.write(e.EV_KEY, btn_key, 1)
            ui.syn()
            pressed = True
            time.sleep(0.06)
            ui.write(e.EV_KEY, btn_key, 0)
            ui.syn()
            pressed = False

            time.sleep(0.08)

            # Click 2
            ui.write(e.EV_KEY, btn_key, 1)
            ui.syn()
            pressed = True
            time.sleep(0.06)
            ui.write(e.EV_KEY, btn_key, 0)
            ui.syn()
            pressed = False

            pos_str = f" at ({x}, {y})" if x is not None and y is not None else ""
            return {"success": True, "message": f"Performed {button} double click{pos_str}."}
        except Exception as exc:
            return {"success": False, "message": f"Failed to double click: {exc}"}
        finally:
            if pressed:
                ui.write(e.EV_KEY, btn_key, 0)
                ui.syn()

    def select(self, start_x: int, start_y: int, end_x: int, end_y: int, steps: int = 40) -> dict:
        """Drag-select a rectangle on screen using glide movements."""
        try:
            ui = self._get_device()
        except Exception as exc:
            return {"success": False, "message": f"Failed to initialize mouse device: {exc}"}

        pressed = False
        try:
            self.move(start_x, start_y, smooth=True)
            time.sleep(0.1)

            ui.write(e.EV_KEY, e.BTN_LEFT, 1)
            ui.syn()
            pressed = True
            time.sleep(0.1)

            self._glide(ui, start_x, start_y, end_x, end_y, steps=steps, delay=0.01)
            time.sleep(0.15)

            self._cur_pos = (end_x, end_y)
            return {
                "success": True,
                "message": f"Selected area from ({start_x}, {start_y}) to ({end_x}, {end_y}).",
                "start": {"x": start_x, "y": start_y},
                "end": {"x": end_x, "y": end_y},
            }
        except Exception as exc:
            return {"success": False, "message": f"Drag-select failed: {exc}"}
        finally:
            if pressed:
                ui.write(e.EV_KEY, e.BTN_LEFT, 0)
                ui.syn()

    # -----------------------------------------------------------------------
    # KeyboardNavigator implementation
    # -----------------------------------------------------------------------
    def _execute_keyboard(self, *args: str) -> dict:
        """Execute a keyboard action via ydotool."""
        try:
            result = subprocess.run(
                ["ydotool", *args],
                capture_output=True,
                text=True,
                check=True,
                timeout=10,
            )
            return {
                "success": True,
                "message": result.stdout.strip() or "Keyboard action executed",
            }
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "message": "Keyboard action timed out",
            }
        except subprocess.CalledProcessError as e_err:
            return {
                "success": False,
                "message": e_err.stderr.strip() or str(e_err),
            }
        except FileNotFoundError:
            return {
                "success": False,
                "message": "ydotool is not installed or not in PATH",
            }
        except Exception as exc:
            return {
                "success": False,
                "message": str(exc),
            }

    def type_text(self, text: str) -> dict:
        """Type text into the currently focused application."""
        result = self._execute_keyboard("type", "--", text)
        if result["success"]:
            result["message"] = f"Typed text: {text}"
        return result

    def press_key(self, key: str) -> dict:
        """Press a single key."""
        result = self._execute_keyboard("key", key)
        if result["success"]:
            result["message"] = f"Pressed key: {key}"
        return result

    def hotkey(self, *keys: str) -> dict:
        """Press a keyboard combination."""
        if not keys:
            return {
                "success": False,
                "message": "No keys provided",
            }
        key_combination = "+".join(keys)
        result = self._execute_keyboard("key", key_combination)
        if result["success"]:
            result["message"] = f"Pressed hotkey: {key_combination}"
        return result


# Aliases for backwards compatibility and specific role typing
LinuxMouseNavigator = LinuxIONavigator
LinuxKeyboardNavigator = LinuxIONavigator
