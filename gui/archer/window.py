"""
Main application window — sidebar Control Center.

Uses Adw.NavigationSplitView (libadwaita >= 1.4) with a sidebar, a per-page
content header, and a persistent status footer. Falls back to the classic
ViewStack + ViewSwitcher layout on older libadwaita so the app still runs.

The daemon connection / telemetry / reconnect logic is unchanged from the
previous version — only how status is *displayed* moved into a shared
StatusModel consumed by the header badge, footer, and dashboard hero.
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
from archer.widgets import status as status_mod
from archer.widgets.status_footer import StatusFooter

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

# NavigationSplitView landed in libadwaita 1.4. Module-level so tests can force
# the fallback path.
_HAS_SPLIT_VIEW = hasattr(Adw, "NavigationSplitView")

# (page name, sidebar/header title, symbolic icon)
_PAGE_NAV = [
    ("dashboard", "Dashboard", "utilities-system-monitor-symbolic"),
    ("performance", "Performance", "power-profile-performance-symbolic"),
    ("battery", "Battery", "battery-symbolic"),
    ("keyboard", "Keyboard", "input-keyboard-symbolic"),
    ("system", "System", "preferences-system-symbolic"),
    ("display", "Display Mode", "video-display-symbolic"),
    ("gamemode", "Game Mode", "applications-games-symbolic"),
    ("audio_enhance", "Audio", "audio-input-microphone-symbolic"),
    ("firmware", "Firmware", "computer-symbolic"),
    ("internals", "Internals", "applications-engineering-symbolic"),
]


class ArcherWindow(Adw.ApplicationWindow):
    def __init__(self, **kwargs):
        super().__init__(
            default_width=1040,
            default_height=720,
            title="Archer",
            **kwargs,
        )

        self.client = ArcherClient()
        self.status = status_mod.StatusModel()
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

        self._titles = {name: title for name, title, _ in _PAGE_NAV}

        # Load CSS
        self._load_css()

        # Build UI
        self._build_ui()

        # Initial data load
        GLib.timeout_add(100, self._initial_load)

    def _load_css(self):
        css_path = os.path.join(os.path.dirname(__file__), "style.css")
        display = Gdk.Display.get_default()
        if os.path.exists(css_path) and display is not None:
            provider = Gtk.CssProvider()
            provider.load_from_path(css_path)
            Gtk.StyleContext.add_provider_for_display(
                display,
                provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
            )

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self):
        self.toast_overlay = Adw.ToastOverlay()
        self.set_content(self.toast_overlay)

        self.status_footer = StatusFooter()

        # The page stack is shared by both layouts.
        self.view_stack = Adw.ViewStack()
        self.view_stack.set_vexpand(True)
        self._create_pages()

        # Status label shown in the content header (kept under the same
        # attribute name the monitoring code already uses).
        self.status_label = Gtk.Label(label="Connecting…")
        self.status_label.add_css_class("status-label")

        if _HAS_SPLIT_VIEW:
            self._build_split_view()
        else:
            self._build_fallback_view()

    def _create_pages(self):
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

        self._pages = {
            "dashboard": self.dashboard_page,
            "performance": self.performance_page,
            "battery": self.battery_page,
            "keyboard": self.keyboard_page,
            "system": self.system_page,
            "internals": self.internals_page,
            "display": self.display_page,
            "gamemode": self.gamemode_page,
            "audio_enhance": self.audio_enhance_page,
            "firmware": self.firmware_page,
        }
        for name, title, icon in _PAGE_NAV:
            self.view_stack.add_titled_with_icon(self._pages[name], name, title, icon)

    def _build_split_view(self):
        # --- Sidebar ---
        self.sidebar_list = Gtk.ListBox()
        self.sidebar_list.add_css_class("navigation-sidebar")
        self.sidebar_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self._sidebar_rows = {}
        for name, title, icon in _PAGE_NAV:
            row = Gtk.ListBoxRow()
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12,
                          margin_top=8, margin_bottom=8, margin_start=8, margin_end=8)
            box.append(Gtk.Image(icon_name=icon))
            label = Gtk.Label(label=title, xalign=0)
            box.append(label)
            row.set_child(box)
            row._page_name = name
            row.set_tooltip_text(title)
            row.update_property([Gtk.AccessibleProperty.LABEL], [title])
            self.sidebar_list.append(row)
            self._sidebar_rows[name] = row
        self.sidebar_list.connect("row-selected", self._on_sidebar_selected)

        sidebar_scroll = Gtk.ScrolledWindow(
            hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        sidebar_scroll.set_child(self.sidebar_list)

        sidebar_toolbar = Adw.ToolbarView()
        sidebar_header = Adw.HeaderBar()
        sidebar_header.set_title_widget(
            Adw.WindowTitle(title="Archer", subtitle="Control Center"))
        sidebar_toolbar.add_top_bar(sidebar_header)
        sidebar_toolbar.set_content(sidebar_scroll)
        sidebar_page = Adw.NavigationPage(title="Archer", child=sidebar_toolbar)

        # --- Content ---
        content_toolbar = Adw.ToolbarView()
        self.content_header = Adw.HeaderBar()
        self.content_title = Adw.WindowTitle(title="Dashboard", subtitle="")
        self.content_header.set_title_widget(self.content_title)
        self.content_header.pack_end(self.status_label)
        content_toolbar.add_top_bar(self.content_header)
        content_toolbar.set_content(self.view_stack)
        content_toolbar.add_bottom_bar(self.status_footer)
        self.content_page = Adw.NavigationPage(title="Dashboard", child=content_toolbar)

        self.split_view = Adw.NavigationSplitView()
        self.split_view.set_sidebar(sidebar_page)
        self.split_view.set_content(self.content_page)
        self.toast_overlay.set_child(self.split_view)

        # Select the first page.
        self.sidebar_list.select_row(self._sidebar_rows["dashboard"])

    def _build_fallback_view(self):
        """Classic ViewStack + ViewSwitcher layout for libadwaita < 1.4."""
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.toast_overlay.set_child(main_box)

        header = Adw.HeaderBar()
        self.view_switcher_title = Adw.ViewSwitcherTitle(title="Archer")
        self.view_switcher_title.set_stack(self.view_stack)
        header.set_title_widget(self.view_switcher_title)
        header.pack_end(self.status_label)
        main_box.append(header)

        switcher_bar = Adw.ViewSwitcherBar(stack=self.view_stack)
        self.view_switcher_title.connect(
            "notify::title-visible",
            lambda obj, _: switcher_bar.set_reveal(obj.get_title_visible()),
        )

        main_box.append(self.view_stack)
        main_box.append(switcher_bar)
        main_box.append(self.status_footer)

    def _on_sidebar_selected(self, _listbox, row):
        if row is None:
            return
        name = row._page_name
        self.view_stack.set_visible_child_name(name)
        title = self._titles.get(name, "Archer")
        self.content_title.set_title(title)
        self.content_page.set_title(title)
        # Collapse to content on narrow/mobile layouts.
        if hasattr(self, "split_view"):
            self.split_view.set_show_content(True)

    # ------------------------------------------------------------------
    # Status display
    # ------------------------------------------------------------------
    def _set_connection(self, state):
        """Single place that updates the header badge, footer, and hero."""
        self.status.connection = state
        self.status_label.set_label(self.status.connection_label)
        ok = state == status_mod.CONNECTED
        self.status_label.remove_css_class("status-connected")
        self.status_label.remove_css_class("status-disconnected")
        self.status_label.add_css_class(
            "status-connected" if ok else "status-disconnected")
        self.status_footer.update(self.status)
        self.dashboard_page.update_status(self.status)

    # ------------------------------------------------------------------
    # Data loading / monitoring
    # ------------------------------------------------------------------
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
            self.status.update_from_settings(data)
            self._reconnect_idx = 0  # success — reset backoff
            self._is_stale = False   # cleared so _check_staleness re-arms cleanly
            self._set_connection(status_mod.CONNECTED)

            # Push settings to all pages
            for page in self._pages.values():
                page.load_settings(data)

            # Start monitoring timer
            self._start_monitoring()
        else:
            self._set_connection(status_mod.OFFLINE)

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

        The daemon pushes telemetry on its own timer; the GUI only listens.
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
            self._set_connection(status_mod.CONNECTED)
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
                self._set_connection(status_mod.STALE)
                # Schedule a reconnect attempt using the same backoff path.
                self._reconnect_idx = 0
                GLib.timeout_add_seconds(
                    self._reconnect_steps_s[0], self._retry_connect
                )
        return True

    def add_toast(self, toast):
        """Show a toast notification."""
        self.toast_overlay.add_toast(toast)
