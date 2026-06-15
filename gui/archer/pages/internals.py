"""
Internals Manager page - debug tools, driver parameters, restart controls.
"""

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw

import threading


class InternalsPage(Gtk.Box):
    def __init__(self, client):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.client = client
        self._build_ui()

    def _build_ui(self):
        scrolled = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        clamp = Adw.Clamp(maximum_size=900, margin_top=24, margin_bottom=24,
                          margin_start=12, margin_end=12)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)

        # Warning banner
        warning_banner = Adw.Banner(
            title="These options are for advanced users and debugging. Incorrect use may require a reboot.",
            revealed=True,
        )
        content.append(warning_banner)

        # --- One-time Driver Parameters ---
        onetime_group = Adw.PreferencesGroup(
            title="One-Time Driver Parameters",
            description="Load the Linuwu-Sense driver with specific parameters. "
                        "These are cleared on next restart.",
        )

        onetime_buttons = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL, spacing=12,
            halign=Gtk.Align.CENTER, margin_top=8, margin_bottom=8,
        )

        btn_nitro = Gtk.Button(label="Load as Nitro")
        btn_nitro.add_css_class("suggested-action")
        btn_nitro.connect("clicked", self._on_force_nitro)
        onetime_buttons.append(btn_nitro)

        btn_predator = Gtk.Button(label="Load as Predator")
        btn_predator.add_css_class("suggested-action")
        btn_predator.connect("clicked", self._on_force_predator)
        onetime_buttons.append(btn_predator)

        btn_all = Gtk.Button(label="Enable All Features")
        btn_all.connect("clicked", self._on_force_enable_all)
        onetime_buttons.append(btn_all)

        onetime_row = Adw.PreferencesRow()
        onetime_inner = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            margin_start=12, margin_end=12, margin_bottom=12)
        onetime_inner.append(onetime_buttons)
        onetime_row.set_child(onetime_inner)
        onetime_group.add(onetime_row)

        content.append(onetime_group)

        # --- Permanent Model Override ---
        permanent_group = Adw.PreferencesGroup(
            title="Permanent Model Override",
            description="Persist a modprobe parameter across reboots via /etc/modprobe.d/linuwu-sense.conf.",
        )

        self.override_combo = Adw.ComboRow(title="Override Mode")
        override_model = Gtk.StringList.new([
            "Disabled",
            "Force Nitro Model (nitro_v4)",
            "Force Predator Model (predator_v4)",
            "Force Enable All (enable_all)",
        ])
        self.override_combo.set_model(override_model)
        self.override_combo.set_selected(0)
        permanent_group.add(self.override_combo)

        apply_override_btn = Gtk.Button(
            label="Apply Override", halign=Gtk.Align.CENTER,
            margin_top=8, margin_bottom=8)
        apply_override_btn.add_css_class("suggested-action")
        apply_override_btn.connect("clicked", self._on_apply_override)
        override_row = Adw.PreferencesRow()
        override_inner = Gtk.Box(
            margin_start=12, margin_end=12, margin_bottom=12,
            halign=Gtk.Align.CENTER)
        override_inner.append(apply_override_btn)
        override_row.set_child(override_inner)
        permanent_group.add(override_row)

        content.append(permanent_group)

        # --- Service Controls ---
        service_group = Adw.PreferencesGroup(
            title="Service Controls",
            description="Restart the daemon or reload drivers.",
        )

        restart_daemon_row = Adw.ActionRow(
            title="Restart Daemon",
            subtitle="Restarts the Archer daemon service without reloading drivers.",
            activatable=True,
        )
        restart_daemon_btn = Gtk.Button(
            label="Restart", valign=Gtk.Align.CENTER,
        )
        restart_daemon_btn.connect("clicked", self._on_restart_daemon)
        restart_daemon_row.add_suffix(restart_daemon_btn)
        service_group.add(restart_daemon_row)

        restart_all_row = Adw.ActionRow(
            title="Restart Drivers & Daemon",
            subtitle="Fully reloads the Linuwu-Sense kernel module and restarts the daemon.",
            activatable=True,
        )
        restart_all_btn = Gtk.Button(
            label="Full Restart", valign=Gtk.Align.CENTER,
        )
        restart_all_btn.add_css_class("destructive-action")
        restart_all_btn.connect("clicked", self._on_restart_drivers)
        restart_all_row.add_suffix(restart_all_btn)
        service_group.add(restart_all_row)

        content.append(service_group)

        # --- Connection Info ---
        self.conn_group = Adw.PreferencesGroup(title="Connection")

        self.conn_status_row = Adw.ActionRow(
            title="Daemon D-Bus", subtitle="io.otectus.Archer1 (system bus)"
        )
        self.conn_group.add(self.conn_status_row)

        self.conn_type_row = Adw.ActionRow(title="Laptop Type", subtitle="--")
        self.conn_group.add(self.conn_type_row)

        self.conn_features_row = Adw.ActionRow(title="Feature Count", subtitle="--")
        self.conn_group.add(self.conn_features_row)

        content.append(self.conn_group)

        clamp.set_child(content)
        scrolled.set_child(clamp)
        self.append(scrolled)

    def load_settings(self, data):
        laptop_type = data.get("laptop_type", "unknown")
        features = data.get("features", [])

        self.conn_type_row.set_subtitle(laptop_type.title())
        self.conn_features_row.set_subtitle(str(len(features)))

    def _send_threaded(self, func, *args):
        threading.Thread(target=func, args=args, daemon=True).start()

    def _on_force_nitro(self, button):
        self._send_threaded(self.client.set_modprobe_parameter, "nitro_v4")
        self._show_toast("Loading with nitro_v4 parameter...")

    def _on_force_predator(self, button):
        self._send_threaded(self.client.set_modprobe_parameter, "predator_v4")
        self._show_toast("Loading with predator_v4 parameter...")

    def _on_force_enable_all(self, button):
        self._send_threaded(self.client.set_modprobe_parameter, "enable_all")
        self._show_toast("Loading with enable_all parameter...")

    def _on_apply_override(self, button):
        idx = self.override_combo.get_selected()
        params = [None, "nitro_v4", "predator_v4", "enable_all"]
        if idx == 0:
            self._send_threaded(self.client.remove_modprobe_parameter)
            self._show_toast("Override removed.")
        else:
            param = params[idx]
            self._send_threaded(self.client.set_modprobe_parameter, param)
            self._show_toast(f"Override set: {param}")

    def _on_restart_daemon(self, button):
        self._send_threaded(self.client.restart_daemon)
        self._show_toast("Daemon restart requested...")

    def _on_restart_drivers(self, button):
        self._send_threaded(self.client.restart_drivers_and_daemon)
        self._show_toast("Full driver & daemon restart requested...")

    def _show_toast(self, message):
        """Show a toast notification in the window."""
        window = self.get_root()
        if window and hasattr(window, "add_toast"):
            toast = Adw.Toast(title=message, timeout=3)
            window.add_toast(toast)
