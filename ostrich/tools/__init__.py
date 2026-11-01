"""
Desktop & System Tools Collection
=================================
A cross-platform collection of tools for interacting with the desktop environment.
Delegates to modular subpackages:
- ui_tools: Desktop window navigation (Windows / Linux)
- mouse_tools: Mouse movement, clicking, and selecting (Windows / Linux)
- keyboard_tools: Keyboard typing and shortcuts (Windows / Linux)
- system_tools: System environment inspection & controls (Windows / Linux)
- file_tools: Filesystem interaction (Windows / Linux)
"""

from modules.tools.window import (
    DesktopNavigator,
    WindowsDesktopNavigator,
    LinuxDesktopNavigator,
    get_desktop_navigator,
    open_app,
    list_windows,
    switch_window,
    maximize_window,
    minimize_window,
    split_screen,
)
from ostrich.tools.mouse_tools import (
    MouseNavigator,
    WindowsMouseNavigator,
    LinuxMouseNavigator,
    get_mouse_navigator,
    mouse_move,
    mouse_click,
    mouse_double_click,
    mouse_select,
)
from ostrich.tools.keyboard_tools import (
    KeyboardNavigator,
    WindowsKeyboardNavigator,
    LinuxKeyboardNavigator,
    get_keyboard_navigator,
)
from modules.tools.system import (
    SystemNavigator,
    WindowsSystemNavigator,
    LinuxSystemNavigator,
    get_system_navigator,
    get_system_info,
    get_volume,
    set_volume,
    set_mute,
    mute_volume,
    get_brightness,
    set_brightness,
    get_wifi_status,
    set_wifi,
    scan_wifi,
    connect_wifi,
    disconnect_wifi,
    get_bluetooth_status,
    set_bluetooth,
    get_battery_status,
    lock_screen,
)
from modules.tools.file import (
    FileNavigator,
    WindowsFileNavigator,
    LinuxFileNavigator,
    get_file_navigator,
)

__all__ = [
    # UI Tools
    "DesktopNavigator",
    "WindowsDesktopNavigator",
    "LinuxDesktopNavigator",
    "get_desktop_navigator",
    "open_app",
    "list_windows",
    "switch_window",
    "maximize_window",
    "minimize_window",
    "split_screen",
    # Mouse Tools
    "MouseNavigator",
    "WindowsMouseNavigator",
    "LinuxMouseNavigator",
    "get_mouse_navigator",
    "mouse_move",
    "mouse_click",
    "mouse_double_click",
    "mouse_select",
    # Keyboard Tools
    "KeyboardNavigator",
    "WindowsKeyboardNavigator",
    "LinuxKeyboardNavigator",
    "get_keyboard_navigator",
    # System Tools
    "SystemNavigator",
    "WindowsSystemNavigator",
    "LinuxSystemNavigator",
    "get_system_navigator",
    "get_system_info",
    "get_volume",
    "set_volume",
    "set_mute",
    "mute_volume",
    "get_brightness",
    "set_brightness",
    "get_wifi_status",
    "set_wifi",
    "scan_wifi",
    "connect_wifi",
    "disconnect_wifi",
    "get_bluetooth_status",
    "set_bluetooth",
    "get_battery_status",
    "lock_screen",
    # File Tools
    "FileNavigator",
    "WindowsFileNavigator",
    "LinuxFileNavigator",
    "get_file_navigator",
]
