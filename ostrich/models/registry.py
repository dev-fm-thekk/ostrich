import needle

from modules.tools.window import (
    open_app,
    list_windows,
    switch_window,
    maximize_window,
    minimize_window,
    split_screen,
)
from modules.tools.io import (
    mouse_move,
    mouse_click,
    mouse_double_click,
    mouse_select,
)
from modules.tools.system import (
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

# UI / Window management tools
ui_tools = [
    open_app,
    list_windows,
    switch_window,
    maximize_window,
    minimize_window,
    split_screen,
]

# Mouse interaction tools
mouse_tools = [
    mouse_move,
    mouse_click,
    mouse_double_click,
    mouse_select,
]

# System control & inspection tools
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

# Combined default tool suite
tools = ui_tools + mouse_tools + system_tools


def load_needle_model(custom_tools=None):
    """Initialize a Needle model loaded with tools."""
    active_tools = custom_tools if custom_tools is not None else tools
    return needle.Needle(
        tools=active_tools,
        stateless=True,
    )
