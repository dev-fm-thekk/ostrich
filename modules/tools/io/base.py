"""
IO Tools - Base Interface
=========================
Abstract base classes and unified interface for user input/output interactions:
- Mouse: move, click, double click, select (drag-select)
- Keyboard: type text, press key, hotkey shortcuts
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


# ===========================================================================
# Base Mouse & Keyboard Interfaces
# ===========================================================================

class MouseNavigator(ABC):
    """Abstract base class defining mouse interaction interfaces."""

    @abstractmethod
    def move(self, x: int, y: int) -> dict:
        """Move mouse cursor to coordinates (x, y)."""
        pass

    @abstractmethod
    def click(self, x: int | None = None, y: int | None = None, button: str = "left") -> dict:
        """Click at optional coordinates (x, y) with specified button (left, right, middle)."""
        pass

    @abstractmethod
    def double_click(self, x: int | None = None, y: int | None = None, button: str = "left") -> dict:
        """Double click at optional coordinates (x, y)."""
        pass

    @abstractmethod
    def select(self, start_x: int, start_y: int, end_x: int, end_y: int) -> dict:
        """Drag-select from (start_x, start_y) to (end_x, end_y)."""
        pass


class KeyboardNavigator(ABC):
    """Abstract base class defining keyboard interaction interfaces."""

    @abstractmethod
    def type_text(self, text: str) -> dict:
        """Type given text string."""
        pass

    @abstractmethod
    def press_key(self, key: str) -> dict:
        """Press a specific key."""
        pass

    @abstractmethod
    def hotkey(self, *keys: str) -> dict:
        """Execute a key combination (e.g. 'ctrl', 'c')."""
        pass


class IONavigator(MouseNavigator, KeyboardNavigator, ABC):
    """Unified abstract base class combining mouse and keyboard navigation."""
    pass


# ===========================================================================
# Factory and Global Dispatcher
# ===========================================================================

_io_navigator_instance: IONavigator | None = None


def get_io_navigator() -> IONavigator:
    """Return the IONavigator instance appropriate for the current OS."""
    global _io_navigator_instance
    if _io_navigator_instance is None:
        os_name = platform.system().lower()
        if os_name == "windows":
            from modules.tools.io.windows import WindowsIONavigator
            _io_navigator_instance = WindowsIONavigator()
        elif os_name == "linux":
            from modules.tools.io.linux import LinuxIONavigator
            _io_navigator_instance = LinuxIONavigator()
        else:
            raise NotImplementedError(
                f"IO navigation is not supported on {platform.system()}"
            )
    return _io_navigator_instance


def get_mouse_navigator() -> MouseNavigator:
    """Return the MouseNavigator instance appropriate for the current OS."""
    return get_io_navigator()


def get_keyboard_navigator() -> KeyboardNavigator:
    """Return the KeyboardNavigator instance appropriate for the current OS."""
    return get_io_navigator()


# ===========================================================================
# Exported Tool Functions
# ===========================================================================

def mouse_move(x: int, y: int) -> dict:
    """Move mouse pointer to coordinates (x, y)."""
    return get_io_navigator().move(x, y)


def mouse_click(x: int | None = None, y: int | None = None, button: str = "left") -> dict:
    """Click mouse button at current position or specified coordinates (x, y)."""
    return get_io_navigator().click(x, y, button=button)


def mouse_double_click(x: int | None = None, y: int | None = None, button: str = "left") -> dict:
    """Double-click mouse button at current position or specified coordinates (x, y)."""
    return get_io_navigator().double_click(x, y, button=button)


def mouse_select(start_x: int, start_y: int, end_x: int, end_y: int) -> dict:
    """Click and drag to select an area from (start_x, start_y) to (end_x, end_y)."""
    return get_io_navigator().select(start_x, start_y, end_x, end_y)


def keyboard_type_text(text: str) -> dict:
    """Type text into the currently focused application."""
    return get_io_navigator().type_text(text)


def keyboard_press_key(key: str) -> dict:
    """Press a specific keyboard key."""
    return get_io_navigator().press_key(key)


def keyboard_hotkey(*keys: str) -> dict:
    """Execute a keyboard shortcut."""
    return get_io_navigator().hotkey(*keys)


# Apply needle decorators if needle is available
if _HAS_NEEDLE:
    mouse_move = needle.tool(mouse_move)
    mouse_click = needle.tool(mouse_click)
    mouse_double_click = needle.tool(mouse_double_click)
    mouse_select = needle.tool(mouse_select)
    keyboard_type_text = needle.tool(keyboard_type_text)
    keyboard_press_key = needle.tool(keyboard_press_key)
    keyboard_hotkey = needle.tool(keyboard_hotkey)
