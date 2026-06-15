"""
Main application window with tab navigation.
"""

import json
import logging
import subprocess
import time

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib, Gdk

import os
import threading

from archer.client import ArcherClient

logger = logging.getLogger("archer-gui")
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


class ArcherWindow(Adw.ApplicationWindow):
    def __init__(self, **kwargs):
        super().__init__(
            default_width=1000,
            default_height=700,
            title="Archer",
            **kwargs,
        )

        self.client = ArcherClient()
        self.settings_data = None
        self._monitoring_timer = None
        self._stale_check_timer = None
        self._telemetry_signal_match = None
        self._audio_signal_match = None
        self._last_telemetry_ts = 0.0
        # Mark "stale" if no signal arrives within STALE_AFTER_S. The daemon
        # emits every 2s, so 6s gives a 3-tick grace window.
        self._STALE_AFTER_S = 6.0
        self._is_stale = False
        # Exponential backoff for reconnect attempts. Resets to index 0 on
        # successful settings load.
        self._reconnect_steps_s = (5, 10, 20, 60)
        self._reconnect_idx = 0

        # Load CSS
        self._load_css()

        # Build UI
        self._build_ui()

        # Initial data load
        GLib.timeout_add(100, self._initial_load)

    def _load_css(self):
        css_path = os.path.join(os.path.dirname(__file__), "style.css")
        if os.path.exists(css_path):
            provider = Gtk.CssProvider()
            provider.load_from_path(css_path)
            Gtk.StyleContext.add_provider_for_display(
                Gdk.Display.get_default(),
                provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
            )

    def _build_ui(self):
        # Toast overlay for notifications
        self.toast_overlay = Adw.ToastOverlay()
        self.set_content(self.toast_overlay)

        # Main layout
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.toast_overlay.set_child(main_box)

        # Header bar with view switcher
        header = Adw.HeaderBar()
        self.view_switcher_title = Adw.ViewSwitcherTitle(title="Archer")
        header.set_title_widget(self.view_switcher_title)

        # Connection status indicator
        self.status_label = Gtk.Label(label="Connecting...")
        self.status_label.add_css_class("status-label")
        header.pack_end(self.status_label)

        main_box.append(header)

        # View stack for tab pages
        self.view_stack = Adw.ViewStack()
        self.view_stack.set_vexpand(True)
        self.view_switcher_title.set_stack(self.view_stack)

        # Bottom view switcher bar (for narrow windows)
        switcher_bar = Adw.ViewSwitcherBar(stack=self.view_stack)
        self.view_switcher_title.connect(
            "notify::title-visible",
            lambda obj, _: switcher_bar.set_reveal(obj.get_title_visible()),
        )

        # Create pages
        self.dashboard_page = DashboardPage(self.client)
        self.performance_page = PerformancePage(self.client)
        self.battery_page = BatteryPage(self.client)
        self.keyboard_page = KeyboardPage(self.client)
        self.system_page = SystemPage(self.client)
        self.internals_page = InternalsPage(self.client)
        self.display_page = DisplayPage(self.client)
        self.gamemode_page = GameModePage(self.client)
        self.audio_enhance_page = AudioEnhancePage(self.client)
        self.firmware_page = FirmwarePage(self.client)

        # Add pages to stack
        self.view_stack.add_titled_with_icon(
            self.dashboard_page, "dashboard", "Dashboard", "utilities-system-monitor-symbolic"
        )
        self.view_stack.add_titled_with_icon(
            self.performance_page, "performance", "Performance", "power-profile-performance-symbolic"
        )
        self.view_stack.add_titled_with_icon(
            self.battery_page, "battery", "Battery", "battery-symbolic"
        )
        self.view_stack.add_titled_with_icon(
            self.keyboard_page, "keyboard", "Keyboard", "input-keyboard-symbolic"
        )
        self.view_stack.add_titled_with_icon(
            self.system_page, "system", "System", "preferences-system-symbolic"
        )
        self.view_stack.add_titled_with_icon(
            self.internals_page, "internals", "Internals", "applications-engineering-symbolic"
        )
        self.view_stack.add_titled_with_icon(
            self.display_page, "display", "Display Mode", "video-display-symbolic"
        )
        self.view_stack.add_titled_with_icon(
            self.gamemode_page, "gamemode", "Game Mode", "applications-games-symbolic"
        )
        self.view_stack.add_titled_with_icon(
            self.audio_enhance_page, "audio_enhance", "Audio", "audio-input-microphone-symbolic"
        )
        self.view_stack.add_titled_with_icon(
            self.firmware_page, "firmware", "Firmware", "computer-symbolic"
        )

        main_box.append(self.view_stack)
        main_box.append(switcher_bar)

    def _initial_load(self):
        """Load initial settings from daemon."""
        thread = threading.Thread(target=self._fetch_settings, daemon=True)
        thread.start()
        return False  # Don't repeat

    def _fetch_settings(self):
        data = self.client.get_all_settings()
        GLib.idle_add(self._on_settings_loaded, data)

    def _on_settings_loaded(self, data):
        if data:
            self.settings_data = data
            self.status_label.set_label("Connected")
            self.status_label.remove_css_class("status-disconnected")
            self.status_label.add_css_class("status-connected")
            self._reconnect_idx = 0  # success — reset backoff
            self._is_stale = False   # cleared so _check_staleness re-arms cleanly

            # Push settings to all pages
            self.dashboard_page.load_settings(data)
            self.performance_page.load_settings(data)
            self.battery_page.load_settings(data)
            self.keyboard_page.load_settings(data)
            self.system_page.load_settings(data)
            self.internals_page.load_settings(data)
            self.display_page.load_settings(data)
            self.gamemode_page.load_settings(data)
            self.audio_enhance_page.load_settings(data)
            self.firmware_page.load_settings(data)

            # Start monitoring timer
            self._start_monitoring()
        else:
            self.status_label.set_label("Daemon Offline")
            self.status_label.remove_css_class("status-connected")
            self.status_label.add_css_class("status-disconnected")

            # Surface the underlying init error in a toast (one per failure)
            err = self.client.init_error
            if err:
                self.add_toast(Adw.Toast.new(f"Daemon offline: {err}"))

            # Retry with exponential backoff
            delay = self._reconnect_steps_s[
                min(self._reconnect_idx, len(self._reconnect_steps_s) - 1)
            ]
            self._reconnect_idx += 1
            GLib.timeout_add_seconds(delay, self._retry_connect)

        return False

    def _retry_connect(self):
        thread = threading.Thread(target=self._reconnect_then_fetch, daemon=True)
        thread.start()
        return False

    def _reconnect_then_fetch(self):
        # Re-handshake the D-Bus connection before re-fetching, in case the
        # daemon was restarted (which invalidates the old proxy).
        self.client.reconnect()
        self._fetch_settings()

    def _start_monitoring(self):
        """Subscribe to TelemetryUpdated and start the staleness watchdog.

        Replaces the previous polling loop, which spawned a new thread every
        2 seconds and would silently pile up zombie threads if any single
        D-Bus call hung. The daemon now pushes telemetry on its own timer.
        """
        # Drop any previous subscriptions. After a daemon restart the proxy
        # in the client is fresh, so old signal matches are dead.
        for attr in ("_telemetry_signal_match", "_audio_signal_match"):
            match = getattr(self, attr)
            if match is not None:
                try:
                    match.remove()
                except Exception:
                    pass
                setattr(self, attr, None)

        iface = self.client.dbus_iface
        if iface is not None:
            try:
                self._telemetry_signal_match = iface.connect_to_signal(
                    "TelemetryUpdated", self._on_telemetry_signal
                )
            except Exception as e:
                self.add_toast(
                    Adw.Toast.new(f"Telemetry signal unavailable: {e}")
                )
            try:
                self._audio_signal_match = iface.connect_to_signal(
                    "AudioEnhancementChanged", self._on_audio_changed
                )
            except Exception as e:
                logger.warning(f"AudioEnhancementChanged subscribe failed: {e}")

        # Mark "fresh" so the first stale-check tick after subscribe doesn't
        # immediately flip to "Stale".
        self._last_telemetry_ts = time.monotonic()

        if self._stale_check_timer is None:
            # Check more often than the staleness window so the flip is
            # observed within ~1s of crossing it.
            self._stale_check_timer = GLib.timeout_add_seconds(
                1, self._check_staleness
            )

    def _on_telemetry_signal(self, payload):
        """Called from the GLib main loop when the daemon emits."""
        try:
            data = json.loads(str(payload))
        except (ValueError, TypeError):
            return
        self._last_telemetry_ts = time.monotonic()
        if self._is_stale:
            self._is_stale = False
            self.status_label.set_label("Connected")
            self.status_label.remove_css_class("status-disconnected")
            self.status_label.add_css_class("status-connected")
        self.dashboard_page.update_monitoring(data)

    def _on_audio_changed(self, enabled):
        """Restart pipewire in this process's user session.

        The daemon runs as root, so it can't poke the user's user-systemd
        instance. Doing the restart here means the noise-suppression file
        rename actually takes effect.
        """
        try:
            subprocess.Popen(
                ["systemctl", "--user", "restart", "pipewire.service"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except Exception as e:
            logger.warning(f"pipewire restart failed: {e}")
            self.add_toast(
                Adw.Toast.new(f"Could not restart pipewire: {e}")
            )
            return
        msg = ("Noise suppression enabled — restarting pipewire."
               if enabled else
               "Noise suppression disabled — restarting pipewire.")
        self.add_toast(Adw.Toast.new(msg))

    def _check_staleness(self):
        """Flip the status label to 'Stale' if no signal for STALE_AFTER_S."""
        if self._last_telemetry_ts == 0.0:
            return True
        if time.monotonic() - self._last_telemetry_ts > self._STALE_AFTER_S:
            if not self._is_stale:
                self._is_stale = True
                self.status_label.set_label("Stale")
                self.status_label.remove_css_class("status-connected")
                self.status_label.add_css_class("status-disconnected")
                # Schedule a reconnect attempt using the same backoff path.
                self._reconnect_idx = 0
                GLib.timeout_add_seconds(
                    self._reconnect_steps_s[0], self._retry_connect
                )
        return True

    def add_toast(self, toast):
        """Show a toast notification."""
        self.toast_overlay.add_toast(toast)
