"""
UITree — AT-SPI + GNOME Shell desktop automation layer.

Public actions (dispatched via call_action, all whitelisted in self.action):
    launch_app(app_name)            -> Window | None
    find_window(app_name)           -> Window | None
    switch_to_app_gnome(app_name)   -> Window | None
    snapshot()                      -> dict
    find_element(name_hint)         -> list[dict]
    click_element(match_key)        -> True | None | ACTION_NOT_FOUND
    click_by_name(name_hint)        -> True | None | ACTION_NOT_FOUND

Design notes
------------
- `active_window` (Window, pydantic) is the serializable record of whatever
  app was last launched/switched to. It's safe to store on Flow state.
- `_active_acc` is the *live* AT-SPI accessible behind that Window. It is
  NOT serializable and NOT stored on Flow state — it lives only on this
  UITree instance, which the Flow keeps alive across turns (see
  `OstrichFlow._ui_tree`). This is what find_element/click_element scope
  their search to.
- `_element_cache` maps a stable-ish "role:name" match_key -> live
  accessible, populated by find_element() and consumed by click_element().
  It is invalidated whenever launch_app/switch_to_app_gnome fires, since
  the active window has changed and old cached nodes are stale.
"""

import gi
gi.require_version('Atspi', '2.0')
from gi.repository import Atspi

import subprocess
import time
import json
import difflib
from typing import Optional, List, Dict, Any

from pydantic import BaseModel

WINDOW_NOT_FOUND = None
ACTION_NOT_FOUND = "Action_Not_Found"


class Window(BaseModel):
    id: str
    app_name: str
    wm_string: str


class UIElement(BaseModel):
    name: str
    role: str
    match_key: str
    score: float


class UITree:

    # AT-SPI roles worth surfacing as "clickable" candidates. Extend as
    # you hit real-world elements that don't fall into these buckets
    # (e.g. "table cell" for spreadsheet-like UIs).
    _INTERACTIVE_ROLES = {
        "push button", "menu item", "list item", "radio button",
        "check box", "entry", "combo box", "link", "tab", "icon",
    }

    def __init__(self, auto_setup_gnome_permissions=True):
        self.desktop = Atspi.get_desktop(0)

        # Serializable "what's active" record — safe to mirror into Flow state.
        self.active_window: Optional[Window] = None
        # Live AT-SPI handle backing active_window — NOT serializable, stays
        # on this instance only.
        self._active_acc = None
        # match_key -> live accessible, from the most recent find_element().
        self._element_cache: Dict[str, Any] = {}

        if auto_setup_gnome_permissions:
            self._ensure_gnome_permissions()

        self.action = frozenset({
            "launch_app",
            "find_window",
            "switch_to_app_gnome",
            "snapshot",
            "find_element",
            "click_element",
            "click_by_name",
        })

    def call_action(self, action: str, *args, **kwargs):
        """Dispatch to one of the whitelisted methods in self.action by name,
        forwarding any positional/keyword arguments.

        Returns ACTION_NOT_FOUND if `action` isn't in the whitelist (or, as a
        safety net, if it's listed but doesn't actually resolve to a callable
        method — guards against self.action drifting out of sync with the
        real methods on the class).
        """
        if action not in self.action:
            return ACTION_NOT_FOUND

        method = getattr(self, action, None)
        if method is None or not callable(method):
            return ACTION_NOT_FOUND

        try:
            return method(*args, **kwargs)
        except TypeError as e:
            print(f"call_action: bad arguments for '{action}': {e}")
            return ACTION_NOT_FOUND

    # ------------------------------------------------------------------
    # Setup / permissions
    # ------------------------------------------------------------------

    def _ensure_gnome_permissions(self):
        """Best-effort setup of what's needed for switch_to_app_gnome() to work.

        Two things are required on GNOME Wayland:
          1. `development-tools` enabled via gsettings — this part CAN be
             automated, so we just run it here every time (idempotent, safe
             to repeat).
          2. GNOME Shell's `unsafe_mode` flag set to true — this CANNOT be
             automated from outside the Shell process itself. It requires a
             one-time manual step via Looking Glass (Alt+F2 -> lg). We can't
             script opening Looking Glass and typing into it, since that
             itself would need a working input-injection method — chicken
             and egg. So instead we just probe whether Eval is currently
             usable and print clear instructions if it isn't.
        """
        try:
            subprocess.run(
                ["gsettings", "set", "org.gnome.shell", "development-tools", "true"],
                capture_output=True, text=True, timeout=5,
            )
        except Exception as e:
            print(f"[UITree setup] Could not set development-tools via gsettings: {e}")

        try:
            probe = subprocess.run(
                [
                    "gdbus", "call", "--session",
                    "--dest", "org.gnome.Shell",
                    "--object-path", "/org/gnome/Shell",
                    "--method", "org.gnome.Shell.Eval",
                    "true",
                ],
                capture_output=True, text=True, timeout=5,
            )
            if probe.stdout.strip().startswith("(true"):
                self._gnome_eval_ready = True
            else:
                self._gnome_eval_ready = False
                self._warn_unsafe_mode_needed()
        except Exception as e:
            self._gnome_eval_ready = False
            print(f"[UITree setup] Could not probe GNOME Shell Eval: {e}")

    @staticmethod
    def _warn_unsafe_mode_needed():
        print(
            "[UITree setup] GNOME Shell Eval is not usable yet — "
            "switch_to_app_gnome() will fail until you enable unsafe mode "
            "for this session (one-time, cannot be scripted):\n"
            "  1. Press Alt+F2, type 'lg', press Enter (opens Looking Glass)\n"
            "  2. In the console at the bottom, type:\n"
            "       global.context.unsafe_mode = true\n"
            "  3. Press Enter, then close Looking Glass\n"
            "This stays enabled until logout. AT-SPI-based lookups will "
            "still work as a fallback in the meantime, though wm_string "
            "may come back empty and switching may not visually raise "
            "the window on GNOME Wayland."
        )

    # ------------------------------------------------------------------
    # GNOME window-state queries (ground truth for id / wm_string)
    # ------------------------------------------------------------------

    def _query_gnome_windows(self):
        """Query GNOME Shell for id, wm_class and title of every open window.
        Returns a list of dicts: [{"id": "...", "wm_class": "...", "title": "..."}]
        or [] if Eval isn't ready / the call fails.
        """
        if not getattr(self, "_gnome_eval_ready", True):
            return []

        script = (
            "JSON.stringify(global.get_window_actors().map(a => ({"
            "id: String(a.meta_window.get_stable_sequence()), "
            "wm_class: a.meta_window.get_wm_class() || '', "
            "title: a.meta_window.get_title() || ''"
            "})))"
        )

        result = subprocess.run(
            [
                "gdbus", "call", "--session",
                "--dest", "org.gnome.Shell",
                "--object-path", "/org/gnome/Shell",
                "--method", "org.gnome.Shell.Eval",
                script,
            ],
            capture_output=True, text=True,
        )

        if result.returncode != 0 or not result.stdout.strip().startswith("(true"):
            return []

        raw = result.stdout.strip()
        try:
            inner = raw[raw.index("'") + 1: raw.rindex("'")]
            inner = inner.encode().decode("unicode_escape")

            parsed = json.loads(inner)
            # GNOME Shell Eval can return JSON.stringify(...) as a JSON string
            if isinstance(parsed, str):
                parsed = json.loads(parsed)

            return parsed

        except Exception as e:
            print("_query_gnome_windows: failed to parse Eval reply:", e, raw)
            return []

    def _match_gnome_window(self, name_hint):
        """Fuzzy-resolve a loose name against the real GNOME window list.
        Returns the matching dict ({"id","wm_class","title"}) or None."""
        windows = self._query_gnome_windows()
        if not windows or not name_hint:
            return None

        needle = name_hint.lower().strip()

        for w in windows:
            if needle == w.lower():
                return w

        candidates = {w["wm_class"]: w for w in windows if w.get("wm_class")}
        candidates.update({w["title"]: w for w in windows if w.get("title")})
        matches = difflib.get_close_matches(needle, [k.lower() for k in candidates], n=1, cutoff=0.5)
        if matches:
            matched_key = next(k for k in candidates if k.lower() == matches[0])
            return candidates[matched_key]

        return None

    def _window_from_atspi_app(self, app) -> Optional[Window]:
        """Build a Window from an AT-SPI application accessible, filling in
        wm_string by cross-referencing GNOME's real window list where
        possible, and falling back to the AT-SPI process id otherwise."""
        if app is None:
            return None

        app_name = app.get_name() or ""

        match = self._match_gnome_window(app_name)
        if match:
            return Window(id=match["id"], app_name=app_name, wm_string=match.get("wm_class", ""))

        try:
            pid = app.get_process_id()
        except Exception:
            pid = -1
        return Window(id=str(pid), app_name=app_name, wm_string="")

    # ------------------------------------------------------------------
    # Active-window bookkeeping
    # ------------------------------------------------------------------

    def _set_active(self, win: Optional[Window], acc):
        """Single place that updates active_window / _active_acc together,
        so the cache invalidation rule can't be forgotten at a call site."""
        self.active_window = win
        self._active_acc = acc
        self._element_cache = {}

    # ------------------------------------------------------------------
    # Public actions — all return Window / List / dict / None
    # ------------------------------------------------------------------

    def launch_app(self, app_name: str) -> Optional[Window]:
        """Launch an application by executable name, then resolve and
        return the Window that was actually opened. Also sets this as the
        active window/accessible, so a follow-up find_element/click_element
        call (e.g. picking a browser profile) is scoped to it automatically.
        """
        proc = subprocess.Popen([app_name])
        time.sleep(2)

        app = self.find_window(app_name, retries=10, delay=0.5, _raw=True)
        if app is None:
            print(f"launch_app: could not confirm window for '{app_name}' via AT-SPI")
            match = self._match_gnome_window(app_name)
            if match:
                win = Window(id=match["id"], app_name=app_name, wm_string=match.get("wm_class", ""))
            else:
                win = Window(id=str(proc.pid), app_name=app_name, wm_string="")
            # No AT-SPI handle available to scope element lookups to.
            self._set_active(win, None)
            return win

        win = self._window_from_atspi_app(app)
        self._set_active(win, app)
        return win

    def find_window(self, app_name, retries=10, delay=0.5, _raw=False):
        """Search top-level AT-SPI applications for a name match, with retries
        since registration on the a11y bus can lag behind process start.

        Returns a Window by default. Pass _raw=True internally to get the
        underlying AT-SPI accessible instead (used by launch_app() and
        switch_to_app_gnome()). Does NOT change active_window — callers that
        want that call _set_active() themselves.
        """
        for _ in range(retries):
            for i in range(self.desktop.get_child_count()):
                app = self.desktop.get_child_at_index(i)
                if app is None:
                    continue
                name = app.get_name()
                if name and app_name.lower() in name.lower():
                    return app if _raw else self._window_from_atspi_app(app)
            time.sleep(delay)
        return WINDOW_NOT_FOUND

    def switch_to_app_gnome(self, app_name) -> Optional[Window]:
        """Raise/focus a window on GNOME Wayland via GNOME Shell's own JS
        engine (org.gnome.Shell.Eval over D-Bus), then resolve and return
        the Window that was activated — and set it as the active
        window/accessible, same as launch_app.

        `app_name` can be a loose name ("chrome", "vs code") OR a
        previously-returned Window.wm_string.
        """
        if not getattr(self, "_gnome_eval_ready", True):
            print(
                "switch_to_app_gnome: skipping call — Eval was not ready at "
                "startup. Complete the unsafe_mode step, then either "
                "re-instantiate UITree or call self._ensure_gnome_permissions() "
                "again to re-check."
            )
            return None

        script = (
            "global.get_window_actors().forEach(a => { "
            "let w = a.meta_window; "
            f'if (w.get_wm_class() && w.get_wm_class().toLowerCase() === "{app_name.lower()}") '
            "w.activate(global.get_current_time()); "
            "});"
        )

        result = subprocess.run(
            [
                "gdbus", "call", "--session",
                "--dest", "org.gnome.Shell",
                "--object-path", "/org/gnome/Shell",
                "--method", "org.gnome.Shell.Eval",
                script,
            ],
            capture_output=True, text=True,
        )

        if result.returncode != 0:
            print("switch_to_app_gnome: gdbus call failed:", result.stderr.strip())
            return None

        if not result.stdout.strip().startswith("(true"):
            print("switch_to_app_gnome: Eval likely blocked — check development-tools/unsafe_mode setup")
            return None

        # Resolve the live AT-SPI accessible for whatever we just activated,
        # so find_element/click_element have something to scope to.
        app = self.find_window(app_name, retries=6, delay=0.3, _raw=True)
        if app is None:
            print(f"switch_to_app_gnome: activated '{app_name}' but couldn't resolve its AT-SPI accessible")
            self._set_active(self.active_window, None)  # keep last known Window, drop stale acc
            return self.active_window

        win = self._window_from_atspi_app(app)
        self._set_active(win, app)
        return win

    # ------------------------------------------------------------------
    # Element discovery / clicking (scoped to the active window)
    # ------------------------------------------------------------------

    def _snapshot_element_tree(self, acc, max_depth=6):
        """Flat list of named/interactive descendants of `acc`, each tagged
        with the child-index path needed to re-resolve it later via
        _resolve_path(). Depth-bounded to avoid pathological walks on very
        deep trees (e.g. web content inside a browser)."""
        elements = []

        def walk(node, path, depth):
            if node is None or depth > max_depth:
                return
            try:
                name = node.get_name() or ""
                role = node.get_role_name() or ""
            except Exception:
                return
            if name and role in self._INTERACTIVE_ROLES:
                elements.append({"name": name, "role": role, "path": path})
            try:
                count = node.get_child_count()
            except Exception:
                count = 0
            for i in range(count):
                try:
                    child = node.get_child_at_index(i)
                except Exception:
                    continue
                walk(child, path + [i], depth + 1)

        walk(acc, [], 0)
        return elements

    def _resolve_path(self, root, path):
        node = root
        for idx in path:
            try:
                node = node.get_child_at_index(idx)
            except Exception:
                return None
            if node is None:
                return None
        return node

    def find_element(self, name_hint: str) -> List[dict]:
        """Fuzzy-search the ACTIVE window's AT-SPI subtree for elements
        matching `name_hint`. Requires launch_app/switch_to_app_gnome to
        have set an active accessible first.

        Returns up to 10 candidates, best match first, each as
        {"name", "role", "match_key", "score"}. Also (re)populates
        _element_cache keyed by match_key, so click_element() can act on
        a result without re-walking the tree.
        """
        if self._active_acc is None:
            print("find_element: no active window — launch_app/switch_to_app_gnome first")
            return []

        needle = (name_hint or "").lower().strip()
        scored = []
        for el in self._snapshot_element_tree(self._active_acc):
            name_l = el["name"].lower()
            score = 1.0 if needle == name_l else difflib.SequenceMatcher(None, needle, name_l).ratio()
            if score > 0.4:
                scored.append((score, el))
        scored.sort(key=lambda x: -x[0])

        results = []
        self._element_cache = {}
        for score, el in scored[:10]:
            match_key = f"{el['role']}:{el['name']}"
            acc = self._resolve_path(self._active_acc, el["path"])
            if acc is not None:
                self._element_cache[match_key] = acc
                results.append({
                    "name": el["name"],
                    "role": el["role"],
                    "match_key": match_key,
                    "score": round(score, 2),
                })
        return results

    def click_element(self, match_key: str):
        """Click an element previously returned by find_element (by its
        match_key). Requires the element to still be in _element_cache —
        i.e. find_element() must have run since the last active-window
        change and the element must still exist in the live tree."""
        acc = self._element_cache.get(match_key)
        if acc is None:
            print(f"click_element: '{match_key}' not in cache — call find_element first")
            return ACTION_NOT_FOUND
        try:
            action_iface = Atspi.Action.cast(acc)
            target_idx = 0
            for i in range(action_iface.get_n_actions()):
                if (action_iface.get_action_name(i) or "").lower() in ("click", "press", "activate"):
                    target_idx = i
                    break
            action_iface.do_action(target_idx)
            return True
        except Exception as e:
            print(f"click_element: do_action failed: {e}")
            return None

    def click_by_name(self, name_hint: str):
        """One-shot convenience: find the best match for `name_hint` in the
        active window and click it directly. Use for unambiguous 'click X'
        commands where the caller doesn't already have a match_key from a
        prior find_element() call (e.g. answering a disambiguation
        question like 'which profile?' -> 'Abhiram')."""
        matches = self.find_element(name_hint)
        if not matches:
            return ACTION_NOT_FOUND
        return self.click_element(matches[0]["match_key"])

    # ------------------------------------------------------------------
    # Snapshot — desktop-wide state fed to the planning agent each turn
    # ------------------------------------------------------------------

    def snapshot(self):
        """Return the current desktop state:
          - atspi: names of all top-level AT-SPI applications
          - gnome_windows: wm_class of every open GNOME window (ground
            truth for switch_to_app_gnome targets)
          - active_window: present only when an active accessible is set
            (post launch_app/switch_to_app_gnome). Contains the app name
            and every interactive element currently visible in it, so the
            planning agent can decide whether to click something, or ask
            the user to disambiguate between several candidates.
        """
        atspi = []
        for i in range(self.desktop.get_child_count()):
            app = self.desktop.get_child_at_index(i)
            if app is None:
                continue
            atspi.append(app.get_name())

        gnome_windows = self._query_gnome_windows()

        result = {
            "atspi": atspi,
            "gnome_windows": [w["wm_class"] for w in gnome_windows],
        }

        if self._active_acc is not None:
            result["active_window"] = {
                "app_name": self.active_window.app_name if self.active_window else "",
                "elements": self._snapshot_element_tree(self._active_acc, max_depth=4),
            }

        return result


if __name__ == "__main__":
    ui_tree = UITree()

    apps = ui_tree.call_action("snapshot")
    print("Registered apps:", apps)

    win = ui_tree.call_action("launch_app", "google-chrome")
    print("launch_app:", win)

    # If a profile picker (or any disambiguation UI) is on screen, its
    # buttons should now show up here:
    elements = ui_tree.call_action("find_element", "profile")
    print("find_element('profile'):", elements)

    if elements:
        clicked = ui_tree.call_action("click_element", elements[0]["match_key"])
        print("click_element:", clicked)

    # Example of the safety net: unknown action name
    print("unknown action:", ui_tree.call_action("delete_everything"))