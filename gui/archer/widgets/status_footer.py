"""
Persistent status footer — a slim bar pinned to the bottom of the window
showing daemon connection, driver presence, reboot-required, and the daemon
version. Bound to the shared StatusModel so it never disagrees with the header
badge or the dashboard hero.
"""

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk


def _dot(label_text):
    box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    dot = Gtk.Label(label="●")
    dot.add_css_class("status-dot")
    text = Gtk.Label(label=label_text)
    text.add_css_class("caption")
    box.append(dot)
    box.append(text)
    return box, dot, text


class StatusFooter(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=18)
        self.add_css_class("status-footer")
        self.set_margin_top(6)
        self.set_margin_bottom(6)
        self.set_margin_start(12)
        self.set_margin_end(12)

        self._daemon_box, self._daemon_dot, self._daemon_text = _dot("Daemon")
        self._driver_box, self._driver_dot, self._driver_text = _dot("Driver")
        self.append(self._daemon_box)
        self.append(self._driver_box)

        # Reboot indicator (hidden unless required).
        self._reboot_box, self._reboot_dot, self._reboot_text = _dot("Reboot required")
        self._reboot_box.set_visible(False)
        self.append(self._reboot_box)

        spacer = Gtk.Box(hexpand=True)
        self.append(spacer)

        self._version_label = Gtk.Label(label="")
        self._version_label.add_css_class("caption")
        self._version_label.add_css_class("dim-label")
        self.append(self._version_label)

    def update(self, status):
        # Daemon
        self._daemon_text.set_label(f"Daemon: {status.connection_label}")
        _set_dot(self._daemon_dot, "ok" if status.is_ok else "bad")

        # Driver
        if not status.is_ok:
            self._driver_text.set_label("Driver: —")
            _set_dot(self._driver_dot, "neutral")
        elif status.driver_loaded:
            self._driver_text.set_label("Driver: loaded")
            _set_dot(self._driver_dot, "ok")
        else:
            self._driver_text.set_label("Driver: not loaded")
            _set_dot(self._driver_dot, "warn")

        # Reboot
        self._reboot_box.set_visible(bool(status.reboot_required))
        if status.reboot_required:
            _set_dot(self._reboot_dot, "warn")

        self._version_label.set_label(
            f"Archer {status.daemon_version}" if status.daemon_version else ""
        )


def _set_dot(dot, state):
    for cls in ("dot-ok", "dot-bad", "dot-warn", "dot-neutral"):
        dot.remove_css_class(cls)
    dot.add_css_class(f"dot-{state}")
