from pathlib import Path
import gi

gi.require_version("Atspi", "2.0")

from gi.repository import Atspi

desktop = Atspi.get_desktop(0)

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


