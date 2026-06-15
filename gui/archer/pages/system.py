"""
System Settings page - LCD override, boot sound, system information.
"""

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw

import subprocess

from archer.widgets.async_set import async_set


class SystemPage(Gtk.Box):
    def __init__(self, client):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.client = client
        self._build_ui()

    def _build_ui(self):
        scrolled = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        clamp = Adw.Clamp(maximum_size=900, margin_top=24, margin_bottom=24,
                          margin_start=12, margin_end=12)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)

        # --- Display Settings ---
        self.display_group = Adw.PreferencesGroup(
            title="Display",
            description="LCD panel settings for supported models.",
        )

        self.lcd_switch = Adw.SwitchRow(
            title="LCD Override",
            subtitle="Reduces LCD latency and minimizes ghosting. May increase battery consumption.",
        )
        self.lcd_switch.connect("notify::active", self._on_lcd_toggled)
        self.display_group.add(self.lcd_switch)

        content.append(self.display_group)

        # --- Boot Settings ---
        self.boot_group = Adw.PreferencesGroup(
            title="Boot",
            description="Control startup behavior.",
        )

        self.boot_switch = Adw.SwitchRow(
            title="Boot Animation & Sound",
            subtitle="Enable Acer's startup animation and boot sound.",
        )
        self.boot_switch.connect("notify::active", self._on_boot_toggled)
        self.boot_group.add(self.boot_switch)

        content.append(self.boot_group)

        # --- System Information ---
        info_group = Adw.PreferencesGroup(title="System Information")

        self.info_model = Adw.ActionRow(title="Model", subtitle="--")
        info_group.add(self.info_model)

        self.info_vendor = Adw.ActionRow(title="Vendor", subtitle="--")
        info_group.add(self.info_vendor)

        self.info_type = Adw.ActionRow(title="Laptop Type", subtitle="--")
        info_group.add(self.info_type)

        self.info_cpu = Adw.ActionRow(title="CPU", subtitle="--")
        info_group.add(self.info_cpu)

        self.info_gpu = Adw.ActionRow(title="GPU", subtitle="--")
        info_group.add(self.info_gpu)

        self.info_kernel = Adw.ActionRow(title="Kernel", subtitle="--")
        info_group.add(self.info_kernel)

        self.info_features = Adw.ActionRow(title="Available Features", subtitle="--")
        self.info_features.set_subtitle_lines(3)
        info_group.add(self.info_features)

        content.append(info_group)

        # --- Version Information ---
        version_group = Adw.PreferencesGroup(title="Version")

        self.info_gui_version = Adw.ActionRow(title="GUI Version", subtitle="1.0.1")
        version_group.add(self.info_gui_version)

        self.info_daemon_version = Adw.ActionRow(title="Daemon Version", subtitle="--")
        version_group.add(self.info_daemon_version)

        self.info_driver_version = Adw.ActionRow(title="Driver Version", subtitle="--")
        version_group.add(self.info_driver_version)

        content.append(version_group)

        # --- Actions ---
        actions_group = Adw.PreferencesGroup(title="Actions")

        # Check for updates
        update_row = Adw.ActionRow(
            title="Check for Updates",
            subtitle="Opens the project releases page",
            activatable=True,
        )
        update_icon = Gtk.Image(icon_name="emblem-synchronizing-symbolic")
        update_row.add_suffix(update_icon)
        update_row.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
        update_row.connect("activated", self._on_check_updates)
        actions_group.add(update_row)

        # Report issue
        issue_row = Adw.ActionRow(
            title="Report an Issue",
            subtitle="Opens the project issue tracker",
            activatable=True,
        )
        issue_row.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
        issue_row.connect("activated", self._on_report_issue)
        actions_group.add(issue_row)

        # View daemon logs
        logs_row = Adw.ActionRow(
            title="View Daemon Logs",
            subtitle="/var/log/archer-daemon.log",
            activatable=True,
        )
        logs_row.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
        logs_row.connect("activated", self._on_view_logs)
        actions_group.add(logs_row)

        content.append(actions_group)

        clamp.set_child(content)
        scrolled.set_child(clamp)
        self.append(scrolled)

    def load_settings(self, data):
        features = data.get("features", [])
        sys_info = data.get("system_info", {})

        # Feature visibility
        self.display_group.set_visible("lcd_override" in features)
        self.boot_group.set_visible("boot_animation_sound" in features)

        # LCD override
        lcd = data.get("lcd_override")
        if lcd is not None:
            self.lcd_switch.handler_block_by_func(self._on_lcd_toggled)
            self.lcd_switch.set_active(lcd)
            self.lcd_switch.handler_unblock_by_func(self._on_lcd_toggled)

        # Boot animation
        boot = data.get("boot_animation_sound")
        if boot is not None:
            self.boot_switch.handler_block_by_func(self._on_boot_toggled)
            self.boot_switch.set_active(boot)
            self.boot_switch.handler_unblock_by_func(self._on_boot_toggled)

        # System info
        self.info_model.set_subtitle(sys_info.get("product_name", "--"))
        self.info_vendor.set_subtitle(sys_info.get("vendor", "--"))
        self.info_type.set_subtitle(sys_info.get("laptop_type", "--").title())
        self.info_cpu.set_subtitle(sys_info.get("cpu_model", "--") or "--")
        self.info_gpu.set_subtitle(sys_info.get("gpu_model", "--") or "--")
        self.info_kernel.set_subtitle(sys_info.get("kernel", "--"))
        self.info_features.set_subtitle(", ".join(features) if features else "None detected")

        # Versions
        self.info_daemon_version.set_subtitle(sys_info.get("daemon_version", "--"))
        self.info_driver_version.set_subtitle(sys_info.get("driver_version", "--"))

    def _on_lcd_toggled(self, switch, *args):
        enabled = switch.get_active()

        def revert(err):
            switch.handler_block_by_func(self._on_lcd_toggled)
            switch.set_active(not enabled)
            switch.handler_unblock_by_func(self._on_lcd_toggled)
            self._toast(f"LCD override toggle failed: {err}")

        async_set(self.client.set_lcd_override, args=(enabled,),
                  on_failure=revert)

    def _on_boot_toggled(self, switch, *args):
        enabled = switch.get_active()

        def revert(err):
            switch.handler_block_by_func(self._on_boot_toggled)
            switch.set_active(not enabled)
            switch.handler_unblock_by_func(self._on_boot_toggled)
            self._toast(f"Boot animation toggle failed: {err}")

        async_set(self.client.set_boot_animation_sound, args=(enabled,),
                  on_failure=revert)

    def _toast(self, message):
        win = self.get_root()
        if win is not None and hasattr(win, "add_toast"):
            win.add_toast(Adw.Toast.new(message))

    def _on_check_updates(self, row):
        try:
            subprocess.Popen(
                ["xdg-open", "https://github.com/otectus/Archer/releases"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            pass

    def _on_report_issue(self, row):
        try:
            subprocess.Popen(
                ["xdg-open", "https://github.com/otectus/Archer/issues"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            pass

    def _on_view_logs(self, row):
        log_path = "/var/log/archer-daemon.log"
        for editor in ["xdg-open", "gnome-text-editor", "kate", "xed", "mousepad", "gedit"]:
            try:
                subprocess.Popen(
                    [editor, log_path],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                return
            except FileNotFoundError:
                continue
        # Fallback: show in terminal
        try:
            subprocess.Popen(["less", log_path])
        except FileNotFoundError:
            pass
