"""
Archer GUI Application entry point.
Supports system tray via D-Bus StatusNotifierItem (close-to-tray behavior).
"""

import logging

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio

from archer.window import ArcherWindow

logger = logging.getLogger("archer-gui")

# Try to load the D-Bus tray module. Failure is non-fatal — the app still
# runs without tray, but we log the reason so users can find it in
# `journalctl --user -t archer-gui` if needed.
HAS_TRAY = False
_TRAY_IMPORT_ERROR = None
try:
    from archer.tray import StatusNotifierItem
    HAS_TRAY = True
except Exception as e:
    _TRAY_IMPORT_ERROR = f"{e}"
    logger.warning(f"Tray module unavailable: {e}")


class ArcherApplication(Adw.Application):
    def __init__(self):
        super().__init__(
            application_id="io.github.archer.gui",
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS,
        )
        self.window = None
        self._tray = None
        self._tray_error = _TRAY_IMPORT_ERROR
        self._tray_warned = False

    def do_startup(self):
        Adw.Application.do_startup(self)
        # Keep the app alive even when all windows are hidden
        self.hold()

        if HAS_TRAY:
            try:
                self._tray = StatusNotifierItem(
                    on_activate=self._tray_open,
                    on_quit=self._tray_exit,
                )
                self._tray.start()
            except Exception as e:
                self._tray = None
                self._tray_error = f"{e}"
                logger.warning(f"Tray registration failed: {e}")

    def do_activate(self):
        if not self.window:
            self.window = ArcherWindow(application=self)
            self.window.connect("close-request", self._on_close_request)
        self.window.present()

        # Surface tray init failure once via a toast so the user knows the
        # close-to-tray hint is bogus on this session.
        if self._tray is None and self._tray_error and not self._tray_warned:
            self._tray_warned = True
            self.window.add_toast(
                Adw.Toast.new(f"System tray unavailable: {self._tray_error}")
            )

    def _on_close_request(self, window):
        """Hide window instead of destroying it (minimize to tray)."""
        if self._tray is not None:
            window.set_visible(False)
            return True  # Prevent window destruction
        # No tray available — quit normally
        return False

    def _tray_open(self):
        """Re-present the main window from tray."""
        if self.window:
            self.window.set_visible(True)
            self.window.present()
        else:
            self.do_activate()

    def _tray_exit(self):
        """Fully quit the application."""
        if self._tray:
            self._tray.stop()
            self._tray = None
        self.release()
        self.quit()
