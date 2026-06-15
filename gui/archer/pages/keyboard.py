"""
Keyboard Lighting page — 4-zone RGB control and effects.

Per-zone colour picking, effect modes, and a backlight timeout toggle.
"""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Gdk

from archer.widgets.async_set import async_set


# ── helpers ──────────────────────────────────────────────────────────

def _hex_to_rgba(hex_str: str) -> Gdk.RGBA:
    """Parse '#rrggbb' into a Gdk.RGBA (alpha=1.0)."""
    rgba = Gdk.RGBA()
    rgba.parse(hex_str)
    return rgba


def _rgba_to_hex(rgba: Gdk.RGBA) -> str:
    """Convert a Gdk.RGBA to a '#rrggbb' hex string."""
    r = int(rgba.red * 255)
    g = int(rgba.green * 255)
    b = int(rgba.blue * 255)
    return "#{:02x}{:02x}{:02x}".format(r, g, b)


def _rgba_to_rgb_tuple(rgba: Gdk.RGBA):
    """Return (r, g, b) as 0-255 ints."""
    return (
        int(rgba.red * 255),
        int(rgba.green * 255),
        int(rgba.blue * 255),
    )


def _make_color_button(default_hex: str) -> Gtk.ColorDialogButton:
    """Create a ColorDialogButton pre-set to *default_hex*."""
    dialog = Gtk.ColorDialog()
    button = Gtk.ColorDialogButton(dialog=dialog)
    button.set_rgba(_hex_to_rgba(default_hex))
    return button


# ── page ─────────────────────────────────────────────────────────────

class KeyboardPage(Gtk.Box):
    """Keyboard lighting settings page."""

    def __init__(self, client):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.client = client

        # ── scrolled window + clamp ──────────────────────────────────
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.append(scrolled)

        clamp = Adw.Clamp(maximum_size=900)
        scrolled.set_child(clamp)

        content = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=24,
            margin_top=24,
            margin_bottom=24,
            margin_start=12,
            margin_end=12,
        )
        clamp.set_child(content)

        # ─────────────────────────────────────────────────────────────
        # 1.  Zone Colors
        # ─────────────────────────────────────────────────────────────
        self.zone_group = Adw.PreferencesGroup(title="Zone Colors")
        content.append(self.zone_group)

        zone_defaults = ["#4287f5", "#ff5733", "#33ff57", "#ffff01"]
        self.zone_buttons: list[Gtk.ColorDialogButton] = []

        grid = Gtk.Grid(
            column_spacing=24,
            row_spacing=12,
            halign=Gtk.Align.CENTER,
        )

        for i, default_hex in enumerate(zone_defaults):
            row, col = divmod(i, 2)

            label = Gtk.Label(label=f"Zone {i + 1}", halign=Gtk.Align.START)
            btn = _make_color_button(default_hex)
            self.zone_buttons.append(btn)

            grid.attach(label, col * 2, row, 1, 1)
            grid.attach(btn, col * 2 + 1, row, 1, 1)

        self.zone_group.add(grid)

        # Brightness slider
        brightness_label = Gtk.Label(
            label="Brightness",
            halign=Gtk.Align.START,
            margin_top=12,
        )
        self.zone_group.add(brightness_label)

        self.brightness_scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, 0, 100, 1,
        )
        self.brightness_scale.set_value(100)
        for mark in (0, 25, 50, 75, 100):
            self.brightness_scale.add_mark(
                mark, Gtk.PositionType.BOTTOM, str(mark),
            )
        self.brightness_scale.set_draw_value(True)
        self.zone_group.add(self.brightness_scale)

        # Apply button
        apply_zones_btn = Gtk.Button(
            label="Apply Zone Colors",
            halign=Gtk.Align.END,
            margin_top=8,
        )
        apply_zones_btn.add_css_class("suggested-action")
        apply_zones_btn.connect("clicked", self._on_apply_zones)
        self.zone_group.add(apply_zones_btn)

        # ─────────────────────────────────────────────────────────────
        # 2.  Lighting Effects
        # ─────────────────────────────────────────────────────────────
        self.effects_group = Adw.PreferencesGroup(title="Lighting Effects")
        content.append(self.effects_group)

        # Effect mode combo
        effect_modes = Gtk.StringList.new([
            "Static", "Breathing", "Neon", "Wave",
            "Shifting", "Zoom", "Meteor", "Twinkling",
        ])
        self.effect_mode_row = Adw.ComboRow(
            title="Effect Mode",
            model=effect_modes,
        )
        self.effects_group.add(self.effect_mode_row)

        # Speed scale
        speed_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        speed_label = Gtk.Label(label="Speed", halign=Gtk.Align.START)
        speed_box.append(speed_label)

        self.speed_scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, 0, 9, 1,
        )
        self.speed_scale.set_round_digits(0)
        self.speed_scale.set_draw_value(True)
        self.speed_scale.set_value(5)
        speed_box.append(self.speed_scale)
        self.effects_group.add(speed_box)

        # Effect colour
        color_box = Gtk.Box(spacing=12, margin_top=4)
        color_label = Gtk.Label(label="Color", halign=Gtk.Align.START)
        color_box.append(color_label)
        self.effect_color_btn = _make_color_button("#0000ff")
        color_box.append(self.effect_color_btn)
        self.effects_group.add(color_box)

        # Direction combo
        direction_model = Gtk.StringList.new([
            "Left to Right", "Right to Left",
        ])
        self.direction_row = Adw.ComboRow(
            title="Direction",
            model=direction_model,
        )
        self.effects_group.add(self.direction_row)

        # Apply effect button
        apply_effect_btn = Gtk.Button(
            label="Apply Effect",
            halign=Gtk.Align.END,
            margin_top=8,
        )
        apply_effect_btn.add_css_class("suggested-action")
        apply_effect_btn.connect("clicked", self._on_apply_effect)
        self.effects_group.add(apply_effect_btn)

        # ─────────────────────────────────────────────────────────────
        # 3.  Backlight Timeout
        # ─────────────────────────────────────────────────────────────
        self.backlight_group = Adw.PreferencesGroup(title="Backlight")
        content.append(self.backlight_group)

        self.backlight_row = Adw.SwitchRow(
            title="Auto-off after 30 seconds of inactivity",
        )
        self.backlight_row.connect("notify::active", self._on_backlight_toggled)
        self.backlight_group.add(self.backlight_row)

    # ── load settings from daemon ────────────────────────────────────

    def load_settings(self, data):
        """
        Apply initial state from daemon settings.

        *data* is the dict returned by ``ArcherClient.get_all_settings()``.
        """
        features = data.get("features", [])

        # Show/hide zone colours
        has_per_zone = "keyboard_per_zone" in features
        self.zone_group.set_visible(has_per_zone)

        # Show/hide effects
        has_effects = "keyboard_effects" in features
        self.effects_group.set_visible(has_effects)

        # Backlight timeout
        timeout_val = data.get("backlight_timeout")
        if timeout_val is not None:
            self.backlight_row.set_active(bool(timeout_val))

        # Restore saved keyboard settings into the UI controls
        saved = data.get("saved_settings", {})

        pz = saved.get("per_zone_mode")
        if pz and has_per_zone:
            for i, key in enumerate(("zone1", "zone2", "zone3", "zone4")):
                hex_val = pz.get(key, "")
                if hex_val:
                    self.zone_buttons[i].set_rgba(_hex_to_rgba(f"#{hex_val}"))
            brightness = pz.get("brightness")
            if brightness is not None:
                self.brightness_scale.set_value(brightness)

        effect = saved.get("four_zone_mode")
        if effect and has_effects:
            mode = effect.get("mode", 0)
            self.effect_mode_row.set_selected(mode)
            speed = effect.get("speed", 5)
            self.speed_scale.set_value(speed)
            r = effect.get("red", 0)
            g = effect.get("green", 0)
            b = effect.get("blue", 255)
            rgba = Gdk.RGBA()
            rgba.red = r / 255.0
            rgba.green = g / 255.0
            rgba.blue = b / 255.0
            rgba.alpha = 1.0
            self.effect_color_btn.set_rgba(rgba)
            direction = effect.get("direction", 2)
            self.direction_row.set_selected(0 if direction == 2 else 1)

    # ── callbacks ────────────────────────────────────────────────────

    def _toast(self, message):
        win = self.get_root()
        if win is not None and hasattr(win, "add_toast"):
            win.add_toast(Adw.Toast.new(message))

    def _on_apply_zones(self, _button):
        # Strip '#' prefix — sysfs expects bare hex like "4287f5"
        z1 = _rgba_to_hex(self.zone_buttons[0].get_rgba()).lstrip("#")
        z2 = _rgba_to_hex(self.zone_buttons[1].get_rgba()).lstrip("#")
        z3 = _rgba_to_hex(self.zone_buttons[2].get_rgba()).lstrip("#")
        z4 = _rgba_to_hex(self.zone_buttons[3].get_rgba()).lstrip("#")
        brightness = int(self.brightness_scale.get_value())

        async_set(
            self.client.set_per_zone_mode,
            args=(z1, z2, z3, z4, brightness),
            on_failure=lambda err: self._toast(f"Zone colors not applied: {err}"),
        )

    def _on_apply_effect(self, _button):
        mode = self.effect_mode_row.get_selected()
        speed = int(self.speed_scale.get_value())
        r, g, b = _rgba_to_rgb_tuple(self.effect_color_btn.get_rgba())
        brightness = int(self.brightness_scale.get_value())

        # Direction: index 0 → "Left to Right" = 2, index 1 → "Right to Left" = 1
        direction = 2 if self.direction_row.get_selected() == 0 else 1

        async_set(
            self.client.set_four_zone_mode,
            args=(mode, speed, brightness, direction, r, g, b),
            on_failure=lambda err: self._toast(f"Effect not applied: {err}"),
        )

    def _on_backlight_toggled(self, row, _pspec):
        state = row.get_active()

        def revert(err):
            row.handler_block_by_func(self._on_backlight_toggled)
            row.set_active(not state)
            row.handler_unblock_by_func(self._on_backlight_toggled)
            self._toast(f"Backlight timeout toggle failed: {err}")

        async_set(self.client.set_backlight_timeout, args=(state,),
                  on_failure=revert)
