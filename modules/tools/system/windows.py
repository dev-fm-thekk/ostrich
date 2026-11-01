"""
Windows System Navigator
========================
Implementation of SystemNavigator for Windows.
Provides system controls:
- Audio volume & mute (Windows CoreAudio via PowerShell C# compilation, pycaw fallback)
- Display brightness (WMI WmiMonitorBrightness / WmiMonitorBrightnessMethods)
- Wi-Fi status, toggle, scan, connect, disconnect (netsh wlan, PowerShell NetAdapter)
- Bluetooth status & toggle (PowerShell PnpDevice / bthserv)
- Battery & power status (WMI Win32_Battery)
- System information & resource inspection (platform, shutil, WMI Win32_OperatingSystem)
- Lock screen (LockWorkStation)
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess

from modules.tools.system.base import SystemNavigator


class WindowsSystemNavigator(SystemNavigator):
    """Windows implementation of SystemNavigator."""

    def _run_powershell(self, script: str, timeout: int = 5) -> subprocess.CompletedProcess:
        """Run a PowerShell command and return CompletedProcess."""
        cmd = ["powershell", "-NoProfile", "-NonInteractive", "-Command", script]
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)

    # -----------------------------------------------------------------------
    # System Information & Resources
    # -----------------------------------------------------------------------

    def get_system_info(self) -> dict:
        """Retrieve system details (OS, CPU, memory, disk, hostname)."""
        mem_data: dict[str, float | None] = {
            "total_mb": None,
            "available_mb": None,
            "used_mb": None,
            "percent_used": None,
        }
        try:
            ps_script = (
                "Get-CimInstance Win32_OperatingSystem | "
                "Select-Object TotalVisibleMemorySize, FreePhysicalMemory | "
                "ConvertTo-Json"
            )
            res = self._run_powershell(ps_script, timeout=3)
            if res.returncode == 0 and res.stdout:
                import json
                info = json.loads(res.stdout)
                tot_kb = float(info.get("TotalVisibleMemorySize", 0))
                free_kb = float(info.get("FreePhysicalMemory", 0))
                used_kb = max(0.0, tot_kb - free_kb)
                if tot_kb > 0:
                    mem_data = {
                        "total_mb": round(tot_kb / 1024, 1),
                        "available_mb": round(free_kb / 1024, 1),
                        "used_mb": round(used_kb / 1024, 1),
                        "percent_used": round((used_kb / tot_kb) * 100, 1),
                    }
        except Exception:
            pass

        disk_path = os.environ.get("SystemDrive", "C:") + "\\"
        disk = shutil.disk_usage(disk_path)

        return {
            "success": True,
            "os": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "hostname": platform.node(),
            "cpu_count": os.cpu_count(),
            "memory": mem_data,
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

    def _get_audio_helper_cs(self) -> str:
        """C# helper snippet using CoreAudio IAudioEndpointVolume."""
        return """
        Add-Type -TypeDefinition @"
        using System;
        using System.Runtime.InteropServices;
        [Guid("5CDF2C82-841E-4546-9722-0CF74078229A"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
        public interface IAudioEndpointVolume {
            int f(); int g(); int h(); int i();
            int SetMasterVolumeLevelScalar(float fLevel, System.Guid pguidEventContext);
            int j();
            int GetMasterVolumeLevelScalar(out float pfLevel);
            int k(); int l(); int m(); int n();
            int SetMute([MarshalAs(UnmanagedType.Bool)] bool bMute, System.Guid pguidEventContext);
            int GetMute(out bool pbMute);
        }
        [Guid("D666063F-1587-4E43-81F1-B948E807363F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
        public interface IMMDevice {
            int Activate(ref System.Guid id, int clsCtx, int pActivationParams, out IAudioEndpointVolume aev);
        }
        [Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
        public interface IMMDeviceEnumerator {
            int GetDefaultAudioEndpoint(int dataFlow, int role, out IMMDevice endpoint);
        }
        [ComImport, Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")] public class MMDeviceEnumeratorComObject { }
        public class WinAudio {
            private static IAudioEndpointVolume GetVolObj() {
                var enumerator = new MMDeviceEnumeratorComObject() as IMMDeviceEnumerator;
                IMMDevice dev = null;
                enumerator.GetDefaultAudioEndpoint(0, 1, out dev);
                var IID_IAEV = typeof(IAudioEndpointVolume).GUID;
                IAudioEndpointVolume aev = null;
                dev.Activate(ref IID_IAEV, 23, 0, out aev);
                return aev;
            }
            public static float GetVolume() {
                float v = 0;
                GetVolObj().GetMasterVolumeLevelScalar(out v);
                return v;
            }
            public static void SetVolume(float v) {
                GetVolObj().SetMasterVolumeLevelScalar(v, System.Guid.Empty);
            }
            public static bool GetMute() {
                bool m = false;
                GetVolObj().GetMute(out m);
                return m;
            }
            public static void SetMute(bool m) {
                GetVolObj().SetMute(m, System.Guid.Empty);
            }
        }
"@
"""

    def get_volume(self) -> dict:
        """Get current master audio volume level (0-100) and mute state."""
        try:
            cs = self._get_audio_helper_cs()
            script = f"{cs}; [WinAudio]::GetVolume(); [WinAudio]::GetMute()"
            res = self._run_powershell(script, timeout=4)
            if res.returncode == 0:
                lines = [line.strip() for line in res.stdout.splitlines() if line.strip()]
                if len(lines) >= 2:
                    vol_float = float(lines[0])
                    muted = lines[1].lower() == "true"
                    return {"success": True, "volume": int(round(vol_float * 100)), "muted": muted}
        except Exception as exc:
            return {"success": False, "error": f"Failed to retrieve volume: {exc}"}

        return {"success": False, "error": "Unable to query Windows audio endpoint volume."}

    def set_volume(self, level: int) -> dict:
        """Set master audio volume level (clamped 0-100)."""
        level = max(0, min(100, int(level)))
        try:
            cs = self._get_audio_helper_cs()
            val_float = level / 100.0
            script = f"{cs}; [WinAudio]::SetVolume({val_float:f})"
            res = self._run_powershell(script, timeout=4)
            if res.returncode == 0:
                return {"success": True, "volume": level, "message": f"Volume set to {level}%."}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

        return {"success": False, "error": f"Failed to set volume to {level}%."}

    def set_mute(self, mute: bool | None = None) -> dict:
        """Mute, unmute, or toggle mute state of master audio."""
        try:
            cs = self._get_audio_helper_cs()
            if mute is None:
                # Toggle
                script = f"{cs}; $m = -not [WinAudio]::GetMute(); [WinAudio]::SetMute($m); $m"
            else:
                target_bool = "$true" if mute else "$false"
                script = f"{cs}; [WinAudio]::SetMute({target_bool}); [WinAudio]::GetMute()"

            res = self._run_powershell(script, timeout=4)
            if res.returncode == 0:
                final_muted = "true" in res.stdout.lower()
                return {"success": True, "muted": final_muted, "message": f"Mute state set to {final_muted}."}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

        return {"success": False, "error": "Failed to set mute state."}

    # -----------------------------------------------------------------------
    # Display Brightness Controls
    # -----------------------------------------------------------------------

    def get_brightness(self) -> dict:
        """Get current display brightness percentage (0-100) via WMI."""
        try:
            script = "(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness).CurrentBrightness"
            res = self._run_powershell(script, timeout=3)
            if res.returncode == 0 and res.stdout.strip().isdigit():
                return {"success": True, "brightness": int(res.stdout.strip())}
        except Exception as exc:
            return {"success": False, "error": f"Brightness query failed: {exc}"}

        return {"success": False, "error": "Unable to query Windows display brightness."}

    def set_brightness(self, level: int) -> dict:
        """Set display brightness percentage (clamped 0-100) via WMI."""
        level = max(0, min(100, int(level)))
        try:
            script = (
                f"(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods)"
                f".WmiSetBrightness(1, {level})"
            )
            res = self._run_powershell(script, timeout=3)
            if res.returncode == 0:
                return {"success": True, "brightness": level, "message": f"Brightness set to {level}%."}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

        return {"success": False, "error": f"Failed to set brightness to {level}%."}

    # -----------------------------------------------------------------------
    # Wi-Fi Controls
    # -----------------------------------------------------------------------

    def get_wifi_status(self) -> dict:
        """Get Wi-Fi status (enabled, connected, SSID, signal strength)."""
        try:
            res = subprocess.run(["netsh", "wlan", "show", "interfaces"], capture_output=True, text=True, timeout=3)
            if res.returncode != 0:
                return {"success": True, "enabled": False, "connected": False, "ssid": None, "signal": None}

            text = res.stdout
            enabled = "There is no wireless interface" not in text and "Software Off" not in text
            connected = "connected" in text.lower() and "disconnected" not in text.lower()

            ssid = None
            signal = None
            m_ssid = re.search(r"^\s*SSID\s*:\s*(.+)$", text, re.MULTILINE)
            if m_ssid:
                ssid = m_ssid.group(1).strip()

            m_sig = re.search(r"^\s*Signal\s*:\s*([0-9]+)%", text, re.MULTILINE)
            if m_sig:
                signal = int(m_sig.group(1))

            return {
                "success": True,
                "enabled": enabled,
                "connected": connected,
                "ssid": ssid,
                "signal": signal,
            }
        except Exception as exc:
            return {"success": False, "error": f"Wi-Fi status check failed: {exc}"}

    def set_wifi(self, enabled: bool) -> dict:
        """Turn Wi-Fi radio on or off via netsh / PowerShell NetAdapter."""
        state_str = "ENABLED" if enabled else "DISABLED"
        try:
            # 1. Try netsh interface
            res = subprocess.run(
                ["netsh", "interface", "set", "interface", "name=Wi-Fi", f"admin={state_str}"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if res.returncode == 0:
                return {"success": True, "enabled": enabled, "message": f"Wi-Fi interface {state_str.lower()}."}
        except Exception:
            pass

        # 2. Try PowerShell NetAdapter
        try:
            action = "Enable-NetAdapter" if enabled else "Disable-NetAdapter"
            script = f"Get-NetAdapter -Name *Wi-Fi* | {action} -Confirm:$false"
            res = self._run_powershell(script, timeout=5)
            if res.returncode == 0:
                return {"success": True, "enabled": enabled, "message": f"Wi-Fi interface {state_str.lower()}."}
        except Exception:
            pass

        return {"success": False, "error": f"Failed to turn Wi-Fi {state_str.lower()}."}

    def scan_wifi(self) -> dict:
        """Scan and list available Wi-Fi networks via netsh wlan."""
        networks: list[dict] = []
        try:
            res = subprocess.run(["netsh", "wlan", "show", "networks", "mode=bssid"], capture_output=True, text=True, timeout=5)
            if res.returncode == 0:
                current_ssid = None
                current_auth = None
                for line in res.stdout.splitlines():
                    m_ssid = re.match(r"^SSID\s+\d+\s*:\s*(.+)$", line.strip())
                    if m_ssid:
                        current_ssid = m_ssid.group(1).strip()
                    m_auth = re.match(r"^Authentication\s*:\s*(.+)$", line.strip())
                    if m_auth:
                        current_auth = m_auth.group(1).strip()
                    m_sig = re.match(r"^Signal\s*:\s*(\d+)%", line.strip())
                    if m_sig and current_ssid:
                        networks.append({
                            "ssid": current_ssid,
                            "signal": int(m_sig.group(1)),
                            "security": current_auth or "Unknown",
                        })
                        current_ssid = None
            return {"success": True, "networks": networks, "count": len(networks)}
        except Exception as exc:
            return {"success": False, "error": f"Wi-Fi scan failed: {exc}"}

    def connect_wifi(self, ssid: str, password: str | None = None) -> dict:
        """Connect to a Wi-Fi network by SSID."""
        try:
            res = subprocess.run(["netsh", "wlan", "connect", f"name={ssid}"], capture_output=True, text=True, timeout=10)
            if res.returncode == 0:
                return {"success": True, "ssid": ssid, "message": f"Connection to '{ssid}' initiated."}
            return {"success": False, "error": res.stderr.strip() or res.stdout.strip()}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    def disconnect_wifi(self) -> dict:
        """Disconnect from the currently connected Wi-Fi network."""
        try:
            res = subprocess.run(["netsh", "wlan", "disconnect"], capture_output=True, text=True, timeout=5)
            if res.returncode == 0:
                return {"success": True, "message": "Disconnected from Wi-Fi."}
            return {"success": False, "error": res.stderr.strip() or res.stdout.strip()}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    # -----------------------------------------------------------------------
    # Bluetooth Controls
    # -----------------------------------------------------------------------

    def get_bluetooth_status(self) -> dict:
        """Get Bluetooth status (enabled, devices) via PowerShell."""
        try:
            script = "Get-PnpDevice -Class Bluetooth | Select-Object FriendlyName, Status, InstanceId | ConvertTo-Json"
            res = self._run_powershell(script, timeout=4)
            enabled = False
            devices = []
            if res.returncode == 0 and res.stdout.strip():
                import json
                raw = json.loads(res.stdout)
                items = raw if isinstance(raw, list) else [raw]
                for it in items:
                    name = it.get("FriendlyName", "")
                    status = it.get("Status", "")
                    if status == "OK":
                        enabled = True
                    devices.append({"name": name, "status": status})
            return {"success": True, "enabled": enabled, "connected_devices": devices}
        except Exception as exc:
            return {"success": False, "error": f"Bluetooth status query failed: {exc}"}

    def set_bluetooth(self, enabled: bool) -> dict:
        """Turn Bluetooth radio on or off via PowerShell PnpDevice."""
        action = "Enable-PnpDevice" if enabled else "Disable-PnpDevice"
        try:
            script = f"Get-PnpDevice -Class Bluetooth | {action} -Confirm:$false"
            res = self._run_powershell(script, timeout=5)
            if res.returncode == 0:
                return {
                    "success": True,
                    "enabled": enabled,
                    "message": f"Bluetooth {'enabled' if enabled else 'disabled'}.",
                }
        except Exception as exc:
            return {"success": False, "error": str(exc)}

        return {"success": False, "error": f"Failed to {'enable' if enabled else 'disable'} Bluetooth."}

    # -----------------------------------------------------------------------
    # Battery & Power Controls
    # -----------------------------------------------------------------------

    def get_battery_status(self) -> dict:
        """Get battery percentage and charging state via WMI."""
        try:
            script = (
                "Get-CimInstance -ClassName Win32_Battery | "
                "Select-Object EstimatedChargeRemaining, BatteryStatus | "
                "ConvertTo-Json"
            )
            res = self._run_powershell(script, timeout=3)
            if res.returncode == 0 and res.stdout.strip():
                import json
                info = json.loads(res.stdout)
                percent = int(info.get("EstimatedChargeRemaining", 0))
                b_status = int(info.get("BatteryStatus", 1))
                # Status 2 = AC power (charging/full), 1 = discharging
                charging = (b_status == 2)
                return {
                    "success": True,
                    "has_battery": True,
                    "percent": percent,
                    "charging": charging,
                    "power_plugged": charging,
                    "status": "Charging" if charging else "Discharging",
                }
            return {
                "success": True,
                "has_battery": False,
                "percent": None,
                "charging": False,
                "power_plugged": True,
                "status": "AC Power",
            }
        except Exception as exc:
            return {"success": False, "error": f"Battery query failed: {exc}"}

    # -----------------------------------------------------------------------
    # System Session Controls
    # -----------------------------------------------------------------------

    def lock_screen(self) -> dict:
        """Lock the current Windows user session."""
        try:
            res = subprocess.run(["rundll32.exe", "user32.dll,LockWorkStation"], capture_output=True, timeout=2)
            if res.returncode == 0:
                return {"success": True, "message": "Screen locked successfully."}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

        return {"success": False, "error": "Failed to lock screen."}
