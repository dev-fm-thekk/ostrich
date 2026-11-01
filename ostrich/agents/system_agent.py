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

import needle


tools = [
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


def get_system_agent():
    return needle.Needle(tools=tools)
