"""ENE K5130 keyboard backlight backend for Acer Predator PHN16S-71.

WHY THIS EXISTS
    On this model the ACPI-WMI path is only partially implemented in firmware.
    Verified by experiment:

        brightness  -> applied
        per-zone RGB -> stored and read back faithfully, NEVER applied
        effect mode  -> ignored

    Writing per_zone_mode through linuwu_sense therefore looks like it works
    (the sysfs read-back returns exactly what you wrote) while the keyboard
    keeps showing the factory rainbow. The colours never reach the LEDs.

    The LEDs are driven by an ENE K5130 sitting on I2C-1 at 0x50, exposed as a
    standard HID-over-I2C device (0018:0CF2:5130) with four vendor feature
    reports. Talking to it directly does work. This module implements that
    protocol; see docs/ENE_PROTOCOL.md for the full reverse-engineering notes.

PROTOCOL SUMMARY
    0xA1  4 bytes, read-only: "03 65 21 83" = device count + device ids
    0xA2  1 byte:  select device            <- MANDATORY before 0xA4
    0xA4 10 bytes: dev, mode, brightness, speed, direction, R, G, B,
                   zonemask (16-bit LE)

    Device ids: 0x21 keyboard (4 zones), 0x65 performance-mode button LED,
                0x83 lid logo. All three take colour; each has its own mode
                numbering (see MODE_* and LOGO_/BUTTON_ constants).

    Mode 2 is static colour on all three devices. The rest of the mode map
    is per device and does not carry over: on the keyboard mode 1 turns it
    off, on the button LED mode 1 does nothing and mode 6 turns it off.
    Check each device rather than assuming.

    The zone field is a bitmask of the low four bits, so zones combine:
    0x3 paints the left half in a single write. The high byte is ignored.

    Direction is encoded the OTHER WAY ROUND from Archer and the
    Linuwu-Sense docs: on the wire 1 sweeps left-to-right and 2 sweeps
    right-to-left. _to_wire_direction() does the translation.

SAFETY
    - The target is resolved by HID identity, never by hidraw number: the
      numbering is not stable across boots (the ENE's reset times out during
      probe, so it enumerates last, and the touchpad can rebind and reclaim
      hidraw0).
    - The internal keyboard and the touchpad are explicitly refused.
    - Every value is range-checked against what the HID report descriptor
      declares before anything is written.
    - The accepted mode range is per device. The keyboard takes the full
      verified range; every other device id stays capped at 7, because while
      sweeping the button LED modes >= 8 coincided with fans starting and
      stopping, so up there the report probably reaches the performance
      profile and not just the LED.
"""

import ctypes
import fcntl
import os
import signal
import threading
import time

# --- identity -------------------------------------------------------------
ENE_HID_ID = "0018:00000CF2:00005130"

# Devices that must never be opened by this module even if something goes
# wrong upstream: writing vendor feature reports to them could leave the
# machine without input.
FORBIDDEN_HID_IDS = {
    "0018:00001025:0000174B": "internal keyboard (input)",
    "0018:000006CB:0000CFE4": "Synaptics touchpad",
}

# --- device ids (from report 0xA1) ----------------------------------------
DEV_KEYBOARD = 0x21
DEV_BUTTON = 0x65
DEV_LOGO = 0x83

# --- keyboard modes, each observed against a black baseline ---------------
# Numbering is the ENE's own and does NOT match the WMI mode numbers that
# other Acer tools document. Names are matched to the effects PredatorSense
# advertises, by behaviour. Modes 8 and 10 are the least certain: 10 is read
# as Shifting because it is the one with a visible direction, matching the
# documented "shifting light effect, full control over speed, direction and
# colour", which leaves 8 as Meteor.
MODE_OFF = 1
MODE_STATIC = 2
MODE_BREATHING = 4       # smooth fade through pure colours
MODE_NEON = 5            # whole board shifts colour at once, no sweep
MODE_NEON_FAST = 6       # same, faster
MODE_WAVE = 7            # lateral rainbow (factory default)
MODE_METEOR = 8          # a point flares at random, then the board flashes
MODE_ZOOM = 9            # circular, outside inward, colour drifting
MODE_SHIFTING = 10       # light crosses and returns over a dark board
MODE_TWINKLING = 11      # two of the four segments lit at random

MODE_MAX_KEYBOARD = 12   # 13..31 produced nothing visible
MODE_MAX_OTHER = 7       # see the note on modes >= 8 in the module docstring

# --- lid logo (0x83), verified from an off baseline -----------------------
# 1 off · 2 static, honours RGB · 3 off · 4 fixed red · 5 slow cycle
# 6 fixed yellow · 7 off
LOGO_OFF = 1
LOGO_STATIC = 2

# --- performance-mode button LED (0x65) -----------------------------------
# 1 nothing · 2 static, honours RGB · 3 nothing · 4 breathing · 5 colour cycle
# 6 off · 7 nothing
#
# Mode 2 is static colour on ALL THREE devices. An earlier reading had the
# button at mode 1, which is why every write to it silently did nothing.
BUTTON_OFF = 6
BUTTON_STATIC = 2

# Colour shown on the button LED for each platform profile. The button is the
# performance-mode button, so tying it to the profile is what it is for.
#
# These are DEFAULTS CHOSEN HERE, not Acer's mapping: the only value taken
# from observed hardware is the purple on balanced-performance. Acer does not
# publish the per-mode colours and the factory firmware stops driving the LED
# once this backend takes over, so there is nothing left to read them from.
# Override per profile with button_colours in settings.json.
PROFILE_COLOURS = {
    "low-power":            "00b0ff",   # cyan
    "quiet":                "00ff40",   # green
    "balanced":             "0080ff",   # blue, matching Archer's own palette
    "balanced-performance": "8000ff",   # purple, observed on this machine
    "performance":          "ff0000",   # red
}

# Effects offered in the GUI, in list order. Only verified modes are exposed.
EFFECTS = [
    ("Static", MODE_STATIC),
    ("Breathing", MODE_BREATHING),
    ("Neon", MODE_NEON),
    ("Neon (fast)", MODE_NEON_FAST),
    ("Wave", MODE_WAVE),
    ("Meteor", MODE_METEOR),
    ("Zoom", MODE_ZOOM),
    ("Shifting", MODE_SHIFTING),
    ("Twinkling", MODE_TWINKLING),
]

ZONE_ALL = 0x0F

# Byte 4 of report 0xA4. Note this is the opposite of the convention Archer
# and the Linuwu-Sense docs use, where 2 means left-to-right: on the wire
# 1 sweeps left-to-right and 2 sweeps right-to-left. Callers pass Archer's
# value and _to_wire_direction() flips it.
DIR_LEFT_TO_RIGHT = 1
DIR_RIGHT_TO_LEFT = 2

# --- reports --------------------------------------------------------------
_REPORT_LEN = {0xA2: 1, 0xA3: 8, 0xA4: 10}

_IOC_WRITE, _IOC_READ = 1, 2


def _hidiocsfeature(size):
    return (((_IOC_WRITE | _IOC_READ) << 30) | (size << 16) |
            (ord('H') << 8) | 0x06)


IOCTL_TIMEOUT_S = 3.0
MIN_GAP_S = 0.05          # the chip needs a breath between feature writes

_lock = threading.Lock()
_last_write = 0.0


class EneError(Exception):
    pass


def _throttle():
    global _last_write
    gap = time.monotonic() - _last_write
    if gap < MIN_GAP_S:
        time.sleep(MIN_GAP_S - gap)
    _last_write = time.monotonic()


def _alarm(signum, frame):
    raise EneError("ENE ioctl timed out")


def _resolve():
    """Return the hidraw node of the ENE, resolved by HID identity.

    Raises EneError if it is absent or ambiguous. Never returns a node whose
    identity is on the blacklist.
    """
    base = "/sys/class/hidraw"
    if not os.path.isdir(base):
        raise EneError("no hidraw class in sysfs")

    found = []
    for node in sorted(os.listdir(base)):
        uevent = os.path.join(base, node, "device", "uevent")
        try:
            with open(uevent) as fh:
                text = fh.read()
        except OSError:
            continue
        hid_id = ""
        for line in text.splitlines():
            if line.startswith("HID_ID="):
                hid_id = line.split("=", 1)[1].strip()
                break
        if hid_id in FORBIDDEN_HID_IDS:
            continue
        if hid_id == ENE_HID_ID:
            found.append("/dev/" + node)

    if not found:
        raise EneError(f"ENE {ENE_HID_ID} not enumerated")
    if len(found) > 1:
        raise EneError(f"ambiguous ENE match: {found}")
    return found[0]


def available():
    try:
        _resolve()
        return True
    except EneError:
        return False


def _write_report(fd, report_id, payload):
    expected = _REPORT_LEN[report_id]
    if len(payload) != expected:
        raise EneError(f"report 0x{report_id:02X} needs exactly "
                       f"{expected} payload bytes, got {len(payload)}")
    total = expected + 1
    buf = ctypes.create_string_buffer(bytes([report_id]) + bytes(payload), total)

    _throttle()
    # setitimer only works on the main thread; the daemon serves D-Bus from a
    # GLib main loop, so guard it rather than crashing on a worker thread.
    armed = threading.current_thread() is threading.main_thread()
    if armed:
        signal.signal(signal.SIGALRM, _alarm)
        signal.setitimer(signal.ITIMER_REAL, IOCTL_TIMEOUT_S)
    try:
        fcntl.ioctl(fd, _hidiocsfeature(total), buf, True)
    except OSError as exc:
        raise EneError(f"HIDIOCSFEATURE(0x{report_id:02X}) failed: {exc}")
    finally:
        if armed:
            signal.setitimer(signal.ITIMER_REAL, 0)


def _check(name, value, lo, hi):
    if not isinstance(value, int) or not lo <= value <= hi:
        raise EneError(f"{name} out of range [{lo}, {hi}]: {value!r}")
    return value


def _to_wire_direction(direction):
    """Archer/Linuwu use 2 for left-to-right; the controller uses 1. Flip."""
    return DIR_LEFT_TO_RIGHT if direction == 2 else DIR_RIGHT_TO_LEFT


def _apply(fd, device, mode, brightness, rgb, zone_mask, speed=0, direction=0):
    # The keyboard tolerates the full verified range. Other devices stay capped
    # at 7: on the performance-mode button LED, modes >= 8 coincided with fans
    # starting and stopping, so up there the report probably reaches the
    # performance profile rather than just the LED.
    top = MODE_MAX_KEYBOARD if device == DEV_KEYBOARD else MODE_MAX_OTHER
    _check("mode", mode, 1, top)
    _check("brightness", brightness, 0, 100)
    _check("speed", speed, 0, 9)
    _check("direction", direction, 0, 3)
    _check("zone_mask", zone_mask, 0, 0xFFFF)
    r, g, b = (_check(n, v, 0, 255) for n, v in zip("rgb", rgb))

    _write_report(fd, 0xA2, [device])   # select — mandatory
    _write_report(fd, 0xA4, [device, mode, brightness, speed, direction,
                             r, g, b,
                             zone_mask & 0xFF, (zone_mask >> 8) & 0xFF])


def _hex_to_rgb(value):
    """Accept 'RRGGBB' or '#RRGGBB'."""
    text = str(value).lstrip("#")
    if len(text) != 6:
        raise EneError(f"bad colour {value!r}, expected RRGGBB")
    try:
        return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))
    except ValueError:
        raise EneError(f"bad colour {value!r}, expected RRGGBB")


# --- public API -----------------------------------------------------------

def set_per_zone(zone1, zone2, zone3, zone4, brightness):
    """Paint the four keyboard zones. Colours are 'RRGGBB' strings."""
    colours = [_hex_to_rgb(z) for z in (zone1, zone2, zone3, zone4)]
    _check("brightness", brightness, 0, 100)
    with _lock:
        fd = os.open(_resolve(), os.O_RDWR)
        try:
            for index, rgb in enumerate(colours):
                _apply(fd, DEV_KEYBOARD, MODE_STATIC, brightness, rgb,
                       1 << index)
        finally:
            os.close(fd)
    return True


def set_effect(effect_index, brightness, red, green, blue,
               speed=0, direction=2):
    """Run one of EFFECTS on the whole keyboard.

    speed is 0-9, rising monotonically. direction follows Archer's convention
    (2 = left to right) and is translated for the wire. Both are ignored by
    the static modes, which is harmless.
    """
    if not 0 <= effect_index < len(EFFECTS):
        raise EneError(f"effect index out of range: {effect_index}")
    mode = EFFECTS[effect_index][1]
    with _lock:
        fd = os.open(_resolve(), os.O_RDWR)
        try:
            _apply(fd, DEV_KEYBOARD, mode, brightness,
                   (red, green, blue), ZONE_ALL,
                   speed=speed, direction=_to_wire_direction(direction))
        finally:
            os.close(fd)
    return True


def set_off():
    with _lock:
        fd = os.open(_resolve(), os.O_RDWR)
        try:
            _apply(fd, DEV_KEYBOARD, MODE_OFF, 0, (0, 0, 0), ZONE_ALL)
        finally:
            os.close(fd)
    return True


def set_logo(colour, brightness=100):
    """Light the lid logo a solid colour. Pass None to switch it off."""
    with _lock:
        fd = os.open(_resolve(), os.O_RDWR)
        try:
            if colour is None:
                _apply(fd, DEV_LOGO, LOGO_OFF, 0, (0, 0, 0), 0xFFFF)
            else:
                _apply(fd, DEV_LOGO, LOGO_STATIC, brightness,
                       _hex_to_rgb(colour), 0xFFFF)
        finally:
            os.close(fd)
    return True


def set_button(colour, brightness=100):
    """Light the performance-mode button LED. Pass None to switch it off."""
    with _lock:
        fd = os.open(_resolve(), os.O_RDWR)
        try:
            if colour is None:
                _apply(fd, DEV_BUTTON, BUTTON_OFF, 0, (0, 0, 0), 0xFFFF)
            else:
                _apply(fd, DEV_BUTTON, BUTTON_STATIC, brightness,
                       _hex_to_rgb(colour), 0xFFFF)
        finally:
            os.close(fd)
    return True


def set_button_for_profile(profile, brightness=100, overrides=None):
    """Colour the button LED after the active platform profile.

    overrides is an optional {profile: "RRGGBB"} map from settings, which
    takes precedence over PROFILE_COLOURS.

    Unknown profile names are left alone rather than guessed at, so a kernel
    that grows a new profile does not silently get the wrong colour.
    """
    colour = (overrides or {}).get(profile) or PROFILE_COLOURS.get(profile)
    if colour is None:
        return False
    return set_button(colour, brightness)
