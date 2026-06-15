"""
Confirmation dialogs for risky daemon actions.

Uses Adw.AlertDialog (libadwaita >= 1.5) when available, falling back to
Adw.MessageDialog on older runtimes, so a "Restart drivers" or "Start
calibration" click always prompts before doing something disruptive.
"""

import gi

gi.require_version("Adw", "1")
from gi.repository import Adw


def _appearance(kind):
    if kind == "suggested":
        return Adw.ResponseAppearance.SUGGESTED
    return Adw.ResponseAppearance.DESTRUCTIVE


def confirm_action(parent, heading, body, confirm_label, on_confirm,
                   kind="destructive"):
    """Prompt the user; invoke ``on_confirm()`` only if they accept.

    parent        — any widget in the window (used to anchor the dialog).
    kind          — "destructive" (default) or "suggested" styling.
    """
    def _on_response(_dialog, response):
        if response == "confirm":
            on_confirm()

    if hasattr(Adw, "AlertDialog"):
        dialog = Adw.AlertDialog(heading=heading, body=body)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("confirm", confirm_label)
        dialog.set_response_appearance("confirm", _appearance(kind))
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.connect("response", _on_response)
        dialog.present(parent)
    else:  # libadwaita < 1.5
        window = parent.get_root() if hasattr(parent, "get_root") else None
        dialog = Adw.MessageDialog(
            transient_for=window, heading=heading, body=body, modal=True,
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("confirm", confirm_label)
        dialog.set_response_appearance("confirm", _appearance(kind))
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.connect("response", _on_response)
        dialog.present()
