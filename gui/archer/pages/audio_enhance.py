"""
Audio Enhancement page - noise suppression virtual audio source.
"""

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw

from archer.widgets.async_set import async_set
from archer.widgets.capability_row import set_group_supported
from archer.widgets.toast import make_toast


class AudioEnhancePage(Gtk.Box):
    """Audio enhancement controls page."""

    def __init__(self, client):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.client = client
        self._build_ui()

    def _build_ui(self):
        scrolled = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        clamp = Adw.Clamp(maximum_size=900, margin_top=24, margin_bottom=24,
                          margin_start=12, margin_end=12)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)

        # --- Noise Suppression ---
        self._noise_group = Adw.PreferencesGroup(
            title="Noise Suppression",
            description="Creates a virtual audio source that filters out "
                        "background noise from your microphone input.",
        )

        self._noise_switch = Adw.SwitchRow(
            title="Enable Noise Suppression",
            subtitle="Off",
        )
        self._noise_switch.connect("notify::active", self._on_noise_toggled)
        self._noise_group.add(self._noise_switch)

        content.append(self._noise_group)

        # --- Setup Instructions ---
        instructions_group = Adw.PreferencesGroup(
            title="How to Use",
            description="After enabling noise suppression, follow these steps "
                        "to use it in your applications.",
        )

        steps = [
            ("1. Enable noise suppression above",
             "This creates a virtual audio input device powered by RNNoise."),
            ("2. Open your application's audio settings",
             "Look for input device or microphone settings in your application."),
            ("3. Select \"Archer Noise Suppression\" as input",
             "Choose the Archer virtual device instead of your physical microphone."),
        ]

        for title, subtitle in steps:
            row = Adw.ActionRow(title=title, subtitle=subtitle)
            row.add_prefix(Gtk.Image(icon_name="emblem-documents-symbolic"))
            instructions_group.add(row)

        content.append(instructions_group)

        # --- Info ---
        info_group = Adw.PreferencesGroup(title="About")

        info_row = Adw.ActionRow(
            title="How it works",
            subtitle="Noise suppression uses a neural network (RNNoise) to filter "
                     "background noise in real time. Audio is routed from your "
                     "physical microphone through the noise filter and presented "
                     "as a virtual PipeWire/PulseAudio source.",
        )
        info_row.set_subtitle_lines(4)
        info_row.add_prefix(Gtk.Image(icon_name="audio-input-microphone-symbolic"))
        info_group.add(info_row)

        compat_row = Adw.ActionRow(
            title="Compatibility",
            subtitle="Works with any application that supports PipeWire or PulseAudio "
                     "audio input, including Discord, Zoom, OBS, and Steam voice chat.",
        )
        compat_row.set_subtitle_lines(3)
        compat_row.add_prefix(Gtk.Image(icon_name="emblem-ok-symbolic"))
        info_group.add(compat_row)

        content.append(info_group)

        clamp.set_child(content)
        scrolled.set_child(clamp)
        self.append(scrolled)

    def load_settings(self, data):
        features = data.get("features", [])
        has_audio = "audio_enhancement" in features

        set_group_supported(
            self._noise_group, has_audio,
            "Install the Audio Enhancement module to enable noise suppression.")

        if has_audio:
            noise = data.get("audio_enhancement", {})
            enabled = noise.get("noise_suppression", False)
            self._noise_switch.handler_block_by_func(self._on_noise_toggled)
            self._noise_switch.set_active(enabled)
            self._noise_switch.set_subtitle("Active" if enabled else "Off")
            self._noise_switch.handler_unblock_by_func(self._on_noise_toggled)

    def _toast(self, message):
        win = self.get_root()
        if win is not None and hasattr(win, "add_toast"):
            win.add_toast(make_toast(message))

    def _on_noise_toggled(self, switch, *args):
        enabled = switch.get_active()
        switch.set_subtitle("Active" if enabled else "Off")

        def revert(err):
            self._revert_toggle(not enabled)
            self._toast(f"Could not change noise suppression: {err}")

        async_set(self.client.set_audio_enhancement, args=(enabled,),
                  on_failure=revert)

    def _revert_toggle(self, state):
        self._noise_switch.handler_block_by_func(self._on_noise_toggled)
        self._noise_switch.set_active(state)
        self._noise_switch.set_subtitle("Active" if state else "Off")
        self._noise_switch.handler_unblock_by_func(self._on_noise_toggled)
