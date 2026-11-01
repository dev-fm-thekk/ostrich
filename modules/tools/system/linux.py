"""
Linux System Navigator
======================
Implementation of SystemNavigator for Linux.
Provides system controls:
- Audio volume & mute (wpctl, pactl, amixer)
- Display brightness (gdbus GNOME, brightnessctl, sysfs, xrandr)
- Wi-Fi status, toggle, scan, connect, disconnect (nmcli, rfkill)
- Bluetooth status & toggle (bluetoothctl, rfkill)
- Battery & power status (sysfs /sys/class/power_supply, upower)
- System information & resource inspection (procfs, shutil, platform)
- Lock screen (loginctl, xdg-screensaver)
"""

from __future__ import annotations

import glob
import os
import platform
import re
import shutil
import subprocess

try:
    from modules.tools.system.base import SystemNavigator
except ImportError:
    from modules.tools.system.base import SystemNavigator


class LinuxSystemNavigator(SystemNavigator):
    """Linux implementation of SystemNavigator."""

    # -----------------------------------------------------------------------
    # System Information & Resources
    # -----------------------------------------------------------------------

    def get_system_info(self) -> dict:
        """Retrieve system details (OS, CPU, memory, disk, hostname)."""
        mem_info: dict[str, int] = {}
        if os.path.exists("/proc/meminfo"):
            try:
                with open("/proc/meminfo", "r") as f:
                    for line in f:
                        parts = line.split(":")
                        if len(parts) == 2:
                            key = parts[0].strip()
                            val_str = parts[1].strip().split()[0]
                            if val_str.isdigit():
                                mem_info[key] = int(val_str)  # in kB
            except Exception:
                pass

        total_kb = mem_info.get("MemTotal", 0)
        avail_kb = mem_info.get("MemAvailable", mem_info.get("MemFree", 0))
        used_kb = max(0, total_kb - avail_kb)

        disk = shutil.disk_usage("/")

        return {
            "success": True,
            "os": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "hostname": platform.node(),
            "cpu_count": os.cpu_count(),
            "memory": {
                "total_mb": round(total_kb / 1024, 1) if total_kb else None,
                "available_mb": round(avail_kb / 1024, 1) if total_kb else None,
                "used_mb": round(used_kb / 1024, 1) if total_kb else None,
                "percent_used": round((used_kb / total_kb) * 100, 1) if total_kb else None,
            },
            "disk": {
                "total_gb": round(disk.total / (1024**3), 2),
                "used_gb": round(disk.used / (1024**3), 2),
                "free_gb": round(disk.free / (1024**3), 2),
                "percent_used": round((disk.used / disk.total) * 100, 1),
            },
        }

    # -----------------------------------------------------------------------
    # Audio Volume & Mute Controls
    # -----------------------------------------------------------------------

    def get_volume(self) -> dict:
        """Get current master audio volume level (0-100) and mute state."""
        # 1. Try wpctl (PipeWire)
        try:
            res = subprocess.run(
                ["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            if res.returncode == 0 and res.stdout:
                m = re.search(r"Volume:\s+([0-9.]+)", res.stdout)
                if m:
                    vol = int(round(float(m.group(1)) * 100))
                    muted = "[MUTED]" in res.stdout
                    return {"success": True, "volume": vol, "muted": muted}
        except Exception:
            pass

        # 2. Try pactl (PulseAudio)
        try:
            vol_res = subprocess.run(
                ["pactl", "get-sink-volume", "@DEFAULT_SINK@"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            mute_res = subprocess.run(
                ["pactl", "get-sink-mute", "@DEFAULT_SINK@"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            if vol_res.returncode == 0:
                m_vol = re.search(r"/\s*([0-9]+)%\s*/", vol_res.stdout)
                muted = "yes" in mute_res.stdout.lower()
                if m_vol:
                    return {"success": True, "volume": int(m_vol.group(1)), "muted": muted}
        except Exception:
            pass

        # 3. Try amixer (ALSA)
        try:
            res = subprocess.run(
                ["amixer", "sget", "Master"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            if res.returncode == 0:
                m_vol = re.search(r"\[([0-9]+)%\]", res.stdout)
                m_mute = re.search(r"\[(on|off)\]", res.stdout)
                vol = int(m_vol.group(1)) if m_vol else None
                muted = (m_mute.group(1) == "off") if m_mute else False
                if vol is not None:
                    return {"success": True, "volume": vol, "muted": muted}
        except Exception:
            pass

        return {"success": False, "error": "No supported audio subsystem found (wpctl, pactl, amixer)."}

    def set_volume(self, level: int) -> dict:
        """Set master audio volume level (clamped 0-100)."""
        level = max(0, min(100, int(level)))

        # 1. Try wpctl (PipeWire)
        try:
            res = subprocess.run(
                ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{level / 100:.2f}"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            if res.returncode == 0:
                return {"success": True, "volume": level, "message": f"Volume set to {level}%."}
        except Exception:
            pass

        # 2. Try pactl (PulseAudio)
        try:
            res = subprocess.run(
                ["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{level}%"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            if res.returncode == 0:
                return {"success": True, "volume": level, "message": f"Volume set to {level}%."}
        except Exception:
            pass

        # 3. Try amixer (ALSA)
        try:
            res = subprocess.run(
                ["amixer", "sset", "Master", f"{level}%"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            if res.returncode == 0:
                return {"success": True, "volume": level, "message": f"Volume set to {level}%."}
        except Exception:
            pass

        return {"success": False, "error": f"Failed to set volume to {level}%."}

    def set_mute(self, mute: bool | None = None) -> dict:
        """Mute, unmute, or toggle mute state of master audio."""
        # 1. Try wpctl
        try:
            if mute is None:
                arg = "toggle"
            else:
                arg = "1" if mute else "0"
            res = subprocess.run(
                ["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", arg],
                capture_output=True,
                text=True,
                timeout=2,
            )
            if res.returncode == 0:
                cur = self.get_volume()
                return {
                    "success": True,
                    "muted": cur.get("muted"),
                    "message": f"Mute state set to {cur.get('muted')}.",
                }
        except Exception:
            pass

        # 2. Try pactl
        try:
            if mute is None:
                arg = "toggle"
            else:
                arg = "1" if mute else "0"
            res = subprocess.run(
                ["pactl", "set-sink-mute", "@DEFAULT_SINK@", arg],
                capture_output=True,
                text=True,
                timeout=2,
            )
            if res.returncode == 0:
                cur = self.get_volume()
                return {
                    "success": True,
                    "muted": cur.get("muted"),
                    "message": f"Mute state set to {cur.get('muted')}.",
                }
        except Exception:
            pass

        # 3. Try amixer
        try:
            if mute is None:
                arg = "toggle"
            else:
                arg = "mute" if mute else "unmute"
            res = subprocess.run(
                ["amixer", "sset", "Master", arg],
                capture_output=True,
                text=True,
                timeout=2,
            )
            if res.returncode == 0:
                cur = self.get_volume()
                return {
                    "success": True,
                    "muted": cur.get("muted"),
                    "message": f"Mute state set to {cur.get('muted')}.",
                }
        except Exception:
            pass

        return {"success": False, "error": "Failed to set mute state."}

    # -----------------------------------------------------------------------
    # Display Brightness Controls
    # -----------------------------------------------------------------------

    def get_brightness(self) -> dict:
        """Get current display brightness percentage (0-100)."""
        # 1. Try gdbus (GNOME SettingsDaemon)
        try:
            res = subprocess.run(
                [
                    "gdbus",
                    "call",
                    "--session",
                    "--dest",
                    "org.gnome.SettingsDaemon.Power",
                    "--object-path",
                    "/org/gnome/SettingsDaemon/Power",
                    "--method",
                    "org.freedesktop.DBus.Properties.Get",
                    "org.gnome.SettingsDaemon.Power.Screen",
                    "Brightness",
                ],
                capture_output=True,
                text=True,
                timeout=2,
            )
            m = re.search(r"<\s*([0-9]+)\s*>", res.stdout)
            if m:
                return {"success": True, "brightness": int(m.group(1))}
        except Exception:
            pass

        # 2. Try brightnessctl
        try:
            res_val = subprocess.run(["brightnessctl", "g"], capture_output=True, text=True, timeout=2)
            res_max = subprocess.run(["brightnessctl", "m"], capture_output=True, text=True, timeout=2)
            if res_val.returncode == 0 and res_max.returncode == 0:
                val = int(res_val.stdout.strip())
                mx = int(res_max.stdout.strip())
                if mx > 0:
                    return {"success": True, "brightness": int(round(val / mx * 100))}
        except Exception:
            pass

        # 3. Try sysfs /sys/class/backlight
        for b_path in glob.glob("/sys/class/backlight/*"):
            try:
                with open(os.path.join(b_path, "brightness"), "r") as f:
                    cur = int(f.read().strip())
                with open(os.path.join(b_path, "max_brightness"), "r") as f:
                    mx = int(f.read().strip())
                if mx > 0:
                    return {"success": True, "brightness": int(round(cur / mx * 100))}
            except Exception:
                pass

        return {"success": False, "error": "Unable to determine display brightness."}

    def set_brightness(self, level: int) -> dict:
        """Set display brightness percentage (clamped 0-100)."""
        level = max(0, min(100, int(level)))

        # 1. Try gdbus (GNOME)
        try:
            res = subprocess.run(
                [
                    "gdbus",
                    "call",
                    "--session",
                    "--dest",
                    "org.gnome.SettingsDaemon.Power",
                    "--object-path",
                    "/org/gnome/SettingsDaemon/Power",
                    "--method",
                    "org.freedesktop.DBus.Properties.Set",
                    "org.gnome.SettingsDaemon.Power.Screen",
                    "Brightness",
                    f"<int32 {level}>",
                ],
                capture_output=True,
                text=True,
                timeout=2,
            )
            if res.returncode == 0:
                return {"success": True, "brightness": level, "message": f"Brightness set to {level}%."}
        except Exception:
            pass

        # 2. Try brightnessctl
        try:
            res = subprocess.run(
                ["brightnessctl", "s", f"{level}%"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            if res.returncode == 0:
                return {"success": True, "brightness": level, "message": f"Brightness set to {level}%."}
        except Exception:
            pass

        # 3. Try xrandr fallback
        try:
            xr_res = subprocess.run(["xrandr", "--verbose"], capture_output=True, text=True, timeout=2)
            for line in xr_res.stdout.splitlines():
                if " connected " in line:
                    disp = line.split()[0]
                    # xrandr brightness is 0.0 - 1.0 (float)
                    val = max(0.1, level / 100.0)
                    subprocess.run(
                        ["xrandr", "--output", disp, "--brightness", str(val)],
                        capture_output=True,
                        timeout=2,
                    )
                    return {"success": True, "brightness": level, "message": f"Brightness set to {level}% via xrandr."}
        except Exception:
            pass

        return {"success": False, "error": f"Failed to set brightness to {level}%."}

    # -----------------------------------------------------------------------
    # Wi-Fi Controls
    # -----------------------------------------------------------------------

    def get_wifi_status(self) -> dict:
        """Get Wi-Fi status (enabled, connected, SSID, signal strength, device)."""
        enabled = False
        # Check enabled state
        try:
            res = subprocess.run(["nmcli", "-t", "-f", "WIFI", "g"], capture_output=True, text=True, timeout=2)
            if res.returncode == 0:
                enabled = (res.stdout.strip().lower() == "enabled")
        except Exception:
            # Fallback to rfkill
            try:
                res = subprocess.run(["rfkill", "list", "wifi"], capture_output=True, text=True, timeout=2)
                enabled = ("Soft blocked: no" in res.stdout and "Hard blocked: no" in res.stdout)
            except Exception:
                pass

        connected = False
        ssid = None
        signal = None
        device = None

        if enabled:
            try:
                res = subprocess.run(
                    ["nmcli", "-t", "-f", "in-use,ssid,signal,device", "dev", "wifi"],
                    capture_output=True,
                    text=True,
                    timeout=3,
                )
                if res.returncode == 0:
                    for line in res.stdout.splitlines():
                        if line.startswith("*"):
                            # Format: *:SSID:SIGNAL:DEVICE
                            parts = line[2:].split(":")
                            if parts:
                                connected = True
                                ssid = parts[0].replace("\\:", ":")
                                signal = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None
                                device = parts[2] if len(parts) > 2 else None
                            break
            except Exception:
                pass

        return {
            "success": True,
            "enabled": enabled,
            "connected": connected,
            "ssid": ssid,
            "signal": signal,
            "device": device,
        }

    def set_wifi(self, enabled: bool) -> dict:
        """Turn Wi-Fi radio on or off."""
        arg = "on" if enabled else "off"
        # 1. Try nmcli
        try:
            res = subprocess.run(["nmcli", "radio", "wifi", arg], capture_output=True, text=True, timeout=5)
            if res.returncode == 0:
                return {
                    "success": True,
                    "enabled": enabled,
                    "message": f"Wi-Fi turned {arg}.",
                }
        except Exception:
            pass

        # 2. Try rfkill fallback
        try:
            rf_cmd = ["rfkill", "unblock" if enabled else "block", "wifi"]
            res = subprocess.run(rf_cmd, capture_output=True, text=True, timeout=5)
            if res.returncode == 0:
                return {
                    "success": True,
                    "enabled": enabled,
                    "message": f"Wi-Fi turned {arg} via rfkill.",
                }
        except Exception:
            pass

        return {"success": False, "error": f"Failed to turn Wi-Fi {arg}."}

    def scan_wifi(self) -> dict:
        """Scan and list available Wi-Fi networks."""
        networks: list[dict] = []
        try:
            # Trigger rescan
            subprocess.run(["nmcli", "dev", "wifi", "rescan"], capture_output=True, timeout=5)
            res = subprocess.run(
                ["nmcli", "-t", "-f", "in-use,ssid,signal,security", "dev", "wifi", "list"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            seen_ssids: set[str] = set()
            for line in res.stdout.splitlines():
                in_use = line.startswith("*")
                content = line[2:] if line.startswith(("*", " ")) else line
                parts = content.split(":")
                if parts and parts[0]:
                    net_ssid = parts[0].replace("\\:", ":")
                    if net_ssid not in seen_ssids:
                        seen_ssids.add(net_ssid)
                        sig = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None
                        sec = parts[2] if len(parts) > 2 else ""
                        networks.append({
                            "ssid": net_ssid,
                            "signal": sig,
                            "security": sec,
                            "connected": in_use,
                        })
            return {"success": True, "networks": networks, "count": len(networks)}
        except Exception as exc:
            return {"success": False, "error": f"Wi-Fi scan failed: {exc}"}

    def connect_wifi(self, ssid: str, password: str | None = None) -> dict:
        """Connect to a Wi-Fi network by SSID."""
        cmd = ["nmcli", "dev", "wifi", "connect", ssid]
        if password:
            cmd.extend(["password", password])
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if res.returncode == 0:
                return {"success": True, "ssid": ssid, "message": f"Connected to Wi-Fi '{ssid}'."}
            return {
                "success": False,
                "error": res.stderr.strip() or res.stdout.strip() or "Connection failed.",
            }
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    def disconnect_wifi(self) -> dict:
        """Disconnect from the currently connected Wi-Fi network."""
        status = self.get_wifi_status()
        device = status.get("device")
        try:
            if device:
                cmd = ["nmcli", "dev", "disconnect", device]
            else:
                cmd = ["nmcli", "dev", "disconnect", "wlan0"]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            if res.returncode == 0:
                return {"success": True, "message": "Disconnected from Wi-Fi."}
            return {"success": False, "error": res.stderr.strip() or "Disconnect failed."}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    # -----------------------------------------------------------------------
    # Bluetooth Controls
    # -----------------------------------------------------------------------

    def get_bluetooth_status(self) -> dict:
        """Get Bluetooth status (enabled, connected devices)."""
        enabled = False
        try:
            res = subprocess.run(["bluetoothctl", "show"], capture_output=True, text=True, timeout=2)
            if re.search(r"Powered:\s+yes", res.stdout, re.IGNORECASE):
                enabled = True
        except Exception:
            try:
                res = subprocess.run(["rfkill", "list", "bluetooth"], capture_output=True, text=True, timeout=2)
                enabled = ("Soft blocked: no" in res.stdout and "Hard blocked: no" in res.stdout)
            except Exception:
                pass

        connected_devices: list[dict] = []
        if enabled:
            try:
                res = subprocess.run(
                    ["bluetoothctl", "devices", "Connected"],
                    capture_output=True,
                    text=True,
                    timeout=2,
                )
                if res.returncode == 0:
                    for line in res.stdout.splitlines():
                        m = re.match(r"Device\s+([0-9A-Fa-f:]+)\s+(.+)", line.strip())
                        if m:
                            connected_devices.append({"mac": m.group(1), "name": m.group(2)})
            except Exception:
                pass

        return {
            "success": True,
            "enabled": enabled,
            "connected_devices": connected_devices,
        }

    def set_bluetooth(self, enabled: bool) -> dict:
        """Turn Bluetooth radio on or off."""
        arg = "on" if enabled else "off"
        # 1. Try bluetoothctl
        try:
            res = subprocess.run(["bluetoothctl", "power", arg], capture_output=True, text=True, timeout=5)
            if res.returncode == 0:
                return {
                    "success": True,
                    "enabled": enabled,
                    "message": f"Bluetooth powered {arg}.",
                }
        except Exception:
            pass

        # 2. Try rfkill fallback
        try:
            rf_cmd = ["rfkill", "unblock" if enabled else "block", "bluetooth"]
            res = subprocess.run(rf_cmd, capture_output=True, text=True, timeout=5)
            if res.returncode == 0:
                return {
                    "success": True,
                    "enabled": enabled,
                    "message": f"Bluetooth set {arg} via rfkill.",
                }
        except Exception:
            pass

        return {"success": False, "error": f"Failed to turn Bluetooth {arg}."}

    # -----------------------------------------------------------------------
    # Battery & Power Controls
    # -----------------------------------------------------------------------

    def get_battery_status(self) -> dict:
        """Get battery percentage, charging state, and power source."""
        battery_paths = glob.glob("/sys/class/power_supply/BAT*")
        ac_paths = glob.glob("/sys/class/power_supply/AC*") + glob.glob("/sys/class/power_supply/ADP*")

        plugged = False
        for ac in ac_paths:
            try:
                with open(os.path.join(ac, "online"), "r") as f:
                    if f.read().strip() == "1":
                        plugged = True
                        break
            except Exception:
                pass

        if not battery_paths:
            # Desktop system without battery
            return {
                "success": True,
                "has_battery": False,
                "percent": None,
                "status": "AC Power",
                "charging": False,
                "power_plugged": plugged or True,
            }

        bat = battery_paths[0]
        percent = None
        status = "Unknown"
        try:
            with open(os.path.join(bat, "capacity"), "r") as f:
                percent = int(f.read().strip())
        except Exception:
            pass

        try:
            with open(os.path.join(bat, "status"), "r") as f:
                status = f.read().strip()
        except Exception:
            pass

        charging = (status.lower() == "charging")

        return {
            "success": True,
            "has_battery": True,
            "percent": percent,
            "status": status,
            "charging": charging,
            "power_plugged": plugged or charging,
        }

    # -----------------------------------------------------------------------
    # System Session Controls
    # -----------------------------------------------------------------------

    def lock_screen(self) -> dict:
        """Lock the current desktop user session."""
        for cmd in [
            ["loginctl", "lock-session"],
            ["xdg-screensaver", "lock"],
            ["gnome-screensaver-command", "-l"],
        ]:
            try:
                res = subprocess.run(cmd, capture_output=True, timeout=2)
                if res.returncode == 0:
                    return {"success": True, "message": "Screen locked successfully."}
            except Exception:
                continue
        return {"success": False, "error": "Unable to lock screen (no supported screen locker found)."}
