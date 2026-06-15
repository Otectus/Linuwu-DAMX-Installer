"""
Shared status model — a single source of truth for the window's connection,
driver, and reboot-required state, consumed by the header badge, the persistent
status footer, and the dashboard hero so they never drift out of sync.
"""

# Connection states.
CONNECTING = "connecting"
CONNECTED = "connected"
STALE = "stale"
OFFLINE = "offline"

_DRIVER_FEATURES = ("keyboard_per_zone", "fan_control", "battery_limiter",
                    "thermal_profiles", "lcd_override")


class StatusModel:
    """Plain data holder; widgets read its attributes and re-render."""

    def __init__(self):
        self.connection = CONNECTING
        self.model_name = None
        self.laptop_type = None
        self.daemon_version = None
        self.driver_loaded = False
        self.reboot_required = False

    def update_from_settings(self, data):
        """Refresh hardware-derived fields from a GetAllSettings payload."""
        if not data:
            return
        sys_info = data.get("system_info", {}) or {}
        self.model_name = sys_info.get("product_name") or data.get("laptop_type")
        self.laptop_type = data.get("laptop_type")
        self.daemon_version = data.get("daemon_version") or sys_info.get("daemon_version")

        driver_version = sys_info.get("driver_version")
        features = data.get("features", []) or []
        self.driver_loaded = (
            bool(driver_version) and driver_version not in ("N/A", "")
        ) or any(f in features for f in _DRIVER_FEATURES)

        # display_mode_reboot_pending isn't part of GetAllSettings today, but
        # honor it if a future daemon adds it; the window can also set this
        # flag directly after a display-mode switch.
        if data.get("display_mode_reboot_pending"):
            self.reboot_required = True

    @property
    def connection_label(self):
        return {
            CONNECTING: "Connecting…",
            CONNECTED: "Connected",
            STALE: "Stale",
            OFFLINE: "Daemon Offline",
        }.get(self.connection, self.connection)

    @property
    def is_ok(self):
        return self.connection == CONNECTED
