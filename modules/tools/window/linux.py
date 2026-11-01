"""
Linux Desktop Navigator
=======================
Implementation of DesktopNavigator for Linux using gdbus (GNOME Shell / Extensions / Introspect)
with support for window ID, process ID, and window title matching, plus wmctrl fallback.
"""

from __future__ import annotations

import ast
import json
import re
import shutil
import subprocess

from modules.tools.window.base import DesktopNavigator

# Common Linux app alias mapping
_LINUX_APP_ALIASES: dict[str, str] = {
    "chrome": "google-chrome",
    "google chrome": "google-chrome",
    "google-chrome": "google-chrome",
    "chromium": "chromium",
    "chromium-browser": "chromium-browser",
    "firefox": "firefox",
    "calc": "gnome-calculator",
    "calculator": "gnome-calculator",
    "gnome-calc": "gnome-calculator",
    "terminal": "gnome-terminal",
    "gedit": "gedit",
    "text editor": "gedit",
    "editor": "gedit",
    "files": "nautilus",
    "nautilus": "nautilus",
    "code": "code",
    "vscode": "code",
    "vs code": "code",
}


class LinuxDesktopNavigator(DesktopNavigator):
    """Linux implementation using gdbus to communicate with GNOME Shell and window manager.

    Supports querying and manipulating windows by:
    - Window ID (winid)
    - Process ID (PID)
    - Application name / window title / wm_class
    """

    def __init__(self) -> None:
        self.gnome_windows_dest = "org.gnome.Shell"
        self.gnome_windows_path = "/org/gnome/Shell/Extensions/Windows"
        self.gnome_windows_iface = "org.gnome.Shell.Extensions.Windows"

    def _call_gdbus(
        self,
        method: str,
        args: list[str] | None = None,
        dest: str | None = None,
        path: str | None = None,
        iface: str | None = None,
        timeout: int = 10,
    ) -> tuple[bool, str, str]:
        """Call a method via gdbus CLI."""
        target_dest = dest or self.gnome_windows_dest
        target_path = path or self.gnome_windows_path
        target_iface = iface or self.gnome_windows_iface

        cmd = [
            "gdbus", "call", "--session",
            "--dest", target_dest,
            "--object-path", target_path,
            "--method", f"{target_iface}.{method}",
        ]
        if args:
            cmd.extend(str(a) for a in args)

        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            return res.returncode == 0, res.stdout.strip(), res.stderr.strip()
        except FileNotFoundError:
            return False, "", "gdbus executable not found."
        except subprocess.TimeoutExpired:
            return False, "", "gdbus call timed out."
        except OSError as e:
            return False, "", str(e)

    def _get_screen_size(self) -> tuple[int, int]:
        """Fetch screen dimensions via gdbus org.gnome.Shell.Introspect ScreenSize."""
        cmd = [
            "gdbus", "call", "--session",
            "--dest", "org.gnome.Shell.Introspect",
            "--object-path", "/org/gnome/Shell/Introspect",
            "--method", "org.freedesktop.DBus.Properties.Get",
            "org.gnome.Shell.Introspect", "ScreenSize",
        ]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            if res.returncode == 0:
                nums = re.findall(r"\d+", res.stdout)
                if len(nums) >= 2:
                    return int(nums[0]), int(nums[1])
        except Exception:
            pass

        # Fallback to xrandr or default 1920x1080
        try:
            res = subprocess.run(["xrandr"], capture_output=True, text=True, timeout=5)
            match = re.search(r"current\s+(\d+)\s*x\s*(\d+)", res.stdout)
            if match:
                return int(match.group(1)), int(match.group(2))
        except Exception:
            pass

        return 1920, 1080

    def _list_windows_gdbus(self) -> list[dict]:
        """Query open windows from the GNOME Shell Windows extension via gdbus."""
        ok, stdout, _ = self._call_gdbus("List")
        if not ok or not stdout:
            return []

        try:
            val = ast.literal_eval(stdout)
            raw_json = val[0] if isinstance(val, (tuple, list)) else val
            windows = json.loads(raw_json)
            normalized = []
            for w in windows:
                # Filter out background desktop icons if present
                is_desktop = w.get("frame_type") == 7 or w.get("window_type") == 1
                normalized.append({
                    "id": w.get("id"),
                    "pid": w.get("pid"),
                    "name": w.get("wm_class_instance") or w.get("wm_class") or "",
                    "wm_class": w.get("wm_class", ""),
                    "wm_class_instance": w.get("wm_class_instance", ""),
                    "title": w.get("title", ""),
                    "focus": w.get("focus", False),
                    "is_desktop": is_desktop,
                })
            return normalized
        except Exception:
            return []

    def _list_windows_wmctrl(self) -> list[dict]:
        """Fallback to wmctrl -lp when gdbus is unavailable or on non-GNOME desktops."""
        try:
            res = subprocess.run(["wmctrl", "-lp"], capture_output=True, text=True, timeout=5)
            if res.returncode != 0:
                return []
            windows = []
            for line in res.stdout.strip().splitlines():
                parts = line.split(None, 4)
                if len(parts) >= 5:
                    win_id_hex, ws, pid_str, host, title = parts
                    pid = int(pid_str) if pid_str.isdigit() else None
                    try:
                        win_id = int(win_id_hex, 16)
                    except ValueError:
                        win_id = win_id_hex
                    windows.append({
                        "id": win_id,
                        "pid": pid,
                        "name": title,
                        "wm_class": "",
                        "wm_class_instance": "",
                        "title": title,
                        "focus": False,
                        "is_desktop": ws == "-1",
                    })
            return windows
        except Exception:
            return []

    def list_windows(self) -> dict:
        """Return a list of all currently visible desktop windows on Linux."""
        windows = self._list_windows_gdbus()
        if not windows:
            windows = self._list_windows_wmctrl()

        return {
            "success": True,
            "windows": windows,
            "message": f"Found {len(windows)} open window(s).",
        }

    def _find_window(self, target: str | int) -> dict | None:
        """Find a window matching window ID, process ID, title, or application name."""
        win_list = self.list_windows().get("windows", [])
        if not win_list:
            return None

        target_str = str(target).strip()
        is_num = target_str.isdigit()

        # 1. Match Window ID directly
        if is_num:
            target_int = int(target_str)
            for w in win_list:
                if w.get("id") == target_int:
                    return w

        # 2. Match Process ID (PID) directly
        if is_num:
            target_int = int(target_str)
            for w in win_list:
                if w.get("pid") == target_int:
                    return w

        # 3. Match by canonical alias
        alias_name = _LINUX_APP_ALIASES.get(target_str.lower(), target_str.lower())

        # Exact / Substring match on wm_class, wm_class_instance, or title
        target_lower = target_str.lower()
        for w in win_list:
            wm_class = (w.get("wm_class") or "").lower()
            wm_instance = (w.get("wm_class_instance") or "").lower()
            title = (w.get("title") or "").lower()
            name = (w.get("name") or "").lower()

            if (
                target_lower in title
                or target_lower in wm_class
                or target_lower in wm_instance
                or target_lower in name
                or alias_name in wm_class
                or alias_name in wm_instance
            ):
                return w

        return None

    def launch_app(self, app_name: str, args: list[str] | None = None) -> dict:
        """Launch an application on Linux using non-blocking subprocess with alias resolution."""
        raw_name = app_name.strip()
        canonical_cmd = _LINUX_APP_ALIASES.get(raw_name.lower(), raw_name)

        # Check if binary is in PATH, otherwise try gtk-launch
        cmd_path = shutil.which(canonical_cmd) or shutil.which(raw_name)

        launch_args = args or []
        try:
            if cmd_path:
                proc = subprocess.Popen(
                    [cmd_path] + launch_args,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                return {
                    "success": True,
                    "message": f"Launched '{canonical_cmd}' (PID {proc.pid}).",
                    "pid": proc.pid,
                }

            # Direct fallback execution attempt
            proc = subprocess.Popen(
                [raw_name] + launch_args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            return {
                "success": True,
                "message": f"Launched '{raw_name}' (PID {proc.pid}).",
                "pid": proc.pid,
            }

        except FileNotFoundError:
            return {
                "success": False,
                "message": f"Application or command '{app_name}' not found.",
                "pid": None,
            }
        except Exception as exc:
            return {
                "success": False,
                "message": f"Failed to launch '{app_name}': {exc}",
                "pid": None,
            }

    def switch_window(self, target: str | int) -> dict:
        """Bring a desktop window to the foreground by window ID, PID, or title."""
        win = self._find_window(target)
        if not win:
            return {
                "success": False,
                "message": f"No open window found matching '{target}'.",
                "pid": None,
                "id": None,
            }

        win_id = win.get("id")
        win_pid = win.get("pid")
        title = win.get("title", "")

        # Try gdbus Activate
        if win_id is not None:
            ok, _, stderr = self._call_gdbus("Activate", [str(win_id)])
            if ok:
                return {
                    "success": True,
                    "message": f"Activated window '{title}' (PID {win_pid}, ID {win_id}).",
                    "pid": win_pid,
                    "id": win_id,
                }

        # Fallback to wmctrl
        if win_id is not None:
            try:
                hex_id = hex(win_id) if isinstance(win_id, int) else str(win_id)
                res = subprocess.run(["wmctrl", "-ia", hex_id], capture_output=True, text=True)
                if res.returncode == 0:
                    return {
                        "success": True,
                        "message": f"Activated window '{title}' via wmctrl (PID {win_pid}, ID {win_id}).",
                        "pid": win_pid,
                        "id": win_id,
                    }
            except Exception:
                pass

        return {
            "success": False,
            "message": f"Failed to activate window '{title}'.",
            "pid": win_pid,
            "id": win_id,
        }

    def maximize_app(self, app_name: str | int) -> dict:
        """Maximize an application window using gdbus by window ID, PID, or title."""
        win = self._find_window(app_name)
        if not win:
            return {
                "success": False,
                "message": f"No open window found matching '{app_name}'.",
                "pid": None,
                "id": None,
            }

        win_id = win.get("id")
        win_pid = win.get("pid")
        title = win.get("title", "")

        # Try gdbus Maximize
        if win_id is not None:
            ok, _, stderr = self._call_gdbus("Maximize", [str(win_id)])
            if ok:
                return {
                    "success": True,
                    "message": f"Maximized window '{title}' (PID {win_pid}, ID {win_id}).",
                    "pid": win_pid,
                    "id": win_id,
                }

        # Fallback to wmctrl
        if win_id is not None:
            try:
                hex_id = hex(win_id) if isinstance(win_id, int) else str(win_id)
                res = subprocess.run(
                    ["wmctrl", "-ir", hex_id, "-b", "add,maximized_horz,maximized_vert"],
                    capture_output=True,
                    text=True,
                )
                if res.returncode == 0:
                    return {
                        "success": True,
                        "message": f"Maximized window '{title}' via wmctrl (PID {win_pid}, ID {win_id}).",
                        "pid": win_pid,
                        "id": win_id,
                    }
            except Exception:
                pass

        return {
            "success": False,
            "message": f"Failed to maximize window '{title}'.",
            "pid": win_pid,
            "id": win_id,
        }

    def minimize_app(self, app_name: str | int) -> dict:
        """Minimize an application window using gdbus by window ID, PID, or title."""
        win = self._find_window(app_name)
        if not win:
            return {
                "success": False,
                "message": f"No open window found matching '{app_name}'.",
                "pid": None,
                "id": None,
            }

        win_id = win.get("id")
        win_pid = win.get("pid")
        title = win.get("title", "")

        # Try gdbus Minimize
        if win_id is not None:
            ok, _, stderr = self._call_gdbus("Minimize", [str(win_id)])
            if ok:
                return {
                    "success": True,
                    "message": f"Minimized window '{title}' (PID {win_pid}, ID {win_id}).",
                    "pid": win_pid,
                    "id": win_id,
                }

        # Fallback to xdotool / wmctrl
        if win_id is not None and shutil.which("xdotool"):
            try:
                res = subprocess.run(
                    ["xdotool", "windowminimize", str(win_id)],
                    capture_output=True,
                    text=True,
                )
                if res.returncode == 0:
                    return {
                        "success": True,
                        "message": f"Minimized window '{title}' via xdotool (PID {win_pid}, ID {win_id}).",
                        "pid": win_pid,
                        "id": win_id,
                    }
            except Exception:
                pass

        return {
            "success": False,
            "message": f"Failed to minimize window '{title}'.",
            "pid": win_pid,
            "id": win_id,
        }

    def split_screen(
        self,
        left_target: str | int | None = None,
        right_target: str | int | None = None,
    ) -> dict:
        """Split and tile two windows side-by-side using gdbus MoveResize."""
        win_list = [w for w in self.list_windows().get("windows", []) if not w.get("is_desktop")]
        if not win_list:
            return {"success": False, "message": "No open application windows found to split."}

        left_win = None
        right_win = None

        if left_target is not None:
            left_win = self._find_window(left_target)
        if right_target is not None:
            right_win = self._find_window(right_target)

        # Default to first two windows if not explicitly given
        if not left_win and win_list:
            left_win = win_list[0]
        if not right_win and len(win_list) > 1:
            remaining = [w for w in win_list if w.get("id") != (left_win.get("id") if left_win else None)]
            if remaining:
                right_win = remaining[0]

        screen_w, screen_h = self._get_screen_size()
        half_w = screen_w // 2

        results = []

        # Position Left Window: (x=0, y=0, width=half_w, height=screen_h)
        if left_win and left_win.get("id") is not None:
            lid = left_win["id"]
            self._call_gdbus("Unmaximize", [str(lid)])
            ok_move, _, _ = self._call_gdbus("MoveResize", [str(lid), "0", "0", str(half_w), str(screen_h)])
            self._call_gdbus("Activate", [str(lid)])
            results.append(f"Left: '{left_win.get('title')}' (ID {lid}, PID {left_win.get('pid')})")

        # Position Right Window: (x=half_w, y=0, width=half_w, height=screen_h)
        if right_win and right_win.get("id") is not None and right_win != left_win:
            rid = right_win["id"]
            self._call_gdbus("Unmaximize", [str(rid)])
            ok_move, _, _ = self._call_gdbus("MoveResize", [str(rid), str(half_w), "0", str(half_w), str(screen_h)])
            self._call_gdbus("Activate", [str(rid)])
            results.append(f"Right: '{right_win.get('title')}' (ID {rid}, PID {right_win.get('pid')})")

        if not results:
            return {"success": False, "message": "Could not arrange windows for split screen."}

        return {
            "success": True,
            "message": f"Split screen positioned: {', '.join(results)}.",
            "left": left_win,
            "right": right_win,
        }
