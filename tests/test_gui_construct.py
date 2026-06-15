"""
Headless construction smoke test for the GTK GUI.

Constructs every page (and the main window) against a stub client with a fake
settings payload and calls load_settings/update_monitoring, catching
attribute/None-handling regressions without a running daemon. This is the
closest automated proxy to "running the GUI" — it does NOT exercise real
interaction or D-Bus.

Requires a display (X or Wayland). If none is available, the test SKIPS with a
zero exit so it never blocks CI that lacks a display server.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "gui"))

import gi  # noqa: E402
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Gdk  # noqa: E402


FAKE_SETTINGS = {
    "features": [
        "thermal_profiles", "fan_control", "battery_limiter",
        "battery_calibration", "usb_charging", "keyboard_per_zone",
        "keyboard_effects", "backlight_timeout", "lcd_override",
        "boot_animation_sound", "display_mode", "game_mode",
        "audio_enhancement",
    ],
    "laptop_type": "nitro",
    "daemon_version": "test",
    "thermal_profile": "balanced",
    "thermal_choices": ["low-power", "balanced", "balanced-performance",
                        "performance", "quiet"],
    "fan_speed_cpu": 0, "fan_speed_gpu": 0,
    "fan_rpm_cpu": 2000, "fan_rpm_gpu": 2200,
    "battery_calibration": False, "battery_limiter": True, "usb_charging": "20",
    "lcd_override": False, "boot_animation_sound": True, "backlight_timeout": False,
    "battery_info": {"present": True, "percentage": 80, "status": "Charging",
                     "time_remaining": "1h 0m"},
    "power_source_ac": True,
    "system_info": {"product_name": "Nitro AN515", "vendor": "Acer",
                    "cpu_model": "AMD Ryzen 7", "gpu_model": "NVIDIA RTX",
                    "laptop_type": "nitro", "driver_version": "1.0",
                    "daemon_version": "test", "kernel": "6.12.0"},
    "fan_curve": {"cpu": {"enabled": False, "points": []},
                  "gpu": {"enabled": False, "points": []}},
    "display_mode": "hybrid",
    "game_mode": False,
    "firmware_info": {"bios_version": "1.0", "fwupd_available": True,
                      "vendor": "Acer", "updates": []},
    "mux_switch": {"detected": False},
    "saved_settings": {},
}

FAKE_TELEMETRY = {
    "cpu_temp": 55, "gpu_temp": 48, "cpu_usage": 12, "gpu_usage": 4,
    "fan_rpm_cpu": 2000, "fan_rpm_gpu": 2200,
    "battery_info": {"present": True, "percentage": 80, "status": "Charging"},
    "power_source_ac": True,
}


class StubClient:
    """Stand-in for ArcherClient: never touches D-Bus."""
    init_error = None
    dbus_iface = None

    def __init__(self):
        self._features = list(FAKE_SETTINGS["features"])

    @property
    def features(self):
        return self._features

    @property
    def is_connected(self):
        return True

    def reconnect(self):
        return True

    def get_all_settings(self):
        return dict(FAKE_SETTINGS)

    def get_monitoring_data(self):
        return dict(FAKE_TELEMETRY)

    # Setters — should not be invoked during construction/load.
    def __getattr__(self, name):
        if name.startswith(("set_", "get_", "remove_", "restart_")):
            return lambda *a, **k: {"success": True, "data": {}}
        raise AttributeError(name)


def _build_pages(client):
    from archer.pages.dashboard import DashboardPage
    from archer.pages.performance import PerformancePage
    from archer.pages.battery import BatteryPage
    from archer.pages.keyboard import KeyboardPage
    from archer.pages.system import SystemPage
    from archer.pages.internals import InternalsPage
    from archer.pages.display import DisplayPage
    from archer.pages.gamemode import GameModePage
    from archer.pages.audio_enhance import AudioEnhancePage
    from archer.pages.firmware import FirmwarePage

    pages = {
        "dashboard": DashboardPage(client),
        "performance": PerformancePage(client),
        "battery": BatteryPage(client),
        "keyboard": KeyboardPage(client),
        "system": SystemPage(client),
        "internals": InternalsPage(client),
        "display": DisplayPage(client),
        "gamemode": GameModePage(client),
        "audio_enhance": AudioEnhancePage(client),
        "firmware": FirmwarePage(client),
    }
    for name, page in pages.items():
        page.load_settings(dict(FAKE_SETTINGS))
        print(f"OK: {name} page constructed + load_settings")
    # Dashboard also consumes live telemetry.
    pages["dashboard"].update_monitoring(dict(FAKE_TELEMETRY))
    print("OK: dashboard update_monitoring")
    return pages


def _build_window(client, force_fallback=False):
    import archer.window as window_mod
    window_mod.ArcherClient = lambda: client  # avoid real D-Bus
    original = window_mod._HAS_SPLIT_VIEW
    window_mod._HAS_SPLIT_VIEW = not force_fallback and original
    try:
        app = Adw.Application(application_id="io.github.archer.test")
        win = window_mod.ArcherWindow(application=app)
        win._on_settings_loaded(dict(FAKE_SETTINGS))
        layout = "fallback" if force_fallback else "split-view"
        print(f"OK: ArcherWindow constructed + settings loaded ({layout})")
    finally:
        window_mod._HAS_SPLIT_VIEW = original
    return win


def main():
    Adw.init()
    if Gdk.Display.get_default() is None:
        print("SKIP: no display available; GUI construction test skipped")
        return
    client = StubClient()
    _build_pages(client)
    _build_window(client, force_fallback=False)
    _build_window(client, force_fallback=True)
    print("PASS: GUI construction smoke complete")


if __name__ == "__main__":
    main()
