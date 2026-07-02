"""
Dashboard page – real-time system monitoring overview.
"""

from collections import deque

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw

from archer.widgets.hero import HeroSummary

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
TEMP_MAX = 110
USAGE_MAX = 100
HISTORY_LEN = 60

CHART_BG = (0x1A / 255, 0x1A / 255, 0x2E / 255)  # #1a1a2e
CHART_GRID = (1.0, 1.0, 1.0, 0.12)
CHART_CPU_COLOR = (0.35, 0.55, 1.0)   # blue
CHART_GPU_COLOR = (1.0, 0.35, 0.35)   # red
CHART_LABEL_COLOR = (1.0, 1.0, 1.0, 0.7)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_card(title):
    """Create a card frame with a title and inner content box.

    Returns (outer_frame, content_box).
    """
    frame = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
    frame.add_css_class("card")

    content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    content.add_css_class("card-content")
    content.set_margin_top(16)
    content.set_margin_bottom(16)
    content.set_margin_start(16)
    content.set_margin_end(16)

    heading = Gtk.Label(label=title, xalign=0)
    heading.add_css_class("title-4")
    content.append(heading)

    frame.append(content)
    return frame, content


def _make_metric_row(label_text, max_value):
    """Create a labelled level bar row.

    Returns (row_box, value_label, level_bar).
    """
    row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)

    top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
    name_label = Gtk.Label(label=label_text, xalign=0)
    name_label.set_hexpand(True)
    value_label = Gtk.Label(label="--", xalign=1)
    value_label.add_css_class("caption")
    top.append(name_label)
    top.append(value_label)

    bar = Gtk.LevelBar()
    bar.set_min_value(0)
    bar.set_max_value(max_value)
    bar.set_value(0)
    bar.set_size_request(-1, 10)
    # Remove default GTK offset marks so our own classes dominate
    bar.remove_offset_value(Gtk.LEVEL_BAR_OFFSET_LOW)
    bar.remove_offset_value(Gtk.LEVEL_BAR_OFFSET_HIGH)
    bar.remove_offset_value(Gtk.LEVEL_BAR_OFFSET_FULL)

    row.append(top)
    row.append(bar)
    return row, value_label, bar


def _make_big_label(initial="--"):
    """Create a large text label used for hero numbers."""
    lbl = Gtk.Label(label=initial)
    lbl.add_css_class("title-1")
    return lbl


def _apply_temp_class(bar, temp):
    """Set the appropriate CSS class on a temperature level bar."""
    for cls in ("temp-low", "temp-medium", "temp-high"):
        bar.remove_css_class(cls)
    if temp < 50:
        bar.add_css_class("temp-low")
    elif temp <= 75:
        bar.add_css_class("temp-medium")
    else:
        bar.add_css_class("temp-high")


# ---------------------------------------------------------------------------
# DashboardPage
# ---------------------------------------------------------------------------

class DashboardPage(Gtk.Box):
    """Overview / monitoring tab."""

    def __init__(self, client):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.client = client

        # Temperature history buffers
        self.cpu_temp_history = deque([0] * HISTORY_LEN, maxlen=HISTORY_LEN)
        self.gpu_temp_history = deque([0] * HISTORY_LEN, maxlen=HISTORY_LEN)

        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self):
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        self.append(scrolled)

        clamp = Adw.Clamp()
        clamp.set_maximum_size(900)
        clamp.set_margin_top(24)
        clamp.set_margin_bottom(24)
        clamp.set_margin_start(12)
        clamp.set_margin_end(12)
        scrolled.set_child(clamp)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        clamp.set_child(outer)

        # --- 0. Hero summary (one-glance health) ---
        self.hero = HeroSummary()
        outer.append(self.hero)

        # --- 1. CPU Card ---
        self._build_cpu_card(outer)

        # --- 2. GPU Section (one card per detected GPU) ---
        self._build_gpu_section(outer)

        # --- 3. Fan Status Card ---
        self._build_fan_card(outer)

        # --- 4. Battery Card ---
        self._build_battery_card(outer)

        # --- 5. Temperature History Chart ---
        self._build_temp_chart(outer)

    # ---- CPU ----
    def _build_cpu_card(self, parent):
        card, content = _make_card("CPU")

        self.cpu_model_label = Gtk.Label(label="--", xalign=0, wrap=True)
        self.cpu_model_label.add_css_class("dim-label")
        content.append(self.cpu_model_label)

        row_temp, self.cpu_temp_label, self.cpu_temp_bar = _make_metric_row(
            "Temperature", TEMP_MAX
        )
        content.append(row_temp)

        row_usage, self.cpu_usage_label, self.cpu_usage_bar = _make_metric_row(
            "Usage", USAGE_MAX
        )
        content.append(row_usage)

        parent.append(card)

    # ---- GPU ----
    def _build_gpu_section(self, parent):
        """Container for per-GPU cards. Cards are (re)built in load_settings
        once the detected GPU list is known (this runs before any data)."""
        self.gpu_section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        parent.append(self.gpu_section)
        self._gpu_cards = []        # one refs dict per rendered card
        self._gpus_built_key = None  # signature of the gpus list last built

    def _build_one_gpu_card(self, gpu):
        """Build a single GPU card. Returns (card_widget, refs_dict)."""
        kind = gpu.get("kind") or ""
        title = f"GPU ({kind.capitalize()})" if kind else "GPU"
        card, content = _make_card(title)

        model_label = Gtk.Label(
            label=gpu.get("model", "Unknown GPU"), xalign=0, wrap=True
        )
        model_label.add_css_class("dim-label")
        content.append(model_label)

        row_temp, temp_label, temp_bar = _make_metric_row("Temperature", TEMP_MAX)
        content.append(row_temp)
        row_usage, usage_label, usage_bar = _make_metric_row("Usage", USAGE_MAX)
        content.append(row_usage)

        return card, {
            "vendor": gpu.get("vendor", "unknown"),
            "temp_label": temp_label, "temp_bar": temp_bar,
            "usage_label": usage_label, "usage_bar": usage_bar,
        }

    def _rebuild_gpu_cards(self, system):
        """(Re)build GPU cards from system_info. Idempotent — only rebuilds
        when the detected GPU set actually changes."""
        gpus = system.get("gpus")
        if not gpus:
            # Back-compat: synthesize a single card from the flat gpu_model.
            gpus = [{"vendor": "unknown",
                     "model": system.get("gpu_model", "Unknown GPU"),
                     "kind": ""}]

        key = tuple((g.get("vendor"), g.get("model"), g.get("kind")) for g in gpus)
        if key == self._gpus_built_key:
            return
        self._gpus_built_key = key

        child = self.gpu_section.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self.gpu_section.remove(child)
            child = nxt
        self._gpu_cards = []

        for gpu in gpus:
            card, refs = self._build_one_gpu_card(gpu)
            self.gpu_section.append(card)
            self._gpu_cards.append(refs)

    # ---- Fans ----
    def _build_fan_card(self, parent):
        card, content = _make_card("Fan Status")

        fan_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=24)
        fan_row.set_halign(Gtk.Align.CENTER)

        # CPU fan
        cpu_fan_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        cpu_fan_box.set_halign(Gtk.Align.CENTER)
        cpu_fan_title = Gtk.Label(label="CPU Fan")
        cpu_fan_title.add_css_class("dim-label")
        self.cpu_fan_label = _make_big_label("-- RPM")
        cpu_fan_box.append(cpu_fan_title)
        cpu_fan_box.append(self.cpu_fan_label)

        # GPU fan
        gpu_fan_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        gpu_fan_box.set_halign(Gtk.Align.CENTER)
        gpu_fan_title = Gtk.Label(label="GPU Fan")
        gpu_fan_title.add_css_class("dim-label")
        self.gpu_fan_label = _make_big_label("-- RPM")
        gpu_fan_box.append(gpu_fan_title)
        gpu_fan_box.append(self.gpu_fan_label)

        fan_row.append(cpu_fan_box)
        fan_row.append(gpu_fan_box)
        content.append(fan_row)

        parent.append(card)

    # ---- Battery ----
    def _build_battery_card(self, parent):
        card, content = _make_card("Battery")

        self.battery_not_present_label = Gtk.Label(
            label="No battery detected", xalign=0
        )
        self.battery_not_present_label.add_css_class("dim-label")
        self.battery_not_present_label.set_visible(False)
        content.append(self.battery_not_present_label)

        self.battery_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        content.append(self.battery_box)

        # Percentage hero
        self.battery_pct_label = _make_big_label("--%")
        self.battery_pct_label.set_halign(Gtk.Align.CENTER)
        self.battery_box.append(self.battery_pct_label)

        # Status
        status_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        status_name = Gtk.Label(label="Status", xalign=0)
        status_name.set_hexpand(True)
        self.battery_status_label = Gtk.Label(label="--", xalign=1)
        self.battery_status_label.add_css_class("caption")
        status_row.append(status_name)
        status_row.append(self.battery_status_label)
        self.battery_box.append(status_row)

        # Time remaining
        time_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        time_name = Gtk.Label(label="Time Remaining", xalign=0)
        time_name.set_hexpand(True)
        self.battery_time_label = Gtk.Label(label="--", xalign=1)
        self.battery_time_label.add_css_class("caption")
        time_row.append(time_name)
        time_row.append(self.battery_time_label)
        self.battery_box.append(time_row)

        # Level bar
        self.battery_bar = Gtk.LevelBar()
        self.battery_bar.set_min_value(0)
        self.battery_bar.set_max_value(100)
        self.battery_bar.set_value(0)
        self.battery_bar.set_size_request(-1, 10)
        self.battery_box.append(self.battery_bar)

        parent.append(card)

    # ---- Temperature Chart ----
    def _build_temp_chart(self, parent):
        card, content = _make_card("Temperature History")

        # Legend row
        legend = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        legend.set_halign(Gtk.Align.CENTER)
        legend.set_margin_bottom(4)

        cpu_legend = Gtk.Label(label="\u25CF CPU")
        cpu_legend.add_css_class("caption")
        # We can't easily color individual labels without CSS, but the chart
        # itself carries the colour coding.
        gpu_legend = Gtk.Label(label="\u25CF GPU")
        gpu_legend.add_css_class("caption")

        legend.append(cpu_legend)
        legend.append(gpu_legend)
        content.append(legend)

        self.chart_area = Gtk.DrawingArea()
        self.chart_area.set_content_height(200)
        self.chart_area.set_content_width(800)
        self.chart_area.set_draw_func(self._draw_chart)
        content.append(self.chart_area)

        parent.append(card)

    # ------------------------------------------------------------------
    # Cairo chart drawing
    # ------------------------------------------------------------------
    def _draw_chart(self, area, cr, width, height):
        """Draw CPU/GPU temperature history as a line chart with Cairo."""
        if width < 1 or height < 1:
            return

        pad_left = 44
        pad_right = 12
        pad_top = 12
        pad_bottom = 24
        chart_w = width - pad_left - pad_right
        chart_h = height - pad_top - pad_bottom

        if chart_w < 1 or chart_h < 1:
            return

        # Background
        cr.set_source_rgb(*CHART_BG)
        cr.rectangle(0, 0, width, height)
        cr.fill()

        # Chart area clip
        cr.save()
        cr.rectangle(pad_left, pad_top, chart_w, chart_h)
        cr.clip()

        # Horizontal grid lines (every 20 degrees, 0-110)
        cr.set_source_rgba(*CHART_GRID)
        cr.set_line_width(0.5)
        for temp in range(0, TEMP_MAX + 1, 20):
            y = pad_top + chart_h - (temp / TEMP_MAX) * chart_h
            cr.move_to(pad_left, y)
            cr.line_to(pad_left + chart_w, y)
            cr.stroke()

        # Draw data lines
        def _draw_line(data, color):
            cr.set_source_rgb(*color)
            cr.set_line_width(1.8)
            points = list(data)
            n = len(points)
            if n < 2:
                return
            step = chart_w / (n - 1)
            for i, val in enumerate(points):
                x = pad_left + i * step
                y = pad_top + chart_h - (val / TEMP_MAX) * chart_h
                if i == 0:
                    cr.move_to(x, y)
                else:
                    cr.line_to(x, y)
            cr.stroke()

        _draw_line(self.cpu_temp_history, CHART_CPU_COLOR)
        _draw_line(self.gpu_temp_history, CHART_GPU_COLOR)

        cr.restore()  # undo clip

        # Y-axis labels
        cr.set_source_rgba(*CHART_LABEL_COLOR)
        cr.select_font_face("sans-serif", 0, 0)
        cr.set_font_size(10)
        for temp in range(0, TEMP_MAX + 1, 20):
            y = pad_top + chart_h - (temp / TEMP_MAX) * chart_h
            text = f"{temp}\u00b0"
            extents = cr.text_extents(text)
            cr.move_to(pad_left - extents.width - 6, y + extents.height / 2)
            cr.show_text(text)

        # X-axis labels (time ticks – most recent on right)
        for i in range(0, HISTORY_LEN, 10):
            x = pad_left + (i / (HISTORY_LEN - 1)) * chart_w
            seconds_ago = (HISTORY_LEN - 1 - i) * 2  # polling is 2 s
            text = f"-{seconds_ago}s"
            extents = cr.text_extents(text)
            cr.move_to(x - extents.width / 2, height - 4)
            cr.show_text(text)

    # ------------------------------------------------------------------
    # Public API – called from window
    # ------------------------------------------------------------------
    def update_status(self, status):
        """Forward the shared status model to the hero badges."""
        self.hero.update_status(status)

    def load_settings(self, data):
        """Populate static info from the initial settings fetch."""
        self.hero.load_settings(data)
        system = data.get("system_info", {})
        self.cpu_model_label.set_label(system.get("cpu_model", "Unknown CPU"))
        self._rebuild_gpu_cards(system)

        # Battery
        bat = data.get("battery_info", {})
        present = bat.get("present", False)
        if not present:
            self.battery_not_present_label.set_visible(True)
            self.battery_box.set_visible(False)
        else:
            self.battery_not_present_label.set_visible(False)
            self.battery_box.set_visible(True)
            self._update_battery(bat)

        # Fan RPM (initial values may come with settings)
        cpu_rpm = data.get("fan_rpm_cpu", 0)
        gpu_rpm = data.get("fan_rpm_gpu", 0)
        self.cpu_fan_label.set_label(f"{cpu_rpm} RPM")
        self.gpu_fan_label.set_label(f"{gpu_rpm} RPM")

    def update_monitoring(self, data):
        """Refresh all live gauges. Called on the main thread via
        GLib.idle_add from the polling loop.
        """
        self.hero.update_monitoring(data)
        # CPU
        cpu_temp = data.get("cpu_temp", 0)
        cpu_usage = data.get("cpu_usage", 0)
        self.cpu_temp_label.set_label(f"{cpu_temp:.0f} \u00b0C")
        self.cpu_temp_bar.set_value(min(cpu_temp, TEMP_MAX))
        _apply_temp_class(self.cpu_temp_bar, cpu_temp)

        self.cpu_usage_label.set_label(f"{cpu_usage:.0f}%")
        self.cpu_usage_bar.set_value(min(cpu_usage, USAGE_MAX))

        # GPU(s)
        gpu_temp = data.get("gpu_temp", 0)
        gpus_tel = data.get("gpus")
        if gpus_tel is not None and self._gpu_cards:
            # Daemon emits gpus in the same (discrete-first) order as
            # system_info, so index-align; fall back to a vendor match.
            for idx, refs in enumerate(self._gpu_cards):
                self._apply_gpu_card(refs, self._match_gpu_tel(gpus_tel, refs["vendor"], idx))
        elif self._gpu_cards:
            # Back-compat: single card from the flat fields.
            self._apply_gpu_card(self._gpu_cards[0],
                                 {"temp": data.get("gpu_temp"),
                                  "usage": data.get("gpu_usage")})

        # Fans
        cpu_rpm = data.get("fan_rpm_cpu", 0)
        gpu_rpm = data.get("fan_rpm_gpu", 0)
        self.cpu_fan_label.set_label(f"{cpu_rpm} RPM")
        self.gpu_fan_label.set_label(f"{gpu_rpm} RPM")

        # Battery (may or may not be present in monitoring payload)
        bat = data.get("battery_info")
        if bat is not None:
            self._update_battery(bat)

        # History
        self.cpu_temp_history.append(cpu_temp)
        self.gpu_temp_history.append(gpu_temp)
        self.chart_area.queue_draw()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _match_gpu_tel(gpus_tel, vendor, idx):
        """Find the telemetry entry for a card by vendor, falling back to the
        positional entry."""
        for g in gpus_tel:
            if g.get("vendor") == vendor:
                return g
        return gpus_tel[idx] if idx < len(gpus_tel) else {}

    @staticmethod
    def _apply_gpu_card(refs, tel):
        """Apply a {temp, usage} telemetry dict to one GPU card's widgets.
        None values (no sensor) render as 'N/A' with the bar at zero."""
        temp = tel.get("temp")
        usage = tel.get("usage")
        if temp is None:
            refs["temp_label"].set_label("N/A")
            refs["temp_bar"].set_value(0)
            _apply_temp_class(refs["temp_bar"], 0)
        else:
            refs["temp_label"].set_label(f"{temp:.0f} °C")
            refs["temp_bar"].set_value(min(temp, TEMP_MAX))
            _apply_temp_class(refs["temp_bar"], temp)
        if usage is None:
            refs["usage_label"].set_label("N/A")
            refs["usage_bar"].set_value(0)
        else:
            refs["usage_label"].set_label(f"{usage:.0f}%")
            refs["usage_bar"].set_value(min(usage, USAGE_MAX))

    def _update_battery(self, bat):
        pct = bat.get("percentage", 0)
        status = bat.get("status", "--")
        time_remaining = bat.get("time_remaining", "--")

        self.battery_pct_label.set_label(f"{pct:.0f}%")
        self.battery_status_label.set_label(str(status).capitalize())
        self.battery_time_label.set_label(str(time_remaining))
        self.battery_bar.set_value(min(max(pct, 0), 100))
