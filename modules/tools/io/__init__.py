"""
IO Tools Module
===============
Unified mouse and keyboard interaction capabilities for Windows and Linux.
"""

from modules.tools.io.base import (
    IONavigator,
    KeyboardNavigator,
    MouseNavigator,
    get_io_navigator,
    get_keyboard_navigator,
    get_mouse_navigator,
    keyboard_hotkey,
    keyboard_press_key,
    keyboard_type_text,
    mouse_click,
    mouse_double_click,
    mouse_move,
    mouse_select,
)

try:
    from modules.tools.io.windows import (
        WindowsIONavigator,
        WindowsKeyboardNavigator,
        WindowsMouseNavigator,
    )
except ImportError:
    WindowsIONavigator = None  # type: ignore
    WindowsKeyboardNavigator = None  # type: ignore
    WindowsMouseNavigator = None  # type: ignore

try:
    from modules.tools.io.linux import (
        LinuxIONavigator,
        LinuxKeyboardNavigator,
        LinuxMouseNavigator,
    )
except ImportError:
    LinuxIONavigator = None  # type: ignore
    LinuxKeyboardNavigator = None  # type: ignore
    LinuxMouseNavigator = None  # type: ignore

__all__ = [
    # Base and unified navigators
    "IONavigator",
    "WindowsIONavigator",
    "LinuxIONavigator",
    "get_io_navigator",
    "MouseNavigator",
    "WindowsMouseNavigator",
    "LinuxMouseNavigator",
    "get_mouse_navigator",
    "KeyboardNavigator",
    "WindowsKeyboardNavigator",
    "LinuxKeyboardNavigator",
    "get_keyboard_navigator",
    # Mouse tools
    "mouse_move",
    "mouse_click",
    "mouse_double_click",
    "mouse_select",
    # Keyboard tools
    "keyboard_type_text",
    "keyboard_press_key",
    "keyboard_hotkey",
]
