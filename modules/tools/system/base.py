"""
System Tools - Base Interface
=============================
Abstract base class and unified interface for system-level controls:
- Audio volume & mute
- Display brightness
- Wi-Fi status, toggle, scan, connect, disconnect
- Bluetooth status & toggle
- Battery & power status
- System information & hardware resources
- Lock screen
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


class SystemNavigator(ABC):
    """Abstract base class defining system interaction interfaces."""

    # -----------------------------------------------------------------------
    # System Information & Hardware Resources
    # -----------------------------------------------------------------------

    @abstractmethod
    def get_system_info(self) -> dict:
        """Retrieve system details (OS, CPU, memory, disk, hostname)."""
        pass

    # -----------------------------------------------------------------------
    # Audio Volume & Mute Controls
    # -----------------------------------------------------------------------

    @abstractmethod
    def get_volume(self) -> dict:
        """Get current master audio volume level (0-100) and mute state."""
        pass

    @abstractmethod
    def set_volume(self, level: int) -> dict:
        """Set master audio volume level (0-100)."""
        pass

    @abstractmethod
    def set_mute(self, mute: bool | None = None) -> dict:
        """Mute, unmute, or toggle mute state of master audio."""
        pass

    def mute_volume(self, mute: bool | None = None) -> dict:
        """Convenience alias for set_mute."""
        return self.set_mute(mute)

    # -----------------------------------------------------------------------
    # Display Brightness Controls
    # -----------------------------------------------------------------------

    @abstractmethod
    def get_brightness(self) -> dict:
        """Get current display brightness percentage (0-100)."""
        pass

    @abstractmethod
    def set_brightness(self, level: int) -> dict:
        """Set display brightness percentage (0-100)."""
        pass

    # -----------------------------------------------------------------------
    # Wi-Fi Controls
    # -----------------------------------------------------------------------

    @abstractmethod
    def get_wifi_status(self) -> dict:
        """Get Wi-Fi status (enabled, connected, SSID, signal strength)."""
        pass

    @abstractmethod
    def set_wifi(self, enabled: bool) -> dict:
        """Turn Wi-Fi radio on or off."""
        pass

    @abstractmethod
    def scan_wifi(self) -> dict:
        """Scan and list available Wi-Fi networks."""
        pass

    @abstractmethod
    def connect_wifi(self, ssid: str, password: str | None = None) -> dict:
        """Connect to a Wi-Fi network by SSID."""
        pass

    @abstractmethod
    def disconnect_wifi(self) -> dict:
        """Disconnect from the currently connected Wi-Fi network."""
        pass

    # -----------------------------------------------------------------------
    # Bluetooth Controls
    # -----------------------------------------------------------------------

    @abstractmethod
    def get_bluetooth_status(self) -> dict:
        """Get Bluetooth status (enabled, connected devices)."""
        pass

    @abstractmethod
    def set_bluetooth(self, enabled: bool) -> dict:
        """Turn Bluetooth radio on or off."""
        pass

    # -----------------------------------------------------------------------
    # Battery & Power Controls
    # -----------------------------------------------------------------------

    @abstractmethod
    def get_battery_status(self) -> dict:
        """Get battery percentage, charging state, and power source."""
        pass

    # -----------------------------------------------------------------------
    # System Session Controls
    # -----------------------------------------------------------------------

    @abstractmethod
    def lock_screen(self) -> dict:
        """Lock the current user desktop session."""
        pass


# Platform-specific implementations
try:
    from modules.tools.system.windows import WindowsSystemNavigator
except ImportError:
    WindowsSystemNavigator = None  # type: ignore

try:
    from modules.tools.system.linux import LinuxSystemNavigator
except ImportError:
    LinuxSystemNavigator = None  # type: ignore


_system_navigator_instance: SystemNavigator | None = None


def get_system_navigator() -> SystemNavigator:
    """Return the SystemNavigator instance appropriate for the current OS."""
    global _system_navigator_instance
    if _system_navigator_instance is None:
        if platform.system().lower() == "windows":
            if WindowsSystemNavigator is None:
                raise NotImplementedError("Windows System navigator is not available.")
            _system_navigator_instance = WindowsSystemNavigator()
        else:
            if LinuxSystemNavigator is None:
                raise NotImplementedError("Linux System navigator is not available.")
            _system_navigator_instance = LinuxSystemNavigator()
    return _system_navigator_instance


# ===========================================================================
# Tool Functions (Exported tools compatible with agent execution)
# ===========================================================================

def get_system_info() -> dict:
    """Retrieve detailed system information including OS, CPU count, memory usage, and disk space."""
    return get_system_navigator().get_system_info()


def get_volume() -> dict:
    """Get the current master audio volume level (0-100) and mute status."""
    return get_system_navigator().get_volume()


def set_volume(level: int) -> dict:
    """Set the master audio volume level (0-100)."""
    return get_system_navigator().set_volume(level)


def set_mute(mute: bool | None = None) -> dict:
    """Mute (True), unmute (False), or toggle (None) the master audio mute state."""
    return get_system_navigator().set_mute(mute)


def mute_volume(mute: bool | None = None) -> dict:
    """Mute (True), unmute (False), or toggle (None) master audio mute state."""
    return get_system_navigator().set_mute(mute)


def get_brightness() -> dict:
    """Get the current display brightness level as a percentage (0-100)."""
    return get_system_navigator().get_brightness()


def set_brightness(level: int) -> dict:
    """Set the display brightness level as a percentage (0-100)."""
    return get_system_navigator().set_brightness(level)


def get_wifi_status() -> dict:
    """Get Wi-Fi radio status, connection state, SSID, and signal strength."""
    return get_system_navigator().get_wifi_status()


def set_wifi(enabled: bool) -> dict:
    """Turn the Wi-Fi radio on (True) or off (False)."""
    return get_system_navigator().set_wifi(enabled)


def scan_wifi() -> dict:
    """Scan and return a list of available Wi-Fi networks in range."""
    return get_system_navigator().scan_wifi()


def connect_wifi(ssid: str, password: str | None = None) -> dict:
    """Connect to a Wi-Fi network by SSID with an optional password."""
    return get_system_navigator().connect_wifi(ssid, password=password)


def disconnect_wifi() -> dict:
    """Disconnect from the currently connected Wi-Fi network."""
    return get_system_navigator().disconnect_wifi()


def get_bluetooth_status() -> dict:
    """Get Bluetooth radio power status and a list of connected devices."""
    return get_system_navigator().get_bluetooth_status()


def set_bluetooth(enabled: bool) -> dict:
    """Turn the Bluetooth radio on (True) or off (False)."""
    return get_system_navigator().set_bluetooth(enabled)


def get_battery_status() -> dict:
    """Get current battery percentage, charging status, and power connection state."""
    return get_system_navigator().get_battery_status()


def lock_screen() -> dict:
    """Lock the current desktop session immediately."""
    return get_system_navigator().lock_screen()


# Apply needle decorators if needle is available
if _HAS_NEEDLE:
    get_system_info = needle.tool(get_system_info)
    get_volume = needle.tool(get_volume)
    set_volume = needle.tool(set_volume)
    set_mute = needle.tool(set_mute)
    mute_volume = needle.tool(mute_volume)
    get_brightness = needle.tool(get_brightness)
    set_brightness = needle.tool(set_brightness)
    get_wifi_status = needle.tool(get_wifi_status)
    set_wifi = needle.tool(set_wifi)
    scan_wifi = needle.tool(scan_wifi)
    connect_wifi = needle.tool(connect_wifi)
    disconnect_wifi = needle.tool(disconnect_wifi)
    get_bluetooth_status = needle.tool(get_bluetooth_status)
    set_bluetooth = needle.tool(set_bluetooth)
    get_battery_status = needle.tool(get_battery_status)
    lock_screen = needle.tool(lock_screen)
