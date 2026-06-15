"""
Battery Controls page - calibration, charge limit, USB power delivery.
"""

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw

from archer.widgets.async_set import async_set


class BatteryPage(Gtk.Box):
    def __init__(self, client):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.client = client
        self._calibrating = False
        self._build_ui()

    def _toast(self, message):
        """Show a toast on the parent ArcherWindow if attached."""
        win = self.get_root()
        if win is not None and hasattr(win, "add_toast"):
            win.add_toast(Adw.Toast.new(message))

    def _build_ui(self):
        scrolled = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        clamp = Adw.Clamp(maximum_size=900, margin_top=24, margin_bottom=24,
                          margin_start=12, margin_end=12)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)

        # --- Battery Status Card ---
        self.status_group = Adw.PreferencesGroup(title="Battery Status")

        self.bat_percentage_row = Adw.ActionRow(title="Charge Level", subtitle="--")
        self.bat_percentage_bar = Gtk.LevelBar(
            min_value=0, max_value=100, hexpand=True,
            valign=Gtk.Align.CENTER)
        self.bat_percentage_bar.set_size_request(200, -1)
        self.bat_percentage_row.add_suffix(self.bat_percentage_bar)
        self.status_group.add(self.bat_percentage_row)

        self.bat_status_row = Adw.ActionRow(title="Status", subtitle="Unknown")
        self.status_group.add(self.bat_status_row)

        self.bat_time_row = Adw.ActionRow(title="Time Remaining", subtitle="--")
        self.status_group.add(self.bat_time_row)

        content.append(self.status_group)

        # --- Charge Limit ---
        self.limit_group = Adw.PreferencesGroup(
            title="Charge Limit",
            description="Limit battery charging to 80% to extend battery lifespan. "
                        "Recommended for laptops frequently connected to AC power.",
        )

        self.limit_switch = Adw.SwitchRow(title="Enable 80% Charge Limit")
        self.limit_switch.connect("notify::active", self._on_limit_toggled)
        self.limit_group.add(self.limit_switch)

        content.append(self.limit_group)

        # --- Battery Calibration ---
        self.calibration_group = Adw.PreferencesGroup(
            title="Battery Calibration",
            description="Performs a full charge-discharge cycle to recalibrate the battery gauge. "
                        "Keep AC power connected during calibration.",
        )

        self.calibration_status_row = Adw.ActionRow(
            title="Calibration Status", subtitle="Not calibrating"
        )
        self.calibration_group.add(self.calibration_status_row)

        # Calibration buttons
        cal_button_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL, spacing=12,
            halign=Gtk.Align.CENTER, margin_top=12)

        self.start_cal_button = Gtk.Button(label="Start Calibration")
        self.start_cal_button.add_css_class("suggested-action")
        self.start_cal_button.connect("clicked", self._on_start_calibration)
        cal_button_box.append(self.start_cal_button)

        self.stop_cal_button = Gtk.Button(label="Stop Calibration")
        self.stop_cal_button.add_css_class("destructive-action")
        self.stop_cal_button.set_sensitive(False)
        self.stop_cal_button.connect("clicked", self._on_stop_calibration)
        cal_button_box.append(self.stop_cal_button)

        cal_row = Adw.PreferencesRow()
        cal_inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin_top=6,
                            margin_bottom=12, margin_start=12, margin_end=12)
        cal_inner.append(cal_button_box)
        cal_row.set_child(cal_inner)
        self.calibration_group.add(cal_row)

        # Warning
        warning_row = Adw.ActionRow(
            title="Warning",
            subtitle="Do not unplug AC power during calibration.",
            icon_name="dialog-warning-symbolic",
        )
        warning_row.add_css_class("warning")
        self.calibration_group.add(warning_row)

        content.append(self.calibration_group)

        # --- USB Power Delivery ---
        self.usb_group = Adw.PreferencesGroup(
            title="USB Power Delivery",
            description="Allow USB ports to charge devices when the laptop is powered off.",
        )

        self.usb_combo = Adw.ComboRow(title="USB Charging When Off")
        usb_model = Gtk.StringList.new([
            "Disabled",
            "Until battery reaches 10%",
            "Until battery reaches 20%",
            "Until battery reaches 30%",
        ])
        self.usb_combo.set_model(usb_model)
        self.usb_combo.set_selected(2)  # Default: 20%
        self.usb_combo.connect("notify::selected", self._on_usb_changed)
        self.usb_group.add(self.usb_combo)

        content.append(self.usb_group)

        # --- No Battery Message ---
        self.no_battery_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            valign=Gtk.Align.CENTER, vexpand=True, spacing=12,
        )
        no_bat_icon = Gtk.Image(
            icon_name="battery-missing-symbolic", pixel_size=64,
            opacity=0.5)
        no_bat_label = Gtk.Label(label="No battery detected")
        no_bat_label.add_css_class("title-2")
        no_bat_label.set_opacity(0.5)
        self.no_battery_box.append(no_bat_icon)
        self.no_battery_box.append(no_bat_label)
        self.no_battery_box.set_visible(False)

        clamp.set_child(content)
        scrolled.set_child(clamp)

        # Stack to switch between battery present / no battery
        self.main_stack = Gtk.Stack()
        self.main_stack.add_named(scrolled, "battery")
        self.main_stack.add_named(self.no_battery_box, "no_battery")
        self.append(self.main_stack)

    def load_settings(self, data):
        features = data.get("features", [])
        bat_info = data.get("battery_info", {})

        if not bat_info.get("present", False):
            self.main_stack.set_visible_child_name("no_battery")
            return

        self.main_stack.set_visible_child_name("battery")

        # Update battery status
        pct = bat_info.get("percentage", 0)
        self.bat_percentage_row.set_subtitle(f"{pct}%")
        self.bat_percentage_bar.set_value(pct)
        self.bat_status_row.set_subtitle(bat_info.get("status", "Unknown"))
        self.bat_time_row.set_subtitle(bat_info.get("time_remaining", "--") or "--")

        # Feature visibility
        self.limit_group.set_visible("battery_limiter" in features)
        self.calibration_group.set_visible("battery_calibration" in features)
        self.usb_group.set_visible("usb_charging" in features)

        # Load current values
        limiter = data.get("battery_limiter")
        if limiter is not None:
            self.limit_switch.handler_block_by_func(self._on_limit_toggled)
            self.limit_switch.set_active(limiter)
            self.limit_switch.handler_unblock_by_func(self._on_limit_toggled)

        calibrating = data.get("battery_calibration")
        if calibrating is not None:
            self._set_calibrating(calibrating)

        usb = data.get("usb_charging")
        if usb is not None:
            level_map = {"0": 0, "10": 1, "20": 2, "30": 3}
            idx = level_map.get(str(usb), 0)
            self.usb_combo.handler_block_by_func(self._on_usb_changed)
            self.usb_combo.set_selected(idx)
            self.usb_combo.handler_unblock_by_func(self._on_usb_changed)

    def _set_calibrating(self, calibrating):
        self._calibrating = calibrating
        self.calibration_status_row.set_subtitle(
            "Calibrating..." if calibrating else "Not calibrating"
        )
        self.start_cal_button.set_sensitive(not calibrating)
        self.stop_cal_button.set_sensitive(calibrating)

    def _on_limit_toggled(self, switch, *args):
        enabled = switch.get_active()

        def revert(err):
            switch.handler_block_by_func(self._on_limit_toggled)
            switch.set_active(not enabled)
            switch.handler_unblock_by_func(self._on_limit_toggled)
            self._toast(f"Battery limit toggle failed: {err}")

        async_set(self.client.set_battery_limiter, args=(enabled,),
                  on_failure=revert)

    def _on_start_calibration(self, button):
        self._set_calibrating(True)

        def revert(err):
            self._set_calibrating(False)
            self._toast(f"Could not start calibration: {err}")

        async_set(self.client.set_battery_calibration, args=(True,),
                  on_failure=revert)

    def _on_stop_calibration(self, button):
        self._set_calibrating(False)

        def revert(err):
            self._set_calibrating(True)
            self._toast(f"Could not stop calibration: {err}")

        async_set(self.client.set_battery_calibration, args=(False,),
                  on_failure=revert)

    def _on_usb_changed(self, combo, *args):
        idx = combo.get_selected()
        levels = [0, 10, 20, 30]
        level = levels[idx] if idx < len(levels) else 0
        prev_idx = self._last_usb_idx if hasattr(self, "_last_usb_idx") else idx

        def remember(_data):
            self._last_usb_idx = idx

        def revert(err):
            combo.handler_block_by_func(self._on_usb_changed)
            combo.set_selected(prev_idx)
            combo.handler_unblock_by_func(self._on_usb_changed)
            self._toast(f"USB charging level change failed: {err}")

        async_set(self.client.set_usb_charging, args=(level,),
                  on_success=remember, on_failure=revert)
