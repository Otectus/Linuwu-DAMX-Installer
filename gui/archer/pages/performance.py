"""
Performance & Power management page.

Thermal profile selection, fan control modes, and power-source awareness.
"""

import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib

from archer.widgets.async_set import async_set


# Mapping from UI label to daemon profile string.
_PROFILES = [
    ("Eco", "leaf-symbolic", "low-power"),
    ("Quiet", "audio-volume-muted-symbolic", "quiet"),
    ("Balanced", "media-playlist-shuffle-symbolic", "balanced"),
    ("Performance", "speedometer-symbolic", "balanced-performance"),
    ("Turbo", "rocket-symbolic", "performance"),
]

_FAN_MODES = ["Automatic", "Maximum", "Manual"]


class PerformancePage(Gtk.Box):
    """Thermal profile and fan-control page."""

    def __init__(self, client):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.client = client

        # State
        self._current_profile = "balanced"
        self._available_profiles = []
        self._on_ac = True

        # --- scrollable wrapper ---
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        self.append(scrolled)

        clamp = Adw.Clamp()
        clamp.set_maximum_size(900)
        scrolled.set_child(clamp)

        content = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=24,
        )
        content.set_margin_top(24)
        content.set_margin_bottom(24)
        content.set_margin_start(12)
        content.set_margin_end(12)
        clamp.set_child(content)

        # -------------------------------------------------------
        # 1. Power Source Section
        # -------------------------------------------------------
        self._power_group = Adw.PreferencesGroup(title="Power Source")
        content.append(self._power_group)

        self._power_row = Adw.SwitchRow(title="AC Power")
        self._power_row.set_subtitle("Plugged in")
        self._power_row.set_active(True)
        self._power_row.set_sensitive(False)  # read-only display
        self._power_group.add(self._power_row)

        # -------------------------------------------------------
        # 2. Thermal Profile Section
        # -------------------------------------------------------
        self._profile_group = Adw.PreferencesGroup(title="Performance Profile")
        content.append(self._profile_group)

        # Horizontal box of toggle buttons
        self._profile_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=8,
            homogeneous=True,
        )
        self._profile_box.set_margin_top(4)
        self._profile_box.set_margin_bottom(4)
        self._profile_group.add(self._profile_box)

        self._profile_buttons: dict[str, Gtk.ToggleButton] = {}

        for label, icon_name, daemon_key in _PROFILES:
            btn_content = Adw.ButtonContent()
            btn_content.set_icon_name(icon_name)
            btn_content.set_label(label)

            btn = Gtk.ToggleButton()
            btn.set_child(btn_content)
            btn.add_css_class("profile-button")
            btn.connect("toggled", self._on_profile_toggled, daemon_key)

            self._profile_box.append(btn)
            self._profile_buttons[daemon_key] = btn

        # -------------------------------------------------------
        # 3. Fan Control Section
        # -------------------------------------------------------
        self._fan_group = Adw.PreferencesGroup(title="Fan Control")
        content.append(self._fan_group)

        # Mode selector
        self._fan_mode_row = Adw.ComboRow(title="Fan Mode")
        fan_model = Gtk.StringList()
        for mode in _FAN_MODES:
            fan_model.append(mode)
        self._fan_mode_row.set_model(fan_model)
        self._fan_mode_row.connect("notify::selected", self._on_fan_mode_changed)
        self._fan_group.add(self._fan_mode_row)

        # Manual speed controls (initially hidden)
        self._manual_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=12,
        )
        self._manual_box.set_margin_top(12)
        self._manual_box.set_visible(False)
        self._fan_group.add(self._manual_box)

        # CPU fan slider
        cpu_label = Gtk.Label(label="CPU Fan Speed", xalign=0)
        cpu_label.add_css_class("heading")
        self._manual_box.append(cpu_label)

        self._cpu_scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, 0, 100, 1
        )
        self._cpu_scale.set_draw_value(True)
        self._cpu_scale.set_value_pos(Gtk.PositionType.RIGHT)
        self._cpu_scale.set_hexpand(True)
        # Add percentage marks
        for mark in (0, 25, 50, 75, 100):
            self._cpu_scale.add_mark(mark, Gtk.PositionType.BOTTOM, f"{mark}%")
        self._manual_box.append(self._cpu_scale)

        # GPU fan slider
        gpu_label = Gtk.Label(label="GPU Fan Speed", xalign=0)
        gpu_label.add_css_class("heading")
        self._manual_box.append(gpu_label)

        self._gpu_scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, 0, 100, 1
        )
        self._gpu_scale.set_draw_value(True)
        self._gpu_scale.set_value_pos(Gtk.PositionType.RIGHT)
        self._gpu_scale.set_hexpand(True)
        for mark in (0, 25, 50, 75, 100):
            self._gpu_scale.add_mark(mark, Gtk.PositionType.BOTTOM, f"{mark}%")
        self._manual_box.append(self._gpu_scale)

        # Apply button
        self._apply_fan_btn = Gtk.Button(label="Apply")
        self._apply_fan_btn.add_css_class("suggested-action")
        self._apply_fan_btn.set_halign(Gtk.Align.END)
        self._apply_fan_btn.connect("clicked", self._on_apply_fan_clicked)
        self._manual_box.append(self._apply_fan_btn)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_settings(self, data):
        """Populate the page from a full settings dict returned by the daemon."""
        features = data.get("features", [])

        # Show or hide entire sections based on feature support
        has_thermal = "thermal_profiles" in features
        has_fan = "fan_control" in features

        self._profile_group.set_visible(has_thermal)
        self._fan_group.set_visible(has_fan)

        # Power source
        self._on_ac = data.get("power_source_ac", True)
        self._power_row.set_active(self._on_ac)
        self._power_row.set_title("AC Power" if self._on_ac else "Battery")
        self._power_row.set_subtitle(
            "Plugged in" if self._on_ac else "Running on battery"
        )

        # Thermal profiles
        if has_thermal:
            self._available_profiles = data.get("thermal_choices", [])
            self._current_profile = data.get("thermal_profile", "balanced")
            self._update_profile_buttons()

        # Fan control
        if has_fan:
            cpu_speed = data.get("fan_speed_cpu", 0)
            gpu_speed = data.get("fan_speed_gpu", 0)

            # Determine initial mode from reported speeds
            if cpu_speed == 0 and gpu_speed == 0:
                self._fan_mode_row.set_selected(0)  # Automatic
            elif cpu_speed == 100 and gpu_speed == 100:
                self._fan_mode_row.set_selected(1)  # Maximum
            else:
                self._fan_mode_row.set_selected(2)  # Manual
                self._cpu_scale.set_value(cpu_speed)
                self._gpu_scale.set_value(gpu_speed)

            self._sync_manual_visibility()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _toast(self, message):
        win = self.get_root()
        if win is not None and hasattr(win, "add_toast"):
            win.add_toast(Adw.Toast.new(message))

    def _refresh_after_change(self):
        """Re-fetch all settings from the daemon and reload the page."""

        def _fetch():
            data = self.client.get_all_settings()
            if data:
                GLib.idle_add(self.load_settings, data)

        threading.Thread(target=_fetch, daemon=True).start()

    def _update_profile_buttons(self):
        """Sync toggle button state and visibility with current data."""
        # Suppress signal handling while we programmatically toggle buttons
        self._updating_profiles = True
        try:
            for daemon_key, btn in self._profile_buttons.items():
                # Visibility rules based on power source
                visible = daemon_key in self._available_profiles
                if visible:
                    if daemon_key == "low-power":
                        # Eco only visible on battery
                        visible = not self._on_ac
                    elif daemon_key in ("quiet", "balanced-performance", "performance"):
                        # Quiet, Performance, Turbo only on AC
                        visible = self._on_ac

                btn.set_visible(visible)

                # Active state
                is_active = daemon_key == self._current_profile
                btn.set_active(is_active)
                if is_active:
                    btn.add_css_class("profile-button-active")
                else:
                    btn.remove_css_class("profile-button-active")
        finally:
            self._updating_profiles = False

    def _sync_manual_visibility(self):
        """Show manual sliders only when Manual mode is selected."""
        selected = self._fan_mode_row.get_selected()
        self._manual_box.set_visible(selected == 2)

    # ------------------------------------------------------------------
    # Signal handlers
    # ------------------------------------------------------------------

    _updating_profiles = False

    def _on_profile_toggled(self, button, daemon_key):
        """Handle a profile toggle button press."""
        if self._updating_profiles:
            return

        if not button.get_active():
            # A button was de-selected; if it's the current one, re-select it
            # (radio behaviour: clicking the active button should not deselect).
            if daemon_key == self._current_profile:
                self._updating_profiles = True
                button.set_active(True)
                self._updating_profiles = False
            return

        previous_profile = self._current_profile

        # De-select all other buttons (radio behaviour)
        self._updating_profiles = True
        for key, btn in self._profile_buttons.items():
            if key != daemon_key:
                btn.set_active(False)
                btn.remove_css_class("profile-button-active")
        button.add_css_class("profile-button-active")
        self._updating_profiles = False

        self._current_profile = daemon_key

        def revert(err):
            # Restore the previously-active profile and resync the buttons.
            self._current_profile = previous_profile
            self._update_profile_buttons()
            self._toast(f"Could not change profile: {err}")

        async_set(self.client.set_thermal_profile, args=(daemon_key,),
                  on_success=lambda _d: self._refresh_after_change(),
                  on_failure=revert)

    def _on_fan_mode_changed(self, combo_row, _pspec):
        """React to the fan mode combo-row changing."""
        self._sync_manual_visibility()

        selected = combo_row.get_selected()

        if selected == 0:
            self._apply_fan_speed(0, 0)       # Automatic
        elif selected == 1:
            self._apply_fan_speed(100, 100)   # Maximum
        # Manual: wait for user to press Apply

    def _on_apply_fan_clicked(self, _button):
        """Send manual fan speeds to the daemon."""
        cpu = int(self._cpu_scale.get_value())
        gpu = int(self._gpu_scale.get_value())
        self._apply_fan_speed(cpu, gpu)

    def _apply_fan_speed(self, cpu, gpu):
        async_set(self.client.set_fan_speed, args=(cpu, gpu),
                  on_success=lambda _d: self._refresh_after_change(),
                  on_failure=lambda err: (self._toast(f"Fan change failed: {err}"),
                                          self._refresh_after_change()))
