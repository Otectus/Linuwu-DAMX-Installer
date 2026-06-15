"""
Archer D-Bus Service — exposes HardwareManager over system D-Bus with polkit authorization.
"""

import json
import logging
import os
import threading

import dbus
import dbus.service
from gi.repository import GLib

logger = logging.getLogger("archer-daemon")

# How often the daemon pushes a TelemetryUpdated signal. The GUI considers
# data "stale" if it has not seen a signal within ~3x this interval.
TELEMETRY_INTERVAL_S = 2

DBUS_NAME = "io.otectus.Archer1"
DBUS_PATH = "/io/otectus/Archer1"
DBUS_IFACE = "io.otectus.Archer1"

# Polkit action IDs mapped to command groups
POLKIT_ACTIONS = {
    "set_thermal_profile": "io.otectus.archer1.set-profile",
    "set_fan_speed": "io.otectus.archer1.set-fan",
    "set_fan_curve": "io.otectus.archer1.set-fan",
    "set_battery_calibration": "io.otectus.archer1.set-hardware",
    "set_battery_limiter": "io.otectus.archer1.set-hardware",
    "set_usb_charging": "io.otectus.archer1.set-hardware",
    "set_backlight_timeout": "io.otectus.archer1.set-hardware",
    "set_lcd_override": "io.otectus.archer1.set-hardware",
    "set_boot_animation_sound": "io.otectus.archer1.set-hardware",
    "set_per_zone_mode": "io.otectus.archer1.set-hardware",
    "set_four_zone_mode": "io.otectus.archer1.set-hardware",
    "set_usb_wake": "io.otectus.archer1.set-hardware",
    "set_audio_enhancement": "io.otectus.archer1.set-hardware",
    "set_display_mode": "io.otectus.archer1.set-display",
    "set_game_mode": "io.otectus.archer1.set-gamemode",
    "restart_daemon": "io.otectus.archer1.system-control",
    "restart_drivers_and_daemon": "io.otectus.archer1.system-control",
    "set_modprobe_parameter": "io.otectus.archer1.system-control",
    "remove_modprobe_parameter": "io.otectus.archer1.system-control",
}


def _check_polkit(bus, sender, action_id):
    """Check polkit authorization for the calling process."""
    proxy = bus.get_object("org.freedesktop.PolicyKit1",
                           "/org/freedesktop/PolicyKit1/Authority")
    authority = dbus.Interface(proxy, "org.freedesktop.PolicyKit1.Authority")

    subject = ("system-bus-name", {"name": sender})
    result = authority.CheckAuthorization(
        subject, action_id, {}, dbus.UInt32(1), ""  # 1 = AllowUserInteraction
    )
    is_authorized = bool(result[0])
    if not is_authorized:
        logger.warning(f"Polkit denied {action_id} for {sender}")
    return is_authorized


class ArcherDBusService(dbus.service.Object):
    """Exports Archer hardware control over D-Bus with polkit checks."""

    def __init__(self, hw_manager, bus=None):
        self.hw = hw_manager
        self._bus = bus or dbus.SystemBus()
        self._bus_name = dbus.service.BusName(DBUS_NAME, self._bus)
        super().__init__(self._bus, DBUS_PATH)
        logger.info(f"D-Bus service registered: {DBUS_NAME} at {DBUS_PATH}")
        # Push telemetry on a timer so the GUI doesn't have to poll. Returns
        # True so GLib keeps re-arming the timeout.
        GLib.timeout_add_seconds(TELEMETRY_INTERVAL_S, self._emit_telemetry)

    def _emit_telemetry(self):
        try:
            payload = json.dumps(self.hw.get_monitoring_data())
            self.TelemetryUpdated(payload)
        except Exception as e:
            # Don't let a transient sysfs hiccup kill the timer.
            logger.warning(f"TelemetryUpdated emit failed: {e}")
        return True

    def _authorize(self, command, sender):
        """Check polkit for mutating commands. Returns True if authorized."""
        action_id = POLKIT_ACTIONS.get(command)
        if not action_id:
            return True  # Read-only commands need no auth
        return _check_polkit(self._bus, sender, action_id)

    def _json_response(self, data):
        """Serialize response to JSON string for D-Bus transport."""
        return json.dumps(data)

    # --- Read-Only Methods (no polkit) ---

    @dbus.service.method(DBUS_IFACE, in_signature="", out_signature="s",
                         sender_keyword="sender")
    def Ping(self, sender=None):
        return self._json_response({"success": True, "data": {"version": self.hw.settings.get("daemon_version", "2.0.1")}})

    @dbus.service.method(DBUS_IFACE, in_signature="", out_signature="s",
                         sender_keyword="sender")
    def GetAllSettings(self, sender=None):
        return self._json_response({"success": True, "data": self.hw.get_all_settings()})

    @dbus.service.method(DBUS_IFACE, in_signature="", out_signature="s",
                         sender_keyword="sender")
    def GetMonitoringData(self, sender=None):
        return self._json_response({"success": True, "data": self.hw.get_monitoring_data()})

    @dbus.service.method(DBUS_IFACE, in_signature="", out_signature="s",
                         sender_keyword="sender")
    def GetSupportedFeatures(self, sender=None):
        return self._json_response({"success": True, "data": {"features": self.hw.features}})

    @dbus.service.method(DBUS_IFACE, in_signature="", out_signature="s",
                         sender_keyword="sender")
    def GetFanCurve(self, sender=None):
        return self._json_response({"success": True, "data": self.hw.get_fan_curve_state()})

    @dbus.service.method(DBUS_IFACE, in_signature="", out_signature="s",
                         sender_keyword="sender")
    def GetDisplayMode(self, sender=None):
        return self._json_response({"success": True, "data": self.hw.get_display_mode()})

    @dbus.service.method(DBUS_IFACE, in_signature="", out_signature="s",
                         sender_keyword="sender")
    def GetGameMode(self, sender=None):
        return self._json_response({"success": True, "data": self.hw.get_game_mode()})

    @dbus.service.method(DBUS_IFACE, in_signature="", out_signature="s",
                         sender_keyword="sender")
    def GetUsbPowerPolicy(self, sender=None):
        usb_level = self.hw.get_usb_charging()
        wake = self.hw.get_usb_wake_sources()
        return self._json_response({"success": True, "data": {
            "charging_level": usb_level, "wake_sources": wake,
        }})

    @dbus.service.method(DBUS_IFACE, in_signature="", out_signature="s",
                         sender_keyword="sender")
    def GetFirmwareInfo(self, sender=None):
        return self._json_response({"success": True, "data": self.hw.get_firmware_info()})

    # --- Mutating Methods (polkit-protected) ---

    @dbus.service.method(DBUS_IFACE, in_signature="s", out_signature="s",
                         sender_keyword="sender")
    def SetThermalProfile(self, profile, sender=None):
        if not self._authorize("set_thermal_profile", sender):
            return self._json_response({"success": False, "error": "Authorization denied"})
        ok, err = self.hw.set_thermal_profile(profile)
        if ok:
            self.hw.settings.set("thermal_profile", profile)
            self.ProfileChanged(profile)
        return self._json_response({"success": ok, "error": err})

    @dbus.service.method(DBUS_IFACE, in_signature="ii", out_signature="s",
                         sender_keyword="sender")
    def SetFanSpeed(self, cpu, gpu, sender=None):
        if not self._authorize("set_fan_speed", sender):
            return self._json_response({"success": False, "error": "Authorization denied"})
        ok = self.hw.set_fan_speed(cpu, gpu)
        if ok:
            self.hw.settings.set("fan_speed", {"cpu": cpu, "gpu": gpu})
        return self._json_response({"success": ok})

    @dbus.service.method(DBUS_IFACE, in_signature="s", out_signature="s",
                         sender_keyword="sender")
    def SetFanCurve(self, params_json, sender=None):
        if not self._authorize("set_fan_curve", sender):
            return self._json_response({"success": False, "error": "Authorization denied"})
        params = json.loads(params_json)
        target = params.get("target", "cpu")
        points = params.get("points", [])
        enabled = params.get("enabled", True)
        if enabled:
            self.hw.start_fan_curve(target, points)
            self.hw.settings.set(f"fan_curve_{target}", {"enabled": True, "points": points})
        else:
            self.hw.stop_fan_curve(target)
        return self._json_response({"success": True})

    @dbus.service.method(DBUS_IFACE, in_signature="b", out_signature="s",
                         sender_keyword="sender")
    def SetBatteryCalibration(self, enabled, sender=None):
        if not self._authorize("set_battery_calibration", sender):
            return self._json_response({"success": False, "error": "Authorization denied"})
        ok = self.hw.set_battery_calibration(enabled)
        if ok:
            self.hw.settings.set("battery_calibration", enabled)
        return self._json_response({"success": ok})

    @dbus.service.method(DBUS_IFACE, in_signature="b", out_signature="s",
                         sender_keyword="sender")
    def SetBatteryLimiter(self, enabled, sender=None):
        if not self._authorize("set_battery_limiter", sender):
            return self._json_response({"success": False, "error": "Authorization denied"})
        ok = self.hw.set_battery_limiter(enabled)
        if ok:
            self.hw.settings.set("battery_limiter", enabled)
        return self._json_response({"success": ok})

    @dbus.service.method(DBUS_IFACE, in_signature="i", out_signature="s",
                         sender_keyword="sender")
    def SetUsbCharging(self, level, sender=None):
        if not self._authorize("set_usb_charging", sender):
            return self._json_response({"success": False, "error": "Authorization denied"})
        ok = self.hw.set_usb_charging(level)
        if ok:
            self.hw.settings.set("usb_charging", level)
        return self._json_response({"success": ok})

    @dbus.service.method(DBUS_IFACE, in_signature="b", out_signature="s",
                         sender_keyword="sender")
    def SetBacklightTimeout(self, enabled, sender=None):
        if not self._authorize("set_backlight_timeout", sender):
            return self._json_response({"success": False, "error": "Authorization denied"})
        ok = self.hw.set_backlight_timeout(enabled)
        if ok:
            self.hw.settings.set("backlight_timeout", enabled)
        return self._json_response({"success": ok})

    @dbus.service.method(DBUS_IFACE, in_signature="b", out_signature="s",
                         sender_keyword="sender")
    def SetLcdOverride(self, enabled, sender=None):
        if not self._authorize("set_lcd_override", sender):
            return self._json_response({"success": False, "error": "Authorization denied"})
        ok = self.hw.set_lcd_override(enabled)
        if ok:
            self.hw.settings.set("lcd_override", enabled)
        return self._json_response({"success": ok})

    @dbus.service.method(DBUS_IFACE, in_signature="b", out_signature="s",
                         sender_keyword="sender")
    def SetBootAnimationSound(self, enabled, sender=None):
        if not self._authorize("set_boot_animation_sound", sender):
            return self._json_response({"success": False, "error": "Authorization denied"})
        ok = self.hw.set_boot_animation_sound(enabled)
        if ok:
            self.hw.settings.set("boot_animation_sound", enabled)
        return self._json_response({"success": ok})

    @dbus.service.method(DBUS_IFACE, in_signature="s", out_signature="s",
                         sender_keyword="sender")
    def SetPerZoneMode(self, params_json, sender=None):
        if not self._authorize("set_per_zone_mode", sender):
            return self._json_response({"success": False, "error": "Authorization denied"})
        p = json.loads(params_json)
        ok = self.hw.set_per_zone_mode(p["zone1"], p["zone2"], p["zone3"], p["zone4"], p["brightness"])
        if ok:
            self.hw.settings.set("per_zone_mode", p)
            self.hw.settings.set("last_keyboard_mode", "per_zone")
        return self._json_response({"success": ok})

    @dbus.service.method(DBUS_IFACE, in_signature="s", out_signature="s",
                         sender_keyword="sender")
    def SetFourZoneMode(self, params_json, sender=None):
        if not self._authorize("set_four_zone_mode", sender):
            return self._json_response({"success": False, "error": "Authorization denied"})
        p = json.loads(params_json)
        ok = self.hw.set_four_zone_mode(p["mode"], p["speed"], p["brightness"],
                                        p["direction"], p["red"], p["green"], p["blue"])
        if ok:
            self.hw.settings.set("four_zone_mode", p)
            self.hw.settings.set("last_keyboard_mode", "effect")
        return self._json_response({"success": ok})

    @dbus.service.method(DBUS_IFACE, in_signature="s", out_signature="s",
                         sender_keyword="sender")
    def SetDisplayMode(self, mode, sender=None):
        if not self._authorize("set_display_mode", sender):
            return self._json_response({"success": False, "error": "Authorization denied"})
        result = self.hw.set_display_mode(mode)
        return self._json_response(result)

    @dbus.service.method(DBUS_IFACE, in_signature="b", out_signature="s",
                         sender_keyword="sender")
    def SetGameMode(self, enabled, sender=None):
        if not self._authorize("set_game_mode", sender):
            return self._json_response({"success": False, "error": "Authorization denied"})
        if enabled:
            self.hw.activate_game_mode()
        else:
            self.hw.deactivate_game_mode()
        return self._json_response({"success": True, "data": {"active": enabled}})

    @dbus.service.method(DBUS_IFACE, in_signature="sb", out_signature="s",
                         sender_keyword="sender")
    def SetUsbWake(self, device, enabled, sender=None):
        if not self._authorize("set_usb_wake", sender):
            return self._json_response({"success": False, "error": "Authorization denied"})
        ok = self.hw.set_usb_wake(device, enabled)
        return self._json_response({"success": ok})

    @dbus.service.method(DBUS_IFACE, in_signature="s", out_signature="s",
                         sender_keyword="sender")
    def SetAudioEnhancement(self, params_json, sender=None):
        if not self._authorize("set_audio_enhancement", sender):
            return self._json_response({"success": False, "error": "Authorization denied"})
        params = json.loads(params_json)
        noise = params.get("noise_suppression", False)
        conf = "/etc/pipewire/filter-chain.conf.d/archer-noise-suppress.conf"
        conf_disabled = conf + ".disabled"
        try:
            if noise:
                if os.path.exists(conf_disabled) and not os.path.exists(conf):
                    os.rename(conf_disabled, conf)
            else:
                if os.path.exists(conf):
                    os.rename(conf, conf_disabled)
            self.hw.settings.set("audio_enhancement", {"noise_suppression": noise})
            # Tell the GUI to restart pipewire in the calling user's
            # session. The daemon runs as root, so `systemctl --user
            # restart pipewire` here would target root's user manager
            # and never touch the actual user's pipewire instance.
            self.AudioEnhancementChanged(noise)
            return self._json_response({"success": True, "data": {"noise_suppression": noise}})
        except OSError as e:
            return self._json_response({"success": False, "error": str(e)})

    @dbus.service.method(DBUS_IFACE, in_signature="s", out_signature="s",
                         sender_keyword="sender")
    def SetModprobeParameter(self, param, sender=None):
        if not self._authorize("set_modprobe_parameter", sender):
            return self._json_response({"success": False, "error": "Authorization denied"})
        if param not in ("nitro_v4", "predator_v4", "enable_all"):
            return self._json_response({"success": False, "error": f"Invalid parameter: {param}"})
        ok = self.hw.set_modprobe_parameter(param)
        return self._json_response({"success": ok})

    @dbus.service.method(DBUS_IFACE, in_signature="", out_signature="s",
                         sender_keyword="sender")
    def RemoveModprobeParameter(self, sender=None):
        if not self._authorize("remove_modprobe_parameter", sender):
            return self._json_response({"success": False, "error": "Authorization denied"})
        ok = self.hw.remove_modprobe_parameter()
        return self._json_response({"success": ok})

    @dbus.service.method(DBUS_IFACE, in_signature="", out_signature="s",
                         sender_keyword="sender")
    def RestartDaemon(self, sender=None):
        if not self._authorize("restart_daemon", sender):
            return self._json_response({"success": False, "error": "Authorization denied"})
        threading.Thread(target=self.hw.restart_daemon, daemon=True).start()
        return self._json_response({"success": True})

    @dbus.service.method(DBUS_IFACE, in_signature="", out_signature="s",
                         sender_keyword="sender")
    def RestartDriversAndDaemon(self, sender=None):
        if not self._authorize("restart_drivers_and_daemon", sender):
            return self._json_response({"success": False, "error": "Authorization denied"})
        threading.Thread(target=self.hw.restart_drivers_and_daemon, daemon=True).start()
        return self._json_response({"success": True})

    # --- D-Bus Signals ---

    @dbus.service.signal(DBUS_IFACE, signature="s")
    def TelemetryUpdated(self, data_json):
        pass

    @dbus.service.signal(DBUS_IFACE, signature="s")
    def ProfileChanged(self, profile):
        pass

    @dbus.service.signal(DBUS_IFACE, signature="b")
    def AudioEnhancementChanged(self, enabled):
        pass
