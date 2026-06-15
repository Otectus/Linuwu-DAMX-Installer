"""
Unit tests for archer_validate — the daemon's input validators.

Pure-Python (no dbus/gi), so it runs anywhere python3 is available. Run
directly: `python3 tests/test_validate.py`, or via pytest.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "gui"))

import archer_validate as v  # noqa: E402


def test_parse_json_object():
    assert v.parse_json_object('{"a": 1}') == ({"a": 1}, None)
    assert v.parse_json_object("not json")[0] is None
    assert v.parse_json_object("[1, 2]")[0] is None  # not an object
    assert v.parse_json_object("42")[0] is None


def test_int_range():
    assert v.validate_int_range(50, 0, 100) == (50, None)
    assert v.validate_int_range(-1, 0, 100)[0] is None
    assert v.validate_int_range(101, 0, 100)[0] is None
    assert v.validate_int_range("nope", 0, 100)[0] is None


def test_fan_speed():
    assert v.validate_fan_speed(0, 100) == ((0, 100), None)
    assert v.validate_fan_speed(200, 0)[0] is None
    assert v.validate_fan_speed(0, -5)[0] is None


def test_usb_levels():
    for lvl in v.USB_CHARGING_LEVELS:
        assert v.validate_choice(lvl, v.USB_CHARGING_LEVELS, "usb") == (lvl, None)
    assert v.validate_choice(15, v.USB_CHARGING_LEVELS, "usb")[0] is None


def test_hex_color():
    assert v.validate_hex_color("ff8800") == ("ff8800", None)
    assert v.validate_hex_color("abc") == ("abc", None)
    assert v.validate_hex_color("#ff8800")[0] is None  # leading '#'
    assert v.validate_hex_color("nothex")[0] is None
    assert v.validate_hex_color(123)[0] is None


def test_per_zone():
    ok = v.validate_per_zone(
        {"zone1": "ff0000", "zone2": "00ff00", "zone3": "0000ff",
         "zone4": "ffffff", "brightness": 80}
    )
    assert ok == (("ff0000", "00ff00", "0000ff", "ffffff", 80), None)
    assert v.validate_per_zone({"zone1": "ff0000"})[0] is None  # missing zones
    assert v.validate_per_zone(
        {"zone1": "zz", "zone2": "0", "zone3": "0", "zone4": "0"}
    )[0] is None  # bad color


def test_four_zone():
    ok = v.validate_four_zone(
        {"mode": 3, "speed": 5, "brightness": 100, "direction": 2,
         "red": 255, "green": 0, "blue": 128}
    )
    assert ok == ((3, 5, 100, 2, 255, 0, 128), None)
    assert v.validate_four_zone({"red": 999})[0] is None
    assert v.validate_four_zone({"direction": 7})[0] is None


def test_fan_curve_points():
    assert v.validate_fan_curve_points([[40, 30], [80, 100]]) == (
        [[40, 30], [80, 100]], None)
    assert v.validate_fan_curve_points([[40]])[0] is None
    assert v.validate_fan_curve_points("nope")[0] is None
    assert v.validate_fan_curve_points([[200, 0]])[0] is None  # temp out of range


def main():
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"OK: {name}")
            except AssertionError as e:
                failures += 1
                print(f"FAIL: {name}: {e}", file=sys.stderr)
    if failures:
        print(f"FAIL: {failures} validator test(s) failed", file=sys.stderr)
        sys.exit(1)
    print("PASS: all validator tests")


if __name__ == "__main__":
    main()
