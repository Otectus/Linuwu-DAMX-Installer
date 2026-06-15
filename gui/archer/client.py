"""
Client for communicating with the Archer daemon over the system D-Bus.

Every method call has a timeout. Without it, dbus-python defaults to no
timeout, which is what made the GUI freeze whenever the daemon paused on
a slow sysfs read or subprocess. The Unix-socket fallback was removed
because the daemon's socket has been root:root 0o660 since the move to
D-Bus + polkit, so the user-mode GUI was never able to read it anyway.
"""

import json
import logging
import threading

logger = logging.getLogger("archer-client")

# Default per-call timeout (seconds). Fast enough that a hung daemon is
# noticed within one polling tick; long enough that ordinary sysfs reads
# don't false-positive.
TIMEOUT = 5.0

# Setters that may legitimately take longer than TIMEOUT. envycontrol can
# reflow the X/Wayland session config; fwupd can scan slow SPI flash.
LONG_TIMEOUTS = {
    "set_display_mode": 60.0,
    "get_firmware_info": 30.0,
    "restart_daemon": 10.0,
    "restart_drivers_and_daemon": 15.0,
}

DBUS_NAME = "io.otectus.Archer1"
DBUS_PATH = "/io/otectus/Archer1"
DBUS_IFACE = "io.otectus.Archer1"

# Maps _send_command names to D-Bus method names + argument packaging.
_DBUS_METHOD_MAP = {
    "ping": ("Ping", None),
    "get_all_settings": ("GetAllSettings", None),
    "get_monitoring_data": ("GetMonitoringData", None),
    "get_supported_features": ("GetSupportedFeatures", None),
    "get_fan_curve": ("GetFanCurve", None),
    "get_display_mode": ("GetDisplayMode", None),
    "get_game_mode": ("GetGameMode", None),
    "get_usb_power_policy": ("GetUsbPowerPolicy", None),
    "get_firmware_info": ("GetFirmwareInfo", None),
    "set_thermal_profile": ("SetThermalProfile", lambda p: (p["profile"],)),
    "set_fan_speed": ("SetFanSpeed", lambda p: (p["cpu"], p["gpu"])),
    "set_fan_curve": ("SetFanCurve", lambda p: (json.dumps(p),)),
    "set_battery_calibration": ("SetBatteryCalibration", lambda p: (p["enabled"],)),
    "set_battery_limiter": ("SetBatteryLimiter", lambda p: (p["enabled"],)),
    "set_usb_charging": ("SetUsbCharging", lambda p: (p["level"],)),
    "set_backlight_timeout": ("SetBacklightTimeout", lambda p: (p["enabled"],)),
    "set_lcd_override": ("SetLcdOverride", lambda p: (p["enabled"],)),
    "set_boot_animation_sound": ("SetBootAnimationSound", lambda p: (p["enabled"],)),
    "set_per_zone_mode": ("SetPerZoneMode", lambda p: (json.dumps(p),)),
    "set_four_zone_mode": ("SetFourZoneMode", lambda p: (json.dumps(p),)),
    "set_display_mode": ("SetDisplayMode", lambda p: (p["mode"],)),
    "set_game_mode": ("SetGameMode", lambda p: (p["enabled"],)),
    "set_usb_wake": ("SetUsbWake", lambda p: (p["device"], p["enabled"])),
    "set_audio_enhancement": ("SetAudioEnhancement", lambda p: (json.dumps(p),)),
    "set_modprobe_parameter": ("SetModprobeParameter", lambda p: (p["parameter"],)),
    "remove_modprobe_parameter": ("RemoveModprobeParameter", None),
    "restart_daemon": ("RestartDaemon", None),
    "restart_drivers_and_daemon": ("RestartDriversAndDaemon", None),
}

DAEMON_OFFLINE_HINT = (
    "Daemon unreachable. Check 'systemctl status archer-daemon' and "
    "'journalctl -u archer-daemon -n 50'. If the policy file was just "
    "installed, run 'sudo systemctl reload dbus.service'."
)


class ArcherClient:
    """Client for the Archer daemon. D-Bus only."""

    def __init__(self):
        self._lock = threading.Lock()
        self._features = []
        self._connected = False
        self._dbus_iface = None
        self._init_error = None
        self._init_dbus()

    def _init_dbus(self):
        """Connect to the daemon via the system D-Bus. Stores any failure
        on self._init_error so the window can surface it."""
        try:
            import dbus
            bus = dbus.SystemBus()
            proxy = bus.get_object(DBUS_NAME, DBUS_PATH)
            self._dbus_iface = dbus.Interface(proxy, DBUS_IFACE)
            self._dbus_iface.Ping(timeout=TIMEOUT)
            self._connected = True
            self._init_error = None
            logger.info("Connected to Archer daemon via D-Bus")
        except Exception as e:
            self._connected = False
            self._init_error = f"{e}"
            logger.warning(
                f"D-Bus connection failed: {e}. {DAEMON_OFFLINE_HINT}"
            )

    @property
    def init_error(self):
        """The string from the most recent _init_dbus failure, or None."""
        return self._init_error

    def reconnect(self):
        """Try the D-Bus handshake again. Used by the window's backoff loop."""
        with self._lock:
            self._init_dbus()
        return self._connected

    def _send_command(self, command, params=None):
        """Send a command and return the response dict."""
        return self._send_dbus(command, params)

    def _send_dbus(self, command, params=None):
        """Send command via D-Bus with a per-call timeout."""
        mapping = _DBUS_METHOD_MAP.get(command)
        if not mapping:
            return {"success": False, "error": f"Unknown command: {command}"}

        if self._dbus_iface is None:
            return {"success": False, "error": DAEMON_OFFLINE_HINT}

        method_name, args_fn = mapping
        timeout = LONG_TIMEOUTS.get(command, TIMEOUT)
        try:
            method = getattr(self._dbus_iface, method_name)
            if args_fn and params:
                result_json = method(*args_fn(params), timeout=timeout)
            else:
                result_json = method(timeout=timeout)
            self._connected = True
            return json.loads(str(result_json))
        except Exception as e:
            self._connected = False
            error_str = str(e)
            if "not authorized" in error_str.lower() or "authorization" in error_str.lower():
                return {"success": False, "error": "Authorization denied"}
            if "timeout" in error_str.lower() or "Timed out" in error_str:
                return {
                    "success": False,
                    "error": f"Daemon did not respond within {timeout}s",
                }
            return {"success": False, "error": error_str}

    @property
    def is_connected(self):
        return self._connected

    @property
    def features(self):
        return self._features

    def has_feature(self, feature):
        return feature in self._features

    # Used by the window to subscribe to TelemetryUpdated. Returns the
    # raw dbus.Interface or None if the client isn't connected.
    @property
    def dbus_iface(self):
        return self._dbus_iface

    # --- High-level API ---
    def ping(self):
        resp = self._send_command("ping")
        return resp.get("success", False)

    def get_all_settings(self):
        resp = self._send_command("get_all_settings")
        if resp.get("success"):
            data = resp.get("data", {})
            self._features = data.get("features", [])
            return data
        return None

    def get_monitoring_data(self):
        resp = self._send_command("get_monitoring_data")
        if resp.get("success"):
            return resp.get("data", {})
        return None

    def get_supported_features(self):
        resp = self._send_command("get_supported_features")
        if resp.get("success"):
            self._features = resp["data"].get("features", [])
            return self._features
        return []

    def set_thermal_profile(self, profile):
        return self._send_command("set_thermal_profile", {"profile": profile})

    def set_fan_speed(self, cpu, gpu):
        return self._send_command("set_fan_speed", {"cpu": cpu, "gpu": gpu})

    def set_battery_calibration(self, enabled):
        return self._send_command("set_battery_calibration", {"enabled": enabled})

    def set_battery_limiter(self, enabled):
        return self._send_command("set_battery_limiter", {"enabled": enabled})

    def set_usb_charging(self, level):
        return self._send_command("set_usb_charging", {"level": level})

    def set_backlight_timeout(self, enabled):
        return self._send_command("set_backlight_timeout", {"enabled": enabled})

    def set_lcd_override(self, enabled):
        return self._send_command("set_lcd_override", {"enabled": enabled})

    def set_boot_animation_sound(self, enabled):
        return self._send_command("set_boot_animation_sound", {"enabled": enabled})

    def set_per_zone_mode(self, zone1, zone2, zone3, zone4, brightness):
        return self._send_command("set_per_zone_mode", {
            "zone1": zone1, "zone2": zone2,
            "zone3": zone3, "zone4": zone4,
            "brightness": brightness,
        })

    def set_four_zone_mode(self, mode, speed, brightness, direction, r, g, b):
        return self._send_command("set_four_zone_mode", {
            "mode": mode, "speed": speed, "brightness": brightness,
            "direction": direction, "red": r, "green": g, "blue": b,
        })

    def set_modprobe_parameter(self, parameter):
        return self._send_command("set_modprobe_parameter", {"parameter": parameter})

    def remove_modprobe_parameter(self):
        return self._send_command("remove_modprobe_parameter")

    def restart_daemon(self):
        return self._send_command("restart_daemon")

    def restart_drivers_and_daemon(self):
        return self._send_command("restart_drivers_and_daemon")
