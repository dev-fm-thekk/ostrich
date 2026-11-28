import re
import subprocess

# D-Bus details for the Window Calls extension
DEST = "org.gnome.Shell"
PATH = "/org/gnome/Shell/Extensions/Windows"
IFACE = "org.gnome.Shell.Extensions.Windows"


def _call_gdbus(method, *args):
    """Run one gdbus method call. Returns (success, stdout, stderr)."""
    cmd = [
        "gdbus", "call", "--session",
        "--dest", DEST,
        "--object-path", PATH,
        "--method", f"{IFACE}.{method}",
        *map(str, args),  # subprocess needs strings
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    return res.returncode == 0, res.stdout.strip(), res.stderr.strip()


def _get_screen_size():
    """Return (width, height) of the screen from xrandr."""
    out = subprocess.run(["xrandr", "--current"], capture_output=True, text=True).stdout
    w, h = re.search(r"current (\d+) x (\d+)", out).groups()
    return int(w), int(h)


def maximize_app(win_id):
    """Maximize the window with this id."""
    ok, _, _ = _call_gdbus("Maximize", win_id)
    return ok


def minimize_app(win_id):
    """Minimize the window with this id."""
    ok, _, _ = _call_gdbus("Minimize", win_id)
    return ok


def split_screen(ratio, screens):
    """
    Put two windows side by side.
    ratio   -> percent of screen width for the LEFT window
    screens -> [left_win_id, right_win_id]
    """
    left_id, right_id = screens
    screen_w, screen_h = _get_screen_size()
    left_w = screen_w * ratio // 100
    right_w = screen_w - left_w

    # A maximized window can't be resized, so un-maximize first
    _call_gdbus("Unmaximize", left_id)
    _call_gdbus("Unmaximize", right_id)

    # MoveResize arguments: window_id, x, y, width, height
    ok1, _, _ = _call_gdbus("MoveResize", left_id, 0, 0, left_w, screen_h)
    ok2, _, _ = _call_gdbus("MoveResize", right_id, left_w, 0, right_w, screen_h)
    return ok1 and ok2
