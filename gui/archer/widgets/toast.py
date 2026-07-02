"""
Shared factory for Adw.Toast.

Adw.Toast renders its title as Pango markup by default, so any toast whose
text contains a literal ``&`` (or ``<``) aborts rendering with:

    Failed to set text '…' from markup … escape ampersand as &amp;

Archer's toasts are plain status strings — several interpolate arbitrary
error text (``f"Could not restart pipewire: {e}"``) that can legitimately
contain those characters. Routing every toast through ``make_toast`` and
disabling markup once removes the whole class of bug.
"""

from gi.repository import Adw


def make_toast(message, *, timeout=None):
    """Build an Adw.Toast that displays ``message`` verbatim (no markup).

    timeout — optional auto-dismiss in seconds; omitted leaves the libadwaita
    default.
    """
    toast = Adw.Toast.new(message)
    toast.set_use_markup(False)
    if timeout is not None:
        toast.set_timeout(timeout)
    return toast
