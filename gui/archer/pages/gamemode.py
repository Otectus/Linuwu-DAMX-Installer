"""
Game Mode page - one-click toggle for maximum gaming performance.
"""

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw

from archer.widgets.async_set import async_set
from archer.widgets.capability_row import set_group_supported
from archer.widgets.toast import make_toast


class GameModePage(Gtk.Box):
    """Game Mode toggle page."""

    def __init__(self, client):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.client = client
        self._active = False
        self._build_ui()

    def _build_ui(self):
        scrolled = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        clamp = Adw.Clamp(maximum_size=900, margin_top=24, margin_bottom=24,
                          margin_start=12, margin_end=12)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)

        # --- Status Card ---
        self._status_group = Adw.PreferencesGroup(title="Game Mode")

        # Big toggle row
        self._toggle_row = Adw.SwitchRow(
            title="Enable Game Mode",
            subtitle="Inactive",
        )
        self._toggle_row.connect("notify::active", self._on_toggle_changed)
        self._status_group.add(self._toggle_row)

        # Status badge row
        self._badge_row = Adw.ActionRow(title="Status")
        self._badge_label = Gtk.Label(label="INACTIVE")
        self._badge_label.add_css_class("dim-label")
        self._badge_label.set_valign(Gtk.Align.CENTER)
        self._badge_row.add_suffix(self._badge_label)
        self._status_group.add(self._badge_row)

        content.append(self._status_group)

        # --- Info Section ---
        info_group = Adw.PreferencesGroup(
            title="What Game Mode Does",
            description="Game Mode optimizes your system for maximum gaming performance.",
        )

        effects = [
            ("power-profile-performance-symbolic",
             "Performance Profile",
             "Sets the thermal profile to maximum performance."),
            ("battery-full-charged-symbolic",
             "Energy Policy",
             "Switches CPU energy policy to performance mode."),
            ("applications-games-symbolic",
             "NVIDIA Persistence",
             "Enables NVIDIA persistence mode to reduce GPU initialization latency."),
            ("speedometer-symbolic",
             "CPU Governor",
             "Sets CPU frequency governor to performance for consistent clock speeds."),
        ]

        for icon, title, subtitle in effects:
            row = Adw.ActionRow(title=title, subtitle=subtitle)
            row.add_prefix(Gtk.Image(icon_name=icon))
            info_group.add(row)

        content.append(info_group)

        # --- Warnings ---
        warning_group = Adw.PreferencesGroup(title="Notes")

        warning_row = Adw.ActionRow(
            title="Increased Power Consumption",
            subtitle="Game Mode significantly increases power usage and heat output. "
                     "Use on AC power for best results.",
            icon_name="dialog-warning-symbolic",
        )
        warning_row.add_css_class("warning")
        warning_group.add(warning_row)

        content.append(warning_group)

        clamp.set_child(content)
        scrolled.set_child(clamp)
        self.append(scrolled)

    def load_settings(self, data):
        features = data.get("features", [])
        has_game_mode = "game_mode" in features

        set_group_supported(
            self._status_group, has_game_mode,
            "Game Mode needs the Archer daemon's performance integration "
            "(thermal profile + CPU governor support).")

        if has_game_mode:
            active = data.get("game_mode", False)
            self._set_active_state(active, update_switch=True)

    def _set_active_state(self, active, update_switch=False):
        """Update UI to reflect game mode state."""
        self._active = active

        if update_switch:
            self._toggle_row.handler_block_by_func(self._on_toggle_changed)
            self._toggle_row.set_active(active)
            self._toggle_row.handler_unblock_by_func(self._on_toggle_changed)

        self._toggle_row.set_subtitle("Active" if active else "Inactive")

        if active:
            self._badge_label.set_label("ACTIVE")
            self._badge_label.remove_css_class("dim-label")
            self._badge_label.add_css_class("success")
        else:
            self._badge_label.set_label("INACTIVE")
            self._badge_label.remove_css_class("success")
            self._badge_label.add_css_class("dim-label")

    def _toast(self, message):
        win = self.get_root()
        if win is not None and hasattr(win, "add_toast"):
            win.add_toast(make_toast(message))

    def _on_toggle_changed(self, switch, *args):
        enabled = switch.get_active()
        self._set_active_state(enabled)

        def revert(err):
            self._set_active_state(not enabled, update_switch=True)
            self._toast(f"Could not toggle game mode: {err}")

        async_set(self.client.set_game_mode, args=(enabled,), on_failure=revert)
