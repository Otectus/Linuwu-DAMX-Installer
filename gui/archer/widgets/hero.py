"""
Dashboard hero — a one-glance health summary shown at the top of the Dashboard.

Surfaces the things you'd want to check at a glance without scanning the whole
app: laptop model, current performance profile, GPU mode, live CPU/GPU temps,
battery + charge-limit, and daemon/driver/reboot status badges.
"""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk

_PROFILE_LABELS = {
    "low-power": "Eco",
    "quiet": "Quiet",
    "balanced": "Balanced",
    "balanced-performance": "Performance",
    "performance": "Turbo",
}
_MODE_LABELS = {"integrated": "Integrated", "hybrid": "Hybrid", "nvidia": "NVIDIA"}


def _stat(title):
    """A compact label/value stat chip. Returns (box, value_label)."""
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
    box.add_css_class("hero-stat")
    name = Gtk.Label(label=title, xalign=0)
    name.add_css_class("hero-stat-title")
    value = Gtk.Label(label="--", xalign=0)
    value.add_css_class("hero-stat-value")
    box.append(name)
    box.append(value)
    return box, value


class HeroSummary(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.add_css_class("card")
        self.add_css_class("hero")
        self.set_margin_bottom(4)

        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        inner.set_margin_top(16)
        inner.set_margin_bottom(16)
        inner.set_margin_start(16)
        inner.set_margin_end(16)
        self.append(inner)

        # Title row: model name + status badges.
        title_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        name_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0,
                           hexpand=True)
        self._model_label = Gtk.Label(label="Detecting…", xalign=0, wrap=True)
        self._model_label.add_css_class("title-2")
        self._sub_label = Gtk.Label(label="", xalign=0)
        self._sub_label.add_css_class("dim-label")
        name_box.append(self._model_label)
        name_box.append(self._sub_label)
        title_row.append(name_box)

        self._badge_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,
                                  spacing=6, valign=Gtk.Align.START)
        title_row.append(self._badge_box)
        inner.append(title_row)

        # Stat chips.
        stats = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=24,
                        homogeneous=True)
        stats.add_css_class("hero-stats")
        self._profile_box, self._profile_value = _stat("Profile")
        self._gpu_box, self._gpu_value = _stat("GPU Mode")
        self._cpu_box, self._cpu_value = _stat("CPU Temp")
        self._gput_box, self._gput_value = _stat("GPU Temp")
        self._bat_box, self._bat_value = _stat("Battery")
        for box in (self._profile_box, self._gpu_box, self._cpu_box,
                    self._gput_box, self._bat_box):
            stats.append(box)
        inner.append(stats)

    # -- updates --------------------------------------------------------
    def load_settings(self, data):
        sys_info = data.get("system_info", {}) or {}
        model = sys_info.get("product_name") or data.get("laptop_type") or "Unknown"
        self._model_label.set_label(str(model))
        kernel = sys_info.get("kernel", "")
        self._sub_label.set_label(f"Linux {kernel}" if kernel else "")

        profile = data.get("thermal_profile")
        self._profile_value.set_label(_PROFILE_LABELS.get(profile, "—") if profile else "—")

        mode = data.get("display_mode")
        self._gpu_value.set_label(_MODE_LABELS.get(mode, "—") if mode else "—")

        bat = data.get("battery_info", {}) or {}
        if bat.get("present"):
            pct = bat.get("percentage", 0)
            limit = " (80% limit)" if data.get("battery_limiter") else ""
            self._bat_value.set_label(f"{pct}%{limit}")
        else:
            self._bat_value.set_label("No battery")

    def update_monitoring(self, data):
        cpu = data.get("cpu_temp")
        gpu = data.get("gpu_temp")
        if cpu is not None:
            self._cpu_value.set_label(f"{cpu:.0f}°C")
        if gpu is not None:
            self._gput_value.set_label(f"{gpu:.0f}°C")
        bat = data.get("battery_info")
        if bat and bat.get("present"):
            self._bat_value.set_label(f"{bat.get('percentage', 0)}%")

    def update_status(self, status):
        # Rebuild badges from the shared status model.
        child = self._badge_box.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self._badge_box.remove(child)
            child = nxt

        self._badge_box.append(_badge(
            "Daemon", status.is_ok,
            ok_text="Daemon OK", bad_text=status.connection_label))
        self._badge_box.append(_badge(
            "Driver", status.driver_loaded,
            ok_text="Driver", bad_text="No driver", neutral=not status.is_ok))
        if status.reboot_required:
            self._badge_box.append(_badge("Reboot", False,
                                          bad_text="Reboot needed", warn=True))


def _badge(name, ok, ok_text=None, bad_text=None, neutral=False, warn=False):
    label = Gtk.Label(label=(ok_text if ok else bad_text) or name)
    label.add_css_class("status-badge")
    if warn:
        label.add_css_class("status-badge-warn")
    elif neutral:
        label.add_css_class("status-badge-neutral")
    elif ok:
        label.add_css_class("status-badge-ok")
    else:
        label.add_css_class("status-badge-bad")
    return label
