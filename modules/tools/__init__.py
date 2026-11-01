"""
Desktop & System Tools Collection
=================================
A cross-platform collection of modular tools for interacting with the desktop environment:
- window: Desktop application and window navigation (Windows / Linux)
- io: Unified input/output interaction including mouse and keyboard (Windows / Linux)
- system: System environment inspection & controls (Windows / Linux)
- file: Filesystem navigation and directory operations (Windows / Linux)
"""

# Window / UI Tools
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

# IO Tools (Mouse and Keyboard)
from modules.tools.io import (
    IONavigator,
    WindowsIONavigator,
    LinuxIONavigator,
    get_io_navigator,
    MouseNavigator,
    WindowsMouseNavigator,
    LinuxMouseNavigator,
    get_mouse_navigator,
    KeyboardNavigator,
    WindowsKeyboardNavigator,
    LinuxKeyboardNavigator,
    get_keyboard_navigator,
    mouse_move,
    mouse_click,
    mouse_double_click,
    mouse_select,
    keyboard_type_text,
    keyboard_press_key,
    keyboard_hotkey,
)

# System Tools
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

# File Tools
from modules.tools.file import (
    FileNavigator,
    WindowsFileNavigator,
    LinuxFileNavigator,
    get_file_navigator,
    list_files,
)

# Tool suites
window_tools = [
    open_app,
    list_windows,
    switch_window,
    maximize_window,
    minimize_window,
    split_screen,
]

mouse_tools = [
    mouse_move,
    mouse_click,
    mouse_double_click,
    mouse_select,
]

keyboard_tools = [
    keyboard_type_text,
    keyboard_press_key,
    keyboard_hotkey,
]

io_tools = mouse_tools + keyboard_tools

system_tools = [
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
]

file_tools = [
    list_files,
]

all_tools = window_tools + io_tools + system_tools + file_tools

__all__ = [
    # Window Tools
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
    # IO Tools
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
    "mouse_move",
    "mouse_click",
    "mouse_double_click",
    "mouse_select",
    "keyboard_type_text",
    "keyboard_press_key",
    "keyboard_hotkey",
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
    "list_files",
    # Tool Collections
    "window_tools",
    "mouse_tools",
    "keyboard_tools",
    "io_tools",
    "system_tools",
    "file_tools",
    "all_tools",
]
