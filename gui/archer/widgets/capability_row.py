"""
Capability-aware control helpers.

Instead of silently hiding controls the daemon or hardware can't support, these
keep them visible but disabled (insensitive) and annotate *why* — as a subtitle
and tooltip — so users understand what their hardware lacks rather than seeing
a mysteriously empty page.
"""


def set_row_supported(row, supported, reason=None, base_subtitle=None):
    """Enable/disable an Adw row, explaining the reason when unsupported.

    row           — an Adw.ActionRow / SwitchRow / ComboRow (anything with
                    set_sensitive + set_tooltip_text; subtitle is optional).
    supported     — bool.
    reason        — text shown (subtitle + tooltip) when not supported.
    base_subtitle — subtitle to restore when supported (if the row has one).
    """
    row.set_sensitive(bool(supported))
    if supported:
        row.set_tooltip_text(None)
        if base_subtitle is not None and hasattr(row, "set_subtitle"):
            row.set_subtitle(base_subtitle)
    else:
        msg = reason or "Not supported on this hardware."
        row.set_tooltip_text(msg)
        if hasattr(row, "set_subtitle"):
            row.set_subtitle(msg)


def set_group_supported(group, supported, reason=None):
    """Dim an entire Adw.PreferencesGroup and annotate the reason via tooltip.

    Keeps the group visible (so users still see the capability exists) but
    insensitive when unsupported. Returns ``supported`` for convenient chaining.
    """
    group.set_sensitive(bool(supported))
    group.set_tooltip_text(None if supported else (reason or "Not supported on this hardware."))
    return bool(supported)
