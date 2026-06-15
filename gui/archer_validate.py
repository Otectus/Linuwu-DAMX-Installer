"""
Input validation helpers for the Archer D-Bus service.

These run inside the root daemon on every mutating D-Bus call, so they must
treat all incoming parameters as untrusted: any local user can reach the bus
(authorization is a separate polkit gate). Kept free of GTK/GLib imports so it
can be imported headlessly by the D-Bus smoke test and unit tests.

Convention: every validator returns a ``(value, error)`` tuple. On success
``error`` is ``None``; on failure ``value`` is ``None`` and ``error`` is a
short human-readable message safe to surface to the GUI.
"""

import json
import re

_HEX_COLOR_RE = re.compile(r"^[0-9a-fA-F]{1,6}$")

# Allowed USB charging levels (percent). 0 disables off-state charging.
USB_CHARGING_LEVELS = (0, 10, 20, 30)


def parse_json_object(raw):
    """Parse a JSON string that must decode to an object (dict).

    Returns (dict, None) on success or (None, error) when the payload is not
    valid JSON or is not a JSON object.
    """
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return None, "Invalid request payload (not valid JSON)"
    if not isinstance(data, dict):
        return None, "Invalid request payload (expected a JSON object)"
    return data, None


def validate_int_range(value, lo, hi, name="value"):
    """Coerce ``value`` to int and require lo <= n <= hi."""
    try:
        n = int(value)
    except (ValueError, TypeError):
        return None, f"Invalid {name} (not an integer)"
    if n < lo or n > hi:
        return None, f"Invalid {name} {n} (expected {lo}..{hi})"
    return n, None


def validate_choice(value, choices, name="value"):
    """Require ``value`` to be one of ``choices``."""
    if value not in choices:
        allowed = ", ".join(str(c) for c in choices)
        return None, f"Invalid {name} {value!r} (allowed: {allowed})"
    return value, None


def validate_hex_color(value, name="color"):
    """Require a bare 1-6 digit hex color string (no leading '#')."""
    if not isinstance(value, str) or not _HEX_COLOR_RE.match(value):
        return None, f"Invalid {name} (expected hex like 'ff8800')"
    return value, None


def validate_fan_speed(cpu, gpu):
    """Validate a (cpu, gpu) fan-speed pair, each 0..100 percent."""
    cpu, err = validate_int_range(cpu, 0, 100, "cpu fan speed")
    if err:
        return None, err
    gpu, err = validate_int_range(gpu, 0, 100, "gpu fan speed")
    if err:
        return None, err
    return (cpu, gpu), None


def validate_per_zone(params):
    """Validate a per-zone keyboard payload dict.

    Expects zone1..zone4 hex colors and brightness 0..100.
    Returns ((z1, z2, z3, z4, brightness), None) or (None, error).
    """
    zones = []
    for key in ("zone1", "zone2", "zone3", "zone4"):
        if key not in params:
            return None, f"Missing keyboard zone '{key}'"
        z, err = validate_hex_color(params[key], key)
        if err:
            return None, err
        zones.append(z)
    brightness, err = validate_int_range(params.get("brightness", 100), 0, 100, "brightness")
    if err:
        return None, err
    return (zones[0], zones[1], zones[2], zones[3], brightness), None


def validate_four_zone(params):
    """Validate a four-zone effect payload dict.

    Returns ((mode, speed, brightness, direction, r, g, b), None) or (None, error).
    """
    mode, err = validate_int_range(params.get("mode", 0), 0, 15, "effect mode")
    if err:
        return None, err
    speed, err = validate_int_range(params.get("speed", 0), 0, 9, "effect speed")
    if err:
        return None, err
    brightness, err = validate_int_range(params.get("brightness", 100), 0, 100, "brightness")
    if err:
        return None, err
    direction, err = validate_int_range(params.get("direction", 2), 1, 2, "direction")
    if err:
        return None, err
    channels = []
    for key in ("red", "green", "blue"):
        c, err = validate_int_range(params.get(key, 0), 0, 255, key)
        if err:
            return None, err
        channels.append(c)
    return (mode, speed, brightness, direction, channels[0], channels[1], channels[2]), None


def validate_fan_curve_points(points):
    """Validate a fan-curve point list: each entry (temp 0..120, pct 0..100)."""
    if not isinstance(points, list):
        return None, "Invalid fan curve (expected a list of points)"
    clean = []
    for entry in points:
        if not isinstance(entry, (list, tuple)) or len(entry) != 2:
            return None, "Invalid fan curve point (expected [temp, percent])"
        temp, err = validate_int_range(entry[0], 0, 120, "curve temperature")
        if err:
            return None, err
        pct, err = validate_int_range(entry[1], 0, 100, "curve percent")
        if err:
            return None, err
        clean.append([temp, pct])
    return clean, None
