#!/usr/bin/env python3
"""
LinuxUIManager - navigate any app on GNOME/Wayland.

Generalises the working "GNOME Settings -> Displays" script into reusable pieces:

    list_windows()                  Window Calls extension (gdbus)
    activate_window(id)             Window Calls extension
    launch_app(name)                .desktop lookup via Gio, PATH fallback
    open_app(name)                  find-or-launch + activate + attach to AT-SPI tree
    show_tree(node) / print_tree    dump the accessibility tree (to discover names)
    find_elements(root, ...)        search by name/role, climbs label -> clickable row
    click(x, y)                     uinput ABSOLUTE pointer (exact pixel)
    click_element(app, node)        action -> mouse, verify, self-calibrate, retry
    click_by_name(app, "Displays")  convenience
    navigate("settings", ["Network", "Wi-Fi"])   multi-step navigation

Why it is reliable (same three layers as the reference script):
  1. ABSOLUTE virtual pointer: lands on the exact pixel, no acceleration error.
  2. VERIFY + SELF-CALIBRATE: after a click we look at the target's state
     (selected/checked/...). If a *different* sibling became selected, we measure
     the coordinate error (e.g. invisible GTK shadow on Wayland), correct, retry.
  3. NO-COORDINATE path: AT-SPI doAction() is tried first in "auto" mode.

Setup (same as the reference script):
    sudo apt install python3-pyatspi at-spi2-core python3-gi gir1.2-gtk-4.0
    pip install python-uinput
    sudo modprobe uinput
    echo 'KERNEL=="uinput", GROUP="input", MODE="0660"' | \
        sudo tee /etc/udev/rules.d/99-uinput.rules
    sudo usermod -aG input $USER     # log out/in. Do NOT run with sudo.
    sudo udevadm control --reload && sudo udevadm trigger
    GNOME extension: "Window Calls"
    gsettings set org.gnome.desktop.interface toolkit-accessibility true

Electron apps (VS Code, Slack...) only expose their tree if started with
    --force-renderer-accessibility
"""

import argparse 
import ast
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Union

import pyatspi

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #
# Friendly name -> substrings looked for in wm_class / wm_class_instance / title
APP_ALIASES: Dict[str, Tuple[str, ...]] = {
    "settings": ("gnome-control-center", "org.gnome.settings"),
    "vscode": ("code",),
    "terminal": ("gnome-terminal", "org.gnome.terminal", "kgx", "console"),
    "files": ("nautilus", "org.gnome.nautilus"),
    "browser": ("firefox", "chrome", "chromium"),
}

WINDOW_ROLES = (pyatspi.ROLE_FRAME, pyatspi.ROLE_WINDOW, pyatspi.ROLE_DIALOG)

# Roles a human would call "the thing you click". A label inside one of these
# is climbed up to the container (e.g. sidebar label -> list row).
CLICKABLE_ROLE_NAMES = {
    "list item", "push button", "toggle button", "check box", "radio button",
    "menu item", "check menu item", "radio menu item", "page tab", "link",
    "combo box", "tree item", "table cell", "tab", "icon",
}

Coord = Tuple[int, int]
Extents = Tuple[int, int, int, int]


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
def safe(func, default=None):
    try:
        return func()
    except Exception:
        return default


def children(node) -> Iterable[Any]:
    count = safe(lambda: node.childCount, 0) or 0
    for i in range(count):
        child = safe(lambda: node.getChildAtIndex(i))
        if child is not None:
            yield child


def role_name(node) -> str:
    return (safe(lambda: node.getRoleName(), "") or "").lower().replace("_", " ")


def text_of(node) -> str:
    name = safe(lambda: node.name, "") or ""
    if name:
        return name
    text = safe(lambda: node.queryText())
    if text is not None:
        return safe(lambda: text.getText(0, text.characterCount), "") or ""
    return ""


def has_state(node, state) -> bool:
    st = safe(lambda: node.getState())
    return bool(st and st.contains(state))


def is_selected(node) -> bool:
    return has_state(node, pyatspi.STATE_SELECTED)


def get_extents(node, coord_type) -> Optional[Extents]:
    comp = safe(lambda: node.queryComponent())
    box = safe(lambda: comp.getExtents(coord_type)) if comp else None
    return (box.x, box.y, box.width, box.height) if box else None


def center(ext: Extents) -> Coord:
    return ext[0] + ext[2] // 2, ext[1] + ext[3] // 2


def has_action(node) -> bool:
    iface = safe(lambda: node.queryAction())
    return bool(iface and (safe(lambda: iface.nActions, 0) or 0) > 0)


def state_snapshot(node) -> Tuple[bool, ...]:
    return tuple(has_state(node, s) for s in (
        pyatspi.STATE_SELECTED, pyatspi.STATE_CHECKED, pyatspi.STATE_PRESSED,
        pyatspi.STATE_EXPANDED, pyatspi.STATE_FOCUSED))


def is_stateful(node) -> bool:
    """True if a click on this node should visibly change its state."""
    return has_state(node, pyatspi.STATE_SELECTABLE) or has_state(node, pyatspi.STATE_CHECKABLE)


@dataclass
class AppWindow:
    """A running app window with its matching AT-SPI top-level node."""
    id: int
    title: str
    pid: Optional[int]
    info: Dict[str, Any]
    root: Any                       # AT-SPI frame node
    coord_type: Any                 # pyatspi.WINDOW_COORDS or DESKTOP_COORDS


# --------------------------------------------------------------------------- #
# Virtual mouse (uinput)
# --------------------------------------------------------------------------- #
class Mouse:
    """uinput pointer: 'absolute' (exact pixel) or 'relative' (accelerated)."""

    def __init__(self, mode: str, bounds: Tuple[int, int, int, int], scale: float = 1.0):
        self.mode, self.bounds, self.scale = mode, bounds, scale
        self._ctx = None
        self.dev = None

    def open(self):
        import uinput  # imported lazily so window-only usage doesn't need it
        self._uinput = uinput
        _, _, w, h = self.bounds
        if self.mode == "absolute":
            events = (uinput.BTN_LEFT, uinput.BTN_RIGHT,
                      uinput.ABS_X + (0, w - 1, 0, 0),
                      uinput.ABS_Y + (0, h - 1, 0, 0))
        else:
            events = (uinput.REL_X, uinput.REL_Y, uinput.BTN_LEFT, uinput.BTN_RIGHT)
        self._ctx = uinput.Device(events)
        self.dev = self._ctx.__enter__()
        time.sleep(0.25)  # let the compositor register the new device
        return self

    def close(self):
        if self._ctx is not None:
            self._ctx.__exit__(None, None, None)
            self._ctx = self.dev = None

    def move_to(self, x: int, y: int) -> bool:
        u = self._uinput
        if self.mode == "absolute":
            x0, y0, w, h = self.bounds
            self.dev.emit(u.ABS_X, max(0, min(w - 1, x - x0)), syn=False)
            self.dev.emit(u.ABS_Y, max(0, min(h - 1, y - y0)))
            return True
        return self._move_relative_to(x, y)

    def click(self, button: str = "left", double: bool = False):
        btn = self._uinput.BTN_RIGHT if button == "right" else self._uinput.BTN_LEFT
        for _ in range(2 if double else 1):
            self.dev.emit(btn, 1)
            time.sleep(0.02)
            self.dev.emit(btn, 0)
            time.sleep(0.04)

    # ----- relative mode ---------------------------------------------------- #
    def _rel(self, dx, dy, step=5, delay=0.005):
        u = self._uinput
        while dx or dy:
            sx, sy = max(-step, min(step, dx)), max(-step, min(step, dy))
            self.dev.emit(u.REL_X, sx, syn=False)
            self.dev.emit(u.REL_Y, sy)
            dx -= sx
            dy -= sy
            time.sleep(delay)

    @staticmethod
    def _pointer() -> Optional[Coord]:
        try:
            out = subprocess.run(["xdotool", "getmouselocation", "--shell"],
                                 capture_output=True, text=True, timeout=2, check=True).stdout
            vals = dict(line.split("=", 1) for line in out.split())
            return int(vals["X"]), int(vals["Y"])
        except Exception:
            return None

    def _move_relative_to(self, tx, ty) -> bool:
        before = self._pointer()
        if before is not None:
            self._rel(20, 20)
            time.sleep(0.1)
            if self._pointer() not in (None, before):  # read-back works: closed loop
                for _ in range(40):
                    x, y = self._pointer()
                    if abs(tx - x) <= 2 and abs(ty - y) <= 2:
                        return True
                    self._rel(tx - x, ty - y)
                    time.sleep(0.05)
                return False
        self._rel(-10000, -10000, step=100, delay=0.002)  # home to (0, 0)
        time.sleep(0.1)
        self._rel(round(tx / self.scale), round(ty / self.scale))
        return True


# --------------------------------------------------------------------------- #
# Manager
# --------------------------------------------------------------------------- #
class LinuxUIManager:
    def __init__(self, mouse_mode: str = "absolute", coords: str = "auto",
                 screen: Optional[str] = None, scale: float = 1.0, debug: bool = False):
        """
        mouse_mode: "absolute" (recommended) or "relative"
        coords:     "auto" (window coords on Wayland, desktop on X11), "window", "desktop"
        screen:     override desktop size, e.g. "1920x1080"
        """
        self.mouse_mode, self.screen, self.scale, self.debug = mouse_mode, screen, scale, debug
        if coords == "auto":
            coords = "window" if os.environ.get("XDG_SESSION_TYPE") == "wayland" else "desktop"
        self.coords = coords
        self.coord_type = pyatspi.WINDOW_COORDS if coords == "window" else pyatspi.DESKTOP_COORDS
        self._mouse: Optional[Mouse] = None
        self._warm: Optional[threading.Thread] = None
        self._bounds = None
        self._active_id = None
        self._lock = threading.Lock()

    # ---- lifecycle --------------------------------------------------------- #
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        if self._mouse:
            self._mouse.close()
            self._mouse = None

    def _log(self, *a):
        print(*a)

    def _dbg(self, *a):
        if self.debug:
            print("[debug]", *a)

    # ---- gdbus / Window Calls --------------------------------------------- #
    def _gdbus(self, method: str, *args) -> str:
        cmd = [
            "gdbus", "call", "--session",
            "--dest", "org.gnome.Shell",
            "--object-path", "/org/gnome/Shell/Extensions/Windows",
            "--method", f"org.gnome.Shell.Extensions.Windows.{method}",
            *[str(a) for a in args],
        ]
        self._dbg("Running:", cmd)
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"gdbus {method} failed: {result.stderr.strip()}")
        return result.stdout.strip()

    @staticmethod
    def _unwrap(output: str):
        """gdbus prints "('<value>',)"; return the inner value."""
        return ast.literal_eval(output)[0]

    def list_windows(self) -> List[Dict[str, Any]]:
        return json.loads(self._unwrap(self._gdbus("List")))

    def get_title(self, win_id) -> str:
        return safe(lambda: self._unwrap(self._gdbus("GetTitle", win_id)), "") or ""

    def get_frame_origin(self, win_id) -> Optional[Coord]:
        rect = safe(lambda: json.loads(self._unwrap(self._gdbus("GetFrameRect", win_id))))
        return (rect["x"], rect["y"]) if rect else None

    def activate_window(self, id, settle: float = 0.05) -> bool:
        try:
            self._gdbus("Activate", id)
            self._active_id = id
            time.sleep(settle)
            return True
        except (RuntimeError, subprocess.SubprocessError):
            return False

    @staticmethod
    def _hints(query: str) -> Tuple[str, ...]:
        q = query.lower()
        return APP_ALIASES.get(q, (q,))

    def find_window(self, query: str) -> Optional[Dict[str, Any]]:
        """First window whose wm_class / instance / title contains the query (or alias)."""
        hints = self._hints(query)
        for w in self.list_windows():
            hay = " ".join(str(w.get(k) or "") for k in ("wm_class", "wm_class_instance", "title")).lower()
            if any(h in hay for h in hints):
                return w
        return None

    def wait_for_window(self, query: str, timeout: float = 10.0) -> Optional[Dict[str, Any]]:
        deadline = time.time() + timeout
        while time.time() < deadline:
            w = safe(lambda: self.find_window(query))
            if w:
                return w
            time.sleep(0.1)
        return None

    # ---- launching --------------------------------------------------------- #
    def launch_app(self, app_name: str) -> bool:
        """Start an app by name ('settings', 'org.gnome.Nautilus', 'firefox', ...)."""
        try:
            import gi
            gi.require_version("Gio", "2.0")
            from gi.repository import Gio
            info = None
            for group in Gio.DesktopAppInfo.search(app_name):
                for desktop_id in group:
                    cand = Gio.DesktopAppInfo.new(desktop_id)
                    if cand and cand.should_show():
                        info = cand
                        break
                if info:
                    break
            if info is None:
                info = Gio.DesktopAppInfo.new(app_name + ".desktop")
            if info and info.launch([], None):
                return True
        except Exception as e:
            self._dbg("Gio launch failed:", e)

        exe = shutil.which(app_name) or shutil.which(app_name.lower())
        if exe:
            subprocess.Popen([exe], start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        return False

    def open_app(self, query: str, launch: bool = True, timeout: float = 10.0,
                 settle: float = 0.3) -> AppWindow:
        """Find (or launch) the app, bring it to front and attach to its AT-SPI tree."""
        win = self.find_window(query)
        if win is None:
            if not launch or not self.launch_app(query):
                raise RuntimeError(f"No window for {query!r} and it could not be launched.")
            self._log(f"Launching {query!r}...")
            win = self.wait_for_window(query, timeout)
            if win is None:
                raise RuntimeError(f"Window for {query!r} did not appear.")
            time.sleep(settle)  # let the UI populate

        win_id = win["id"]
        title = self.get_title(win_id)
        self._log(f"Activating window {win_id}: {title}")
        self.activate_window(win_id)

        root = self._find_atspi_window(win, title, timeout)
        if root is None:
            raise RuntimeError("Window not found in the AT-SPI tree (is accessibility enabled?).")
        return AppWindow(id=win_id, title=title, pid=win.get("pid"), info=win,
                         root=root, coord_type=self.coord_type)

    def _find_atspi_window(self, win: Dict[str, Any], title: str, timeout: float = 10.0):
        names = {str(win.get(k) or "").lower() for k in ("wm_class", "wm_class_instance")} - {""}
        names |= {h for n in list(names) for h in APP_ALIASES.get(n, ())}
        pid = win.get("pid")
        deadline = time.time() + timeout
        while True:
            fallback = None
            for app in children(pyatspi.Registry.getDesktop(0)):
                app_pid = safe(lambda: app.get_process_id())
                app_name = (safe(lambda: app.name, "") or "").lower()
                same_app = (pid and app_pid == pid) or any(n in app_name or app_name in n
                                                           for n in names if app_name)
                if not same_app:
                    continue
                for w in children(app):
                    if safe(lambda: w.getRole()) not in WINDOW_ROLES:
                        continue
                    if title and safe(lambda: w.name) == title:
                        return w
                    fallback = fallback or w
            if fallback is not None or time.time() >= deadline:
                return fallback
            time.sleep(0.1)

    # ---- tree inspection --------------------------------------------------- #
    def show_tree(self, node, depth: int = 0, max_depth: int = 60,
                  with_geometry: bool = False, showing_only: bool = False) -> Optional[dict]:
        """Recursively build a JSON-serialisable AT-SPI tree."""
        if node is None or depth > max_depth:
            return None
        tree: Dict[str, Any] = {
            "name": safe(lambda: node.name, "") or "",
            "role": safe(lambda: node.getRoleName(), "") or "",
            "description": safe(lambda: node.description, "") or "",
            "depth": depth,
            "children": [],
        }
        if with_geometry:
            tree["extents"] = get_extents(node, self.coord_type)
            tree["showing"] = has_state(node, pyatspi.STATE_SHOWING)
            tree["actions"] = has_action(node)
        if depth >= max_depth:
            return tree
        for child in children(node):
            if showing_only and not has_state(child, pyatspi.STATE_SHOWING):
                continue
            sub = self.show_tree(child, depth + 1, max_depth, with_geometry, showing_only)
            if sub is not None:
                tree["children"].append(sub)
        return tree

    @staticmethod
    def print_tree(tree: Optional[dict], skip_unnamed: bool = False):
        """Pretty-print the result of show_tree()."""
        if not tree:
            return
        if not (skip_unnamed and not tree.get("name")):
            extra = f" {tree['extents']}" if tree.get("extents") else ""
            print(f"{'  ' * tree['depth']}[{tree['role']}] {tree['name']!r}{extra}")
        for c in tree["children"]:
            LinuxUIManager.print_tree(c, skip_unnamed)

    # ---- searching --------------------------------------------------------- #
    @staticmethod
    def _name_matches(text: str, wanted: str, mode: str) -> bool:
        t, w = text.strip().lower(), wanted.lower()
        if mode == "exact":
            return t == w
        if mode == "contains":
            return w in t
        if mode == "regex":
            return re.search(wanted, text, re.I) is not None
        return t.startswith(w)  # "startswith" (default, like the reference script)

    @staticmethod
    def _climb_to_clickable(node):
        """Label inside a row/button -> the row/button itself."""
        n = node
        for _ in range(4):
            if role_name(n) in CLICKABLE_ROLE_NAMES or has_action(n):
                return n
            n = safe(lambda: n.parent)
            if n is None:
                break
        return node

    def find_elements(self, root, name: Optional[str] = None, role: Optional[str] = None,
                      match: str = "startswith", showing_only: bool = True,
                      max_depth: int = 40, climb: bool = True) -> List[Any]:
        """
        All matching nodes, sorted leftmost-then-topmost (the reference script prefers
        the leftmost hit so sidebar entries win over same-named content-pane items).
        `role` is an AT-SPI role name such as "list item" or "push button".
        """
        role = role.lower().replace("_", " ") if role else None
        found, seen = [], set()
        stack = [(root, 0)]
        while stack:
            node, depth = stack.pop()
            if showing_only and depth > 0 and not has_state(node, pyatspi.STATE_SHOWING):
                continue  # hidden subtree: skip it entirely (big speed-up)
            ok = True
            if role and role_name(node) != role:
                ok = False
            if ok and name is not None and not self._name_matches(text_of(node), name, match):
                ok = False
            if ok and (name is not None or role):
                target = self._climb_to_clickable(node) if (climb and not role) else node
                ext = get_extents(target, self.coord_type)
                if ext and ext[2] > 0 and ext[3] > 0 and ext not in seen:
                    seen.add(ext)
                    found.append((ext, target))
            if depth < max_depth:
                stack.extend((c, depth + 1) for c in children(node))
        found.sort(key=lambda p: (p[0][0], p[0][1]))
        return [n for _, n in found]

    def wait_for(self, app: AppWindow, name: Optional[str] = None, role: Optional[str] = None,
                 timeout: float = 8.0, **kw):
        """Poll until an element appears (UIs populate lazily). Returns node or None."""
        hits = self.wait_for_all(app, name, role, timeout, **kw)
        return hits[0] if hits else None

    def wait_for_all(self, app: AppWindow, name: Optional[str] = None, role: Optional[str] = None,
                     timeout: float = 8.0, **kw) -> List[Any]:
        """Poll until at least one element matches; returns ALL hits (one tree walk per poll)."""
        deadline = time.time() + timeout
        while True:
            hits = self.find_elements(app.root, name, role, **kw)
            if hits or time.time() >= deadline:
                return hits
            time.sleep(0.1)

    # ---- low-level click --------------------------------------------------- #
    def warm_up(self):
        """Create the virtual mouse in a background thread (saves ~1 s on the first click)."""
        if self._mouse is not None or self._warm is not None:
            return
        try:
            self._bounds = self._desktop_bounds()  # main thread: GTK is not thread-safe
        except Exception as e:
            self._dbg("warm_up skipped:", e)
            return
        self._warm = threading.Thread(target=lambda: safe(self._ensure_mouse), daemon=True)
        self._warm.start()

    def _ensure_mouse(self) -> Mouse:
        with self._lock:
            if self._mouse is None:
                bounds = self._bounds or self._desktop_bounds()
                self._mouse = Mouse(self.mouse_mode, bounds, self.scale).open()
                self._log(f"Virtual {self.mouse_mode} mouse initialised.")
        return self._mouse

    def _desktop_bounds(self) -> Tuple[int, int, int, int]:
        """(x0, y0, width, height) of the whole desktop in logical pixels."""
        if self.screen:
            w, h = (int(v) for v in self.screen.lower().split("x"))
            return (0, 0, w, h)
        try:
            import gi
            gi.require_version("Gtk", "4.0")
            from gi.repository import Gdk, Gtk
            if Gtk.init_check():
                mons = Gdk.Display.get_default().get_monitors()
                rects = [mons.get_item(i).get_geometry() for i in range(mons.get_n_items())]
                x0, y0 = min(r.x for r in rects), min(r.y for r in rects)
                return (x0, y0, max(r.x + r.width for r in rects) - x0,
                        max(r.y + r.height for r in rects) - y0)
        except Exception:
            pass
        try:
            out = subprocess.run(["xrandr", "--current"], capture_output=True,
                                 text=True, check=True).stdout
            m = re.search(r"current (\d+) x (\d+)", out)
            if m:
                return (0, 0, int(m.group(1)), int(m.group(2)))
        except Exception:
            pass
        raise RuntimeError("Could not detect desktop size; pass screen='WIDTHxHEIGHT'")

    def click(self, x: int, y: int, button: str = "left", double: bool = False) -> bool:
        """Click at absolute DESKTOP logical pixel (x, y)."""
        try:
            mouse = self._ensure_mouse()
            mouse.move_to(x, y)
            time.sleep(0.02)
            mouse.click(button, double)
            return True
        except Exception as e:
            self._log(f"click failed: {e}")
            return False

    # ---- element click: action -> mouse, verify, calibrate ------------------ #
    @staticmethod
    def _poll(fn, timeout: float = 0.5, step: float = 0.05) -> bool:
        """Return as soon as fn() is truthy instead of sleeping a fixed time."""
        end = time.time() + timeout
        while True:
            if fn():
                return True
            if time.time() >= end:
                return False
            time.sleep(step)

    @staticmethod
    def _do_action(node) -> bool:
        iface = safe(lambda: node.queryAction())
        return bool(iface and safe(lambda: iface.doAction(0), False))

    @staticmethod
    def _siblings(node) -> List[Tuple[int, Any]]:
        parent = safe(lambda: node.parent)
        if parent is None:
            return []
        rn = role_name(node)
        return [(safe(lambda: c.getIndexInParent(), i), c)
                for i, c in enumerate(children(parent)) if role_name(c) == rn]

    def _origin(self, app: AppWindow) -> Coord:
        if app.coord_type == pyatspi.WINDOW_COORDS:
            return self.get_frame_origin(app.id) or (0, 0)
        return (0, 0)

    def target_point(self, app: AppWindow, node, offset: Coord = (0, 0)) -> Optional[Coord]:
        ext = get_extents(node, app.coord_type)
        if not ext:
            return None
        cx, cy = center(ext)
        ox, oy = self._origin(app)
        return cx + ox + offset[0], cy + oy + offset[1]

    def click_element(self, app: AppWindow, node, method: str = "auto",
                      offset: Coord = (0, 0), calibrate: bool = True,
                      attempts: int = 2, dry_run: bool = False) -> bool:
        """
        method: "auto"   -> AT-SPI action first, mouse fallback if state did not change
                "action" -> AT-SPI action only (no coordinates)
                "mouse"  -> calibrated absolute-pointer click
        """
        label = text_of(node) or role_name(node) or "element"
        pt = self.target_point(app, node, offset)
        if dry_run:
            self._log(f"[dry-run] {label!r} -> {pt}")
            return pt is not None

        if self._active_id != app.id:
            self.activate_window(app.id)
        stateful = is_stateful(node)
        before = state_snapshot(node)

        def effect() -> bool:
            return (not stateful) or is_selected(node) or state_snapshot(node) != before

        if method in ("auto", "action"):
            if self._do_action(node):
                if method == "action" or self._poll(effect, 0.2):
                    self._log(f"Triggered {label!r} via AT-SPI action.")
                    return True
                self._log("Action sent but no state change; falling back to mouse.")
            elif method == "action":
                self._log(f"{label!r} has no usable action.")
                return False

        off = list(offset)
        siblings = self._siblings(node)
        for attempt in range(1, attempts + 1):
            ext = get_extents(node, app.coord_type)
            if not ext:
                return False
            cx, cy = center(ext)
            ox, oy = self._origin(app)
            x, y = cx + ox + off[0], cy + oy + off[1]
            self._log(f"Attempt {attempt}: clicking {label!r} at ({x}, {y}) offset=({off[0]}, {off[1]})")
            self._dbg("extents", ext, "origin", (ox, oy), "coord_type", self.coords)

            sel_before = {i for i, s in siblings if is_selected(s)}
            before = state_snapshot(node)
            if not self.click(x, y):
                return False
            if self._poll(effect, 0.3):
                self._log(f"Verified: {label!r}" + (" is now selected." if stateful else " clicked."))
                if off != list(offset):
                    self._log(f"Measured correction: use offset={tuple(off)} to hit it first time.")
                return True

            hit = next((s for i, s in siblings if i not in sel_before and is_selected(s)), None)
            if hit is None or not calibrate:
                self._log("Clicked, but selection could not be verified.")
                return False
            hext = get_extents(hit, app.coord_type)
            self._log(f"Landed on {text_of(hit) or 'another item'!r}; correcting.")
            off[0] += cx - (hext[0] + hext[2] // 2)
            off[1] += cy - (hext[1] + hext[3] // 2)
        return False

    # ---- high-level helpers ------------------------------------------------ #
    def click_by_name(self, app: AppWindow, name: str, role: Optional[str] = None,
                      match: str = "startswith", nth: int = 0, timeout: float = 8.0,
                      **click_kw) -> bool:
        """Find an element by visible name (+ optional role) and click it."""
        hits = self.wait_for_all(app, name, role, timeout, match=match)
        if len(hits) <= nth:
            self._log(f"No visible element matching {name!r}"
                      + (f" with role {role!r}" if role else "")
                      + ". Narrow window? Try --dump to see names.")
            return False
        if len(hits) > 1:
            self._dbg(f"{len(hits)} matches for {name!r}; using #{nth}")
        return self.click_element(app, hits[nth], **click_kw)

    def set_text(self, app: AppWindow, node, text: str) -> bool:
        """Put text into an editable field (AT-SPI EditableText, no keyboard needed)."""
        editable = safe(lambda: node.queryEditableText())
        if editable is None:
            return False
        safe(lambda: node.queryComponent().grabFocus())
        return bool(safe(lambda: editable.setTextContents(text), False))

    def navigate(self, app_query: str, steps: Sequence[Union[str, Dict[str, Any]]],
                 **click_kw) -> bool:
        """
        Open an app and click through a path of elements.
            ui.navigate("settings", ["Displays"])
            ui.navigate("settings", ["Network", {"name": "Wi-Fi", "role": "push button"}])
        Each step is a name string or kwargs for click_by_name(); the next step
        waits for its element to appear after the previous click.
        """
        app = self.open_app(app_query)
        for step in steps:
            spec = {"name": step} if isinstance(step, str) else dict(step)
            spec.update(click_kw)
            if not self.click_by_name(app, **spec):
                return False
        return True


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _parse_offset(text: str) -> Coord:
    dx, dy = (int(v) for v in text.split(","))
    return dx, dy


def main():
    p = argparse.ArgumentParser(description="Navigate any GNOME/Wayland app via AT-SPI + uinput.")
    p.add_argument("app", help="app/window query, e.g. settings, code, nautilus")
    p.add_argument("labels", nargs="*", help="element names to click in order")
    p.add_argument("--role", help="AT-SPI role filter, e.g. 'push button'")
    p.add_argument("--method", choices=["auto", "action", "mouse"], default="auto")
    p.add_argument("--mouse", choices=["absolute", "relative"], default="absolute")
    p.add_argument("--coords", choices=["auto", "window", "desktop"], default="auto")
    p.add_argument("--offset", type=_parse_offset, default=(0, 0), metavar="DX,DY")
    p.add_argument("--screen", metavar="WxH")
    p.add_argument("--match", choices=["startswith", "exact", "contains", "regex"],
                   default="startswith")
    p.add_argument("--no-calibrate", action="store_true")
    p.add_argument("--no-launch", action="store_true")
    p.add_argument("--dump", action="store_true", help="print the visible accessibility tree and exit")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--debug", action="store_true")
    a = p.parse_args()

    with LinuxUIManager(a.mouse, a.coords, a.screen, debug=a.debug) as ui:
        app = ui.open_app(a.app, launch=not a.no_launch)
        if a.dump:
            ui.print_tree(ui.show_tree(app.root, with_geometry=True, showing_only=True),
                          skip_unnamed=True)
            return
        ok = True
        for label in a.labels:
            ok = ui.click_by_name(app, label, role=a.role, match=a.match, method=a.method,
                                  offset=a.offset, calibrate=not a.no_calibrate,
                                  dry_run=a.dry_run)
            if not ok:
                break
            time.sleep(0.4)
        sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()