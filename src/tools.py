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
