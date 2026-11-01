"""
UI Tools - Desktop Navigation
=============================
Cross-platform desktop navigation capabilities for Windows and Linux.
"""

from __future__ import annotations

import platform
from abc import ABC, abstractmethod

# Optional needle integration
try:
    import needle
    _HAS_NEEDLE = True
except ImportError:
    _HAS_NEEDLE = False

# Import app naming context resolution
try:
    from ostrich.context.app_aliases import resolve_app_name
except ImportError:
    try:
        from ostrich.context.app_aliases import resolve_app_name
    except ImportError:
        def resolve_app_name(raw: str) -> str:
            return raw


# ===========================================================================
# Base Desktop Navigator
# ===========================================================================

class DesktopNavigator(ABC):
    """Abstract base class for desktop navigation operations."""

    @abstractmethod
    def launch_app(self, app_name: str, args: list[str] | None = None) -> dict:
        """Launch an application by name or path with optional arguments."""
        pass

    @abstractmethod
    def maximize_app(self, app_name: str | int) -> dict:
        """Maximize an application window matched by name, title, PID, or window ID."""
        pass

    @abstractmethod
    def minimize_app(self, app_name: str | int) -> dict:
        """Minimize an application window matched by name, title, PID, or window ID."""
        pass

    @abstractmethod
    def list_windows(self) -> dict:
        """List currently open/visible application windows."""
        pass

    @abstractmethod
    def switch_window(self, target: str | int) -> dict:
        """Bring an application window to the foreground by name, title, PID, or window ID."""
        pass

    @abstractmethod
    def split_screen(
        self,
        left_target: str | int | None = None,
        right_target: str | int | None = None,
    ) -> dict:
        """Tile windows to the left and right halves of the screen."""
        pass

    # Aliases matching tools.py naming
    def open_app(self, app_name: str, args: list[str] | None = None) -> dict:
        return self.launch_app(app_name, args)

    def maximize_window(self, target: str | int) -> dict:
        return self.maximize_app(target)

    def minimize_window(self, target: str | int) -> dict:
        return self.minimize_app(target)

    def switch_app(self, target: str | int) -> dict:
        return self.switch_window(target)


# Platform-specific navigators
try:
    from modules.tools.window.windows import WindowsDesktopNavigator
    from modules.tools.window.linux import LinuxDesktopNavigator
except ImportError:
    from modules.tools.window.windows import WindowsDesktopNavigator
    from modules.tools.window.linux import LinuxDesktopNavigator


# ===========================================================================
# Factory and Global Dispatcher
# ===========================================================================

_navigator_instance: DesktopNavigator | None = None


def get_desktop_navigator() -> DesktopNavigator:
    """Return the DesktopNavigator instance appropriate for the current OS."""
    global _navigator_instance
    if _navigator_instance is None:
        if platform.system().lower() == "windows":
            _navigator_instance = WindowsDesktopNavigator()
        else:
            _navigator_instance = LinuxDesktopNavigator()
    return _navigator_instance


# ===========================================================================
# Needle Tool Wrappers (Exported tools compatible with agent execution)
# ===========================================================================

def open_app(app_name: str, args: list[str] | None = None) -> dict:
    """Open or launch a desktop application by name."""
    return get_desktop_navigator().launch_app(app_name, args)


def list_windows() -> dict:
    """Return a list of all currently visible desktop windows."""
    return get_desktop_navigator().list_windows()


def switch_window(title: str) -> dict:
    """Bring a desktop window to the foreground by matching its title, PID, or window ID."""
    return get_desktop_navigator().switch_window(title)


def maximize_window(title: str) -> dict:
    """Maximize a desktop window by matching its title, PID, or window ID."""
    return get_desktop_navigator().maximize_app(title)


def minimize_window(title: str) -> dict:
    """Minimize a desktop window to the taskbar/dock by matching its title, PID, or window ID."""
    return get_desktop_navigator().minimize_app(title)


def split_screen(
    left_target: str | None = None,
    right_target: str | None = None,
) -> dict:
    """Tile desktop windows side-by-side to split the screen into left and right halves."""
    return get_desktop_navigator().split_screen(left_target, right_target)


# Apply needle decorators if needle is available
if _HAS_NEEDLE:
    open_app = needle.tool(open_app)
    list_windows = needle.tool(list_windows)
    switch_window = needle.tool(switch_window)
    maximize_window = needle.tool(maximize_window)
    minimize_window = needle.tool(minimize_window)
    split_screen = needle.tool(split_screen)
