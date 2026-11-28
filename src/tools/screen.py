import ast
import json
import re
import subprocess

# D-Bus details for the Window Calls extension
DEST = "org.gnome.Shell"
PATH = "/org/gnome/Shell/Extensions/Windows"
IFACE = "org.gnome.Shell.Extensions.Windows"


def _call_gdbus(method: str, *args):
    """Run one gdbus method call. Returns (success, stdout, stderr)."""
    cmd = [
        "gdbus", "call", "--session",
        "--dest", DEST,
        "--object-path", PATH,
        "--method", f"{IFACE}.{method}",
    ]
    cmd.extend(str(a) for a in args)  # add method arguments, if any

    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        return res.returncode == 0, res.stdout.strip(), res.stderr.strip()
    except FileNotFoundError:
        return False, "", "gdbus executable not found."
    except subprocess.TimeoutExpired:
        return False, "", "gdbus call timed out."
    except OSError as e:
        return False, "", str(e)


def _get_window_id(pid: str):
    """Find the GNOME window id that belongs to a process id (or None)."""
    ok, out, _ = _call_gdbus("List")
    if not ok:
        return None

    # gdbus prints something like: ('[{"id": 123, "pid": 456, ...}]',)
    # literal_eval turns that into a tuple, [0] is the JSON string.
    windows = json.loads(ast.literal_eval(out)[0])

    for w in windows:
        if str(w["pid"]) == str(pid):
            return w["id"]
    return None


def _get_screen_size():
    """Return (width, height) of the screen using xrandr."""
    out = subprocess.run(["xrandr", "--current"], capture_output=True, text=True).stdout
    match = re.search(r"current (\d+) x (\d+)", out)
    return int(match.group(1)), int(match.group(2))


def maximize_app(win: str) -> bool:
    """Maximize the window that belongs to the given process id."""
    win_id = _get_window_id(win)
    if win_id is None:
        return False
    ok, _, _ = _call_gdbus("Maximize", win_id)
    return ok


def minimize_app(app_id: str) -> bool:
    """Minimize the window that belongs to the given process id."""
    win_id = _get_window_id(app_id)
    if win_id is None:
        return False
    ok, _, _ = _call_gdbus("Minimize", win_id)
    return ok


def split_screen(ratio: int, screens: list[str]) -> bool:
    """
    Put two windows side by side.
    ratio   -> percent of the screen width given to the LEFT window (e.g. 50, 70)
    screens -> [left_pid, right_pid]
    """
    if len(screens) != 2:
        return False

    screen_w, screen_h = _get_screen_size()
    left_w = screen_w * ratio // 100   # width of the left window
    right_w = screen_w - left_w        # the right window gets the rest

    left_id = _get_window_id(screens[0])
    right_id = _get_window_id(screens[1])
    if left_id is None or right_id is None:
        return False

    # A maximized window can't be resized, so un-maximize both first
    _call_gdbus("Unmaximize", left_id)
    _call_gdbus("Unmaximize", right_id)

    # MoveResize arguments: window_id, x, y, width, height
    ok1, _, _ = _call_gdbus("MoveResize", left_id, 0, 0, left_w, screen_h)
    ok2, _, _ = _call_gdbus("MoveResize", right_id, left_w, 0, right_w, screen_h)
    return ok1 and ok2
