from pathlib import Path
import gi

gi.require_version("Atspi", "2.0")

from gi.repository import Atspi, GLib

app_dirs = [
    Path("/usr/share/applications"),
    Path.home() / ".local/share/applications",
    Path("/var/lib/flatpak/exports/share/applications"),
    Path.home() / ".local/share/flatpak/exports/share/applications",
    Path("/var/lib/snapd/desktop/applications"),
]

def get_app_aliases(filter=None):
    aliases = []
    for app_dir in app_dirs:
        if not app_dir.is_dir():
            continue
        for desktop_file in app_dir.glob("*.desktop"):
            aliases.append(desktop_file.stem)  # e.g. "org.gnome.Nautilus"
    aliases = sorted(aliases)

    if not filter:
        return aliases

    filter = filter.lower()
    filtered = [a for a in aliases if filter in a.lower()]

    return filtered

WINDOW_ROLES = {
    Atspi.Role.FRAME,
    Atspi.Role.WINDOW,
    Atspi.Role.DIALOG,
    Atspi.Role.ALERT,
}

def get_running_windows():
    windows = []
    desktop = Atspi.get_desktop(0)
    for i in range(desktop.get_child_count()):
        app = desktop.get_child_at_index(i)
        if app is None:
            continue
        for j in range(app.get_child_count()):
            win = app.get_child_at_index(j)
            if win is None or win.get_role() not in WINDOW_ROLES:
                continue
            s = win.get_state_set()
            windows.append({
                "app": app.get_name(),
                "title": win.get_name(),
                "pid": app.get_process_id(),
                "active": s.contains(Atspi.StateType.ACTIVE),
                "minimized": s.contains(Atspi.StateType.ICONIFIED),
                "showing": s.contains(Atspi.StateType.SHOWING),
            })  
    return windows


def get_ui_tree(app, limit, iter=0, _path=()):
    """
    Depth-limited recursive walk of an AT-SPI accessible tree.

    app   : Atspi.Accessible to start from (the app object, or any node)
    limit : max depth to descend (0 = only `app` itself, 1 = + its children, ...)
    iter  : current depth (leave at 0 when calling)
    _path : internal, child-index path from the starting node

    Returns a flat list of dicts: {"name", "description", "path"}
    where path is a "/"-joined string of child indices, e.g. "0/2/1"
    ("" for the starting node itself).
    """
    if app is None or iter > limit:
        return []

    try:
        element = {
            "name": app.get_name() or "",
            "description": app.get_description() or "",
            "path": "/".join(map(str, _path)),
        }
        count = app.get_child_count()
    except GLib.Error:
        # node vanished or the app stopped responding
        return []

    results = [element]

    if iter == limit:
        return results

    for i in range(count):
        try:
            child = app.get_child_at_index(i)
        except GLib.Error:
            continue
        results.extend(get_ui_tree(child, limit, iter + 1, _path + (i,)))

    return results