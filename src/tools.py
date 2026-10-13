"""
Desktop Navigator Tools
=======================
A collection of tools for interacting with the desktop environment.
"""

import subprocess
import needle

from context import resolve_app_name


# ---------------------------------------------------------------------------
# Helper: Start-Process launcher
# ---------------------------------------------------------------------------

def _start_process(app_name: str, args: list[str]) -> dict:
    """Run ``Start-Process <app_name>`` directly via PowerShell.

    No file-path resolution — Windows / PowerShell resolves the name itself,
    exactly like typing ``Start-Process calc`` in a terminal.

    Parameters
    ----------
    app_name : str       – canonical app name (e.g. ``"calc"``, ``"code"``).
    args     : list[str] – optional CLI arguments passed as ``-ArgumentList``.
    """
    # Build optional -ArgumentList fragment
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


# ---------------------------------------------------------------------------
# Tool: Open an Application
# ---------------------------------------------------------------------------

@needle.tool
def open_app(app_name: str, args: list[str] | None = None) -> dict:
    """Open a desktop application by name.

    Parameters
    ----------
    app_name : str
        The application to open (e.g. ``"notepad"``, ``"calc"``, ``"chrome"``).
        Human-friendly names like ``"Google Chrome"`` or ``"Calculator"`` are
        also accepted — they are resolved to the correct Windows name via the
        naming context before launch.
    args : list[str] | None
        Optional CLI arguments to pass to the application.

    Returns
    -------
    dict
        ``{"success": bool, "message": str, "pid": int | None}``

    Examples
    --------
    >>> open_app("calc")
    {'success': True, 'message': "Launched 'calc' via Start-Process (PID 1234).", 'pid': 1234}

    >>> open_app("code", args=["myfile.py"])
    {'success': True, 'message': "Launched 'code' via Start-Process (PID 5678).", 'pid': 5678}
    """
    # Resolve human/model-supplied name → canonical Windows name
    app_name = resolve_app_name(app_name)

    return _start_process(app_name, args or [])


# ---------------------------------------------------------------------------
# Shared helper: run a PowerShell snippet and return stdout
# ---------------------------------------------------------------------------

def _run_ps(command: str, timeout: int = 10) -> tuple[bool, str, str]:
    """Execute *command* in a non-interactive PowerShell session.

    Returns
    -------
    (success, stdout, stderr)
    """
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True, text=True, timeout=timeout,
        )
        return r.returncode == 0, r.stdout.strip(), r.stderr.strip()
    except FileNotFoundError:
        return False, "", "PowerShell not found."
    except subprocess.TimeoutExpired:
        return False, "", "PowerShell command timed out."


# ---------------------------------------------------------------------------
# Tool: List open windows
# ---------------------------------------------------------------------------

@needle.tool
def list_windows() -> dict:
    """Return a list of all currently visible desktop windows.

    Each entry contains the process ID, process name, and window title.

    Returns
    -------
    dict
        ``{"success": bool, "windows": list[dict], "message": str}``

        Each window dict has:
        - ``pid``   (int)  – process ID
        - ``name``  (str)  – process/executable name
        - ``title`` (str)  – window title bar text

    Examples
    --------
    >>> list_windows()
    {
      "success": True,
      "windows": [
        {"pid": 1234, "name": "Notepad",    "title": "Untitled - Notepad"},
        {"pid": 5678, "name": "chrome",     "title": "Google - Chrome"},
        {"pid": 9101, "name": "Calculator", "title": "Calculator"}
      ],
      "message": "Found 3 open window(s)."
    }
    """
    ps_command = (
        "Get-Process | "
        "Where-Object { $_.MainWindowTitle -ne '' } | "
        "Select-Object Id, ProcessName, MainWindowTitle | "
        "ConvertTo-Json -Compress"
    )

    ok, stdout, stderr = _run_ps(ps_command)

    if not ok:
        return {"success": False, "windows": [], "message": stderr or "Failed to list windows."}

    if not stdout:
        return {"success": True, "windows": [], "message": "No open windows found."}

    import json
    raw = json.loads(stdout)
    # ConvertTo-Json returns a single object (not array) when only one result
    if isinstance(raw, dict):
        raw = [raw]

    windows = [
        {
            "pid":   entry["Id"],
            "name":  entry["ProcessName"],
            "title": entry["MainWindowTitle"],
        }
        for entry in raw
    ]

    return {
        "success": True,
        "windows": windows,
        "message": f"Found {len(windows)} open window(s).",
    }


# ---------------------------------------------------------------------------
# Tool: Switch / activate a window
# ---------------------------------------------------------------------------

# Inline C# type loaded once — brings a window handle to the foreground.
_WIN32_TYPE = """
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public class Win32 {
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
}
'@
"""

@needle.tool
def switch_window(title: str) -> dict:
    """Bring a desktop window to the foreground by matching its title.

    The match is case-insensitive and partial — ``"notepad"`` will match
    ``"Untitled - Notepad"``.  If multiple windows match, the first one is
    activated.

    Parameters
    ----------
    title : str
        A substring of the window title to activate
        (e.g. ``"Notepad"``, ``"Chrome"``, ``"Calculator"``).

    Returns
    -------
    dict
        ``{"success": bool, "message": str, "pid": int | None}``

    Examples
    --------
    >>> switch_window("Notepad")
    {'success': True, 'message': "Activated window 'Untitled - Notepad' (PID 1234).", 'pid': 1234}

    >>> switch_window("calc")
    {'success': True, 'message': "Activated window 'Calculator' (PID 5678).", 'pid': 5678}
    """
    ps_command = (
        # Load Win32 helper
        f"{_WIN32_TYPE}"
        # Find the first process whose MainWindowTitle contains the query
        f"$w = Get-Process | "
        f"Where-Object {{ $_.MainWindowTitle -like '*{title}*' }} | "
        f"Select-Object -First 1; "
        # Fail fast if nothing matched
        f"if (-not $w) {{ Write-Error 'NO_MATCH'; exit 1 }}; "
        # SW_RESTORE (9) un-minimises the window, then bring to front
        f"[Win32]::ShowWindow($w.MainWindowHandle, 9) | Out-Null; "
        f"[Win32]::SetForegroundWindow($w.MainWindowHandle) | Out-Null; "
        # Return PID and matched title so Python can report them
        f"Write-Output \"$($w.Id)|$($w.MainWindowTitle)\""
    )

    ok, stdout, stderr = _run_ps(ps_command, timeout=10)

    if not ok:
        if "NO_MATCH" in stderr:
            return {
                "success": False,
                "message": f"No open window found matching '{title}'.",
                "pid": None,
            }
        return {
            "success": False,
            "message": stderr or f"Failed to switch to window '{title}'.",
            "pid": None,
        }

    pid, matched_title = (stdout.split("|", 1) + [""])[:2]
    return {
        "success": True,
        "message": f"Activated window '{matched_title}' (PID {pid}).",
        "pid": int(pid) if pid.isdigit() else None,
    }


# ---------------------------------------------------------------------------
# Shared helper: apply a ShowWindow command by title match
# ---------------------------------------------------------------------------

# ShowWindow nCmdShow constants
_SW_MINIMIZE = 6
_SW_MAXIMIZE = 3
_SW_RESTORE  = 9


def _show_window(title: str, nCmdShow: int, action_label: str) -> dict:
    """Find the first window whose title matches *title* and call
    ``ShowWindow(handle, nCmdShow)`` on it.

    Parameters
    ----------
    title       : str – partial, case-insensitive window title to match.
    nCmdShow    : int – Win32 ShowWindow command constant.
    action_label: str – human-readable action name for result messages.
    """
    ps_command = (
        f"{_WIN32_TYPE}"
        f"$w = Get-Process | "
        f"Where-Object {{ $_.MainWindowTitle -like '*{title}*' }} | "
        f"Select-Object -First 1; "
        f"if (-not $w) {{ Write-Error 'NO_MATCH'; exit 1 }}; "
        f"[Win32]::ShowWindow($w.MainWindowHandle, {nCmdShow}) | Out-Null; "
        f"Write-Output \"$($w.Id)|$($w.MainWindowTitle)\""
    )

    ok, stdout, stderr = _run_ps(ps_command, timeout=10)

    if not ok:
        if "NO_MATCH" in stderr:
            return {
                "success": False,
                "message": f"No open window found matching '{title}'.",
                "pid": None,
            }
        return {
            "success": False,
            "message": stderr or f"Failed to {action_label} window '{title}'.",
            "pid": None,
        }

    pid, matched_title = (stdout.split("|", 1) + [""])[:2]
    return {
        "success": True,
        "message": f"{action_label.capitalize()}d window '{matched_title}' (PID {pid}).",
        "pid": int(pid) if pid.isdigit() else None,
    }


# ---------------------------------------------------------------------------
# Tool: Maximize a window
# ---------------------------------------------------------------------------

@needle.tool
def maximize_window(title: str) -> dict:
    """Maximize a desktop window by matching its title.

    The match is case-insensitive and partial — ``"notepad"`` will match
    ``"Untitled - Notepad"``.

    Parameters
    ----------
    title : str
        A substring of the window title to maximize
        (e.g. ``"Notepad"``, ``"Chrome"``, ``"Calculator"``).

    Returns
    -------
    dict
        ``{"success": bool, "message": str, "pid": int | None}``

    Examples
    --------
    >>> maximize_window("Notepad")
    {'success': True, 'message': "Maximized window 'Untitled - Notepad' (PID 1234).", 'pid': 1234}
    """
    return _show_window(title, _SW_MAXIMIZE, "maximize")


# ---------------------------------------------------------------------------
# Tool: Minimize a window
# ---------------------------------------------------------------------------

@needle.tool
def minimize_window(title: str) -> dict:
    """Minimize a desktop window to the taskbar by matching its title.

    The match is case-insensitive and partial — ``"chrome"`` will match
    ``"Google - Chrome"``.

    Parameters
    ----------
    title : str
        A substring of the window title to minimize
        (e.g. ``"Notepad"``, ``"Chrome"``, ``"Calculator"``).

    Returns
    -------
    dict
        ``{"success": bool, "message": str, "pid": int | None}``

    Examples
    --------
    >>> minimize_window("Chrome")
    {'success': True, 'message': "Minimized window 'Google - Chrome' (PID 5678).", 'pid': 5678}
    """
    return _show_window(title, _SW_MINIMIZE, "minimize")
