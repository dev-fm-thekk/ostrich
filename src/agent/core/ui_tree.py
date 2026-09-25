import gi
gi.require_version('Atspi', '2.0')
from gi.repository import Atspi

import subprocess
import time

WINDOW_NOT_FOUND = None
ACTION_NOT_FOUND = "Action_Not_Found"

class UITree:
    def __init__(self, auto_setup_gnome_permissions=True):
        self.desktop = Atspi.get_desktop(0)

        if auto_setup_gnome_permissions:
            self._ensure_gnome_permissions()

        self.action = frozenset({
            "launch_app",
            "find_window",
            "switch_to_app_gnome",
            "list_apps"
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
        # 1. Enable development-tools (safe to run every time)
        try:
            subprocess.run(
                ["gsettings", "set", "org.gnome.shell", "development-tools", "true"],
                capture_output=True, text=True, timeout=5,
            )
        except Exception as e:
            print(f"[UITree setup] Could not set development-tools via gsettings: {e}")

        # 2. Probe whether Eval actually works right now (harmless no-op script)
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
            "This stays enabled until logout. AT-SPI-based focus_window() "
            "will still work as a fallback in the meantime, though it may "
            "not visually raise the window on GNOME Wayland."
        )

    def launch_app(self, app_name: str):
        """Launch an application by executable name."""
        proc = subprocess.Popen([app_name])
        time.sleep(2)
        return proc

    def find_window(self, app_name, retries=10, delay=0.5):
        """Search top-level AT-SPI applications for a name match, with retries
        since registration on the a11y bus can lag behind process start."""
        for _ in range(retries):
            for i in range(self.desktop.get_child_count()):
                app = self.desktop.get_child_at_index(i)
                if app is None:
                    continue
                name = app.get_name()
                if name and app_name.lower() in name.lower():
                    return app
            time.sleep(delay)
        return WINDOW_NOT_FOUND


    def switch_to_app_gnome(self, wm_class_substring):
        """Actually raise/focus a window on GNOME Wayland via GNOME Shell's
        own JS engine (org.gnome.Shell.Eval over D-Bus).

        Unlike AT-SPI's grab_focus(), this runs with the compositor's own
        privilege to activate windows, so it reliably switches focus
        visually — not just at the accessibility layer.

        Requires, once per session:
            gsettings set org.gnome.shell development-tools true
        and on some GNOME versions, also enabling unsafe mode manually via
        Looking Glass (Alt+F2 -> lg -> `global.context.unsafe_mode = true`),
        since Eval is otherwise locked down. Both of these are checked/set
        automatically in __init__(); see self._gnome_eval_ready.
        """
        if not getattr(self, "_gnome_eval_ready", True):
            print(
                "switch_to_app_gnome: skipping call — Eval was not ready at "
                "startup. Complete the unsafe_mode step, then either "
                "re-instantiate UITree or call self._ensure_gnome_permissions() "
                "again to re-check."
            )
            return False

        needle = wm_class_substring.lower()
        script = (
            "global.get_window_actors().forEach(a => { "
            "let w = a.meta_window; "
            f'if (w.get_wm_class() && w.get_wm_class().toLowerCase().includes("{needle}")) '
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
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            print("gdbus call failed:", result.stderr.strip())
            return False

        # Eval's reply looks like (true, 'true') on success, or
        # (false, '...error text...') if the script itself failed
        # (e.g. Eval disabled, unsafe_mode not set).
        stdout = result.stdout.strip()
        print("gdbus reply:", stdout)
        if stdout.startswith("(true"):
            return True
        print("Eval likely blocked — check development-tools/unsafe_mode setup")
        return False

    def list_apps(self):
        """Debug helper: print every AT-SPI application name currently registered."""
        names = []
        for i in range(self.desktop.get_child_count()):
            app = self.desktop.get_child_at_index(i)
            if app:
                names.append(app.get_name())
        return names


if __name__ == "__main__":
    ui_tree = UITree()

    print("Registered apps:", ui_tree.call_action("list_apps"))

    app = ui_tree.call_action("find_window", "code")
    print("find_window:", app.get_name() if app else None)

    # Preferred: real compositor-level activation via GNOME Shell Eval.
    gnome_result = ui_tree.call_action("switch_to_app_gnome", "chrome")
    print("switch_to_app_gnome result:", gnome_result)

    # Example of the safety net: unknown action name
    print("unknown action:", ui_tree.call_action("delete_everything"))