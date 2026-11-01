"""
Windows Desktop Navigator
=========================
Implementation of DesktopNavigator for Windows using PowerShell and Win32 APIs.
"""

from __future__ import annotations

import json
import subprocess

try:
    from modules.tools.window.base import DesktopNavigator
except ImportError:
    from modules.tools.window.base import DesktopNavigator

# Import app naming context resolution
try:
    from ostrich.context.app_aliases import resolve_app_name
except ImportError:
    try:
        from ostrich.context.app_aliases import resolve_app_name
    except ImportError:
        def resolve_app_name(raw: str) -> str:
            return raw


# Inline C# types loaded into PowerShell for Win32 API calls
_WIN32_TYPE = """
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public class Win32 {
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
    [DllImport("user32.dll")] public static extern bool MoveWindow(IntPtr hWnd, int X, int Y, int nWidth, int nHeight, bool bRepaint);
    [DllImport("user32.dll")] public static extern int GetSystemMetrics(int nIndex);
}
'@
"""

_SW_MINIMIZE = 6
_SW_MAXIMIZE = 3
_SW_RESTORE = 9


class WindowsDesktopNavigator(DesktopNavigator):
    """Windows implementation using PowerShell and Win32 user32 APIs."""

    def _run_ps(self, command: str, timeout: int = 10) -> tuple[bool, str, str]:
        """Execute a command in a non-interactive PowerShell session."""
        try:
            r = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return r.returncode == 0, r.stdout.strip(), r.stderr.strip()
        except FileNotFoundError:
            return False, "", "PowerShell not found."
        except subprocess.TimeoutExpired:
            return False, "", "PowerShell command timed out."
        except OSError as exc:
            return False, "", str(exc)

    def _start_process(self, app_name: str, args: list[str] | None = None) -> dict:
        """Run Start-Process directly via PowerShell."""
        arg_fragment = ""
        if args:
            quoted = ", ".join(f'"{a}"' for a in args)
            arg_fragment = f" -ArgumentList {quoted}"

        ps_command = (
            f"$p = Start-Process {app_name}{arg_fragment} -PassThru; "
            f"Write-Output $p.Id"
        )

        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_command],
                capture_output=True,
                text=True,
                timeout=15,
            )

            if result.returncode != 0:
                error_msg = result.stderr.strip() or f"Exit code {result.returncode}"
                return {
                    "success": False,
                    "message": f"Start-Process failed for '{app_name}': {error_msg}",
                    "pid": None,
                }

            pid_str = result.stdout.strip()
            pid = int(pid_str) if pid_str.isdigit() else None
            return {
                "success": True,
                "message": f"Launched '{app_name}' via Start-Process"
                           + (f" (PID {pid})." if pid else "."),
                "pid": pid,
            }

        except FileNotFoundError:
            return {
                "success": False,
                "message": "PowerShell not found. Cannot use Start-Process.",
                "pid": None,
            }
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "message": f"Start-Process timed out while launching '{app_name}'.",
                "pid": None,
            }
        except OSError as exc:
            return {"success": False, "message": str(exc), "pid": None}

    def _show_window(self, target: str | int, nCmdShow: int, action_label: str) -> dict:
        """Find a window by title or PID and call ShowWindow(handle, nCmdShow)."""
        target_str = str(target).strip()

        # Build PowerShell filter supporting PID and title
        if target_str.isdigit():
            filter_clause = (
                f"($_.Id -eq {target_str}) -or "
                f"($_.MainWindowTitle -like '*{target_str}*')"
            )
        else:
            filter_clause = f"$_.MainWindowTitle -like '*{target_str}*'"

        ps_command = (
            f"{_WIN32_TYPE}"
            f"$w = Get-Process | "
            f"Where-Object {{ {filter_clause} }} | "
            f"Select-Object -First 1; "
            f"if (-not $w) {{ Write-Error 'NO_MATCH'; exit 1 }}; "
            f"[Win32]::ShowWindow($w.MainWindowHandle, {nCmdShow}) | Out-Null; "
            f"Write-Output \"$($w.Id)|$($w.MainWindowTitle)\""
        )

        ok, stdout, stderr = self._run_ps(ps_command, timeout=10)

        if not ok:
            if "NO_MATCH" in stderr:
                return {
                    "success": False,
                    "message": f"No open window found matching '{target}'.",
                    "pid": None,
                }
            return {
                "success": False,
                "message": stderr or f"Failed to {action_label} window '{target}'.",
                "pid": None,
            }

        pid, matched_title = (stdout.split("|", 1) + [""])[:2]
        return {
            "success": True,
            "message": f"{action_label.capitalize()}d window '{matched_title}' (PID {pid}).",
            "pid": int(pid) if pid.isdigit() else None,
        }

    def launch_app(self, app_name: str, args: list[str] | None = None) -> dict:
        """Open a desktop application by name on Windows."""
        canonical_name = resolve_app_name(app_name)
        return self._start_process(canonical_name, args or [])

    def list_windows(self) -> dict:
        """Return a list of all currently visible desktop windows on Windows."""
        ps_command = (
            "Get-Process | "
            "Where-Object { $_.MainWindowTitle -ne '' } | "
            "Select-Object Id, ProcessName, MainWindowTitle | "
            "ConvertTo-Json -Compress"
        )

        ok, stdout, stderr = self._run_ps(ps_command)

        if not ok:
            return {"success": False, "windows": [], "message": stderr or "Failed to list windows."}

        if not stdout:
            return {"success": True, "windows": [], "message": "No open windows found."}

        try:
            raw = json.loads(stdout)
            if isinstance(raw, dict):
                raw = [raw]
            windows = [
                {
                    "pid": entry["Id"],
                    "name": entry["ProcessName"],
                    "title": entry["MainWindowTitle"],
                }
                for entry in raw
            ]
            return {
                "success": True,
                "windows": windows,
                "message": f"Found {len(windows)} open window(s).",
            }
        except Exception as e:
            return {"success": False, "windows": [], "message": f"Failed to parse windows output: {e}"}

    def switch_window(self, target: str | int) -> dict:
        """Bring a desktop window to foreground by matching title or PID."""
        target_str = str(target).strip()
        if target_str.isdigit():
            filter_clause = (
                f"($_.Id -eq {target_str}) -or "
                f"($_.MainWindowTitle -like '*{target_str}*')"
            )
        else:
            filter_clause = f"$_.MainWindowTitle -like '*{target_str}*'"

        ps_command = (
            f"{_WIN32_TYPE}"
            f"$w = Get-Process | "
            f"Where-Object {{ {filter_clause} }} | "
            f"Select-Object -First 1; "
            f"if (-not $w) {{ Write-Error 'NO_MATCH'; exit 1 }}; "
            f"[Win32]::ShowWindow($w.MainWindowHandle, {_SW_RESTORE}) | Out-Null; "
            f"[Win32]::SetForegroundWindow($w.MainWindowHandle) | Out-Null; "
            f"Write-Output \"$($w.Id)|$($w.MainWindowTitle)\""
        )

        ok, stdout, stderr = self._run_ps(ps_command, timeout=10)

        if not ok:
            if "NO_MATCH" in stderr:
                return {
                    "success": False,
                    "message": f"No open window found matching '{target}'.",
                    "pid": None,
                }
            return {
                "success": False,
                "message": stderr or f"Failed to switch to window '{target}'.",
                "pid": None,
            }

        pid, matched_title = (stdout.split("|", 1) + [""])[:2]
        return {
            "success": True,
            "message": f"Activated window '{matched_title}' (PID {pid}).",
            "pid": int(pid) if pid.isdigit() else None,
        }

    def maximize_app(self, app_name: str | int) -> dict:
        """Maximize a desktop window by matching title or PID."""
        return self._show_window(app_name, _SW_MAXIMIZE, "maximize")

    def minimize_app(self, app_name: str | int) -> dict:
        """Minimize a desktop window by matching title or PID."""
        return self._show_window(app_name, _SW_MINIMIZE, "minimize")

    def split_screen(
        self,
        left_target: str | int | None = None,
        right_target: str | int | None = None,
    ) -> dict:
        """Position two windows side-by-side using Win32 MoveWindow."""
        # Query open windows
        wins_info = self.list_windows()
        windows = wins_info.get("windows", [])
        if not windows:
            return {"success": False, "message": "No open windows found to split."}

        # Resolve left and right target windows
        left_win = None
        right_win = None

        if left_target is not None:
            l_str = str(left_target).lower()
            left_win = next(
                (w for w in windows if l_str in w["title"].lower() or str(w["pid"]) == l_str),
                None,
            )
        if right_target is not None:
            r_str = str(right_target).lower()
            right_win = next(
                (w for w in windows if r_str in w["title"].lower() or str(w["pid"]) == r_str),
                None,
            )

        # Fallback to first two windows if targets are not specified
        if not left_win and windows:
            left_win = windows[0]
        if not right_win and len(windows) > 1:
            candidates = [w for w in windows if w != left_win]
            if candidates:
                right_win = candidates[0]

        ps_script_parts = [_WIN32_TYPE]
        ps_script_parts.append(
            "$w = [Win32]::GetSystemMetrics(0); "
            "$h = [Win32]::GetSystemMetrics(1); "
            "$half = [math]::Floor($w / 2);"
        )

        actions = []
        if left_win:
            ps_script_parts.append(
                f"$pLeft = Get-Process -Id {left_win['pid']} -ErrorAction SilentlyContinue; "
                f"if ($pLeft) {{ "
                f"[Win32]::ShowWindow($pLeft.MainWindowHandle, {_SW_RESTORE}) | Out-Null; "
                f"[Win32]::MoveWindow($pLeft.MainWindowHandle, 0, 0, $half, $h, $true) | Out-Null; "
                f"}}"
            )
            actions.append(f"Left: '{left_win['title']}' (PID {left_win['pid']})")

        if right_win and right_win != left_win:
            ps_script_parts.append(
                f"$pRight = Get-Process -Id {right_win['pid']} -ErrorAction SilentlyContinue; "
                f"if ($pRight) {{ "
                f"[Win32]::ShowWindow($pRight.MainWindowHandle, {_SW_RESTORE}) | Out-Null; "
                f"[Win32]::MoveWindow($pRight.MainWindowHandle, $half, 0, $half, $h, $true) | Out-Null; "
                f"}}"
            )
            actions.append(f"Right: '{right_win['title']}' (PID {right_win['pid']})")

        ok, _, stderr = self._run_ps(" ".join(ps_script_parts))
        if not ok:
            return {"success": False, "message": stderr or "Failed to split screen on Windows."}

        return {
            "success": True,
            "message": f"Split screen positioned: {', '.join(actions)}.",
            "left": left_win,
            "right": right_win,
        }
