"""
Headless smoke test for the Archer D-Bus service.

Boots ArcherDBusService against a session bus with a mocked HardwareManager,
calls Ping, scrapes the introspection XML for required methods + signals,
waits for one TelemetryUpdated signal to confirm the timer fires, then
exits 0 on success and non-zero on any failure. Designed to run under
`dbus-run-session -- python3 tests/dbus_smoke.py` with no root and no
real hardware.
"""

import sys
import threading
import xml.etree.ElementTree as ET
from pathlib import Path

import dbus
import dbus.mainloop.glib
import dbus.service
from gi.repository import GLib

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "gui"))

# archer_dbus.py uses dbus.SystemBus() in __init__; force SessionBus for CI.
import dbus  # noqa: E402  (re-import after path tweak)
_orig_system_bus = dbus.SystemBus
dbus.SystemBus = dbus.SessionBus

import archer_dbus  # noqa: E402

REQUIRED_METHODS = (
    "Ping",
    "GetAllSettings",
    "GetMonitoringData",
    "GetSupportedFeatures",
    "SetThermalProfile",
    "SetAudioEnhancement",
)
REQUIRED_SIGNALS = (
    "TelemetryUpdated",
    "AudioEnhancementChanged",
    "ProfileChanged",
)


class FakeSettings:
    def __init__(self):
        self._data = {"daemon_version": "smoke"}

    def get(self, k, default=None):
        return self._data.get(k, default)

    def set(self, k, v):
        self._data[k] = v

    @property
    def data(self):
        return dict(self._data)


class FakeHardware:
    """Minimal stand-in. Returns plausible scalar telemetry every call."""
    features = ["smoke"]
    settings = FakeSettings()

    def get_monitoring_data(self):
        return {"cpu_temp": 42, "gpu_temp": 38, "battery_info": {"present": False}}

    def get_all_settings(self):
        return {"features": list(self.features), "battery_info": {"present": False}}


def _fail(msg):
    print(f"FAIL: {msg}", file=sys.stderr)
    sys.exit(1)


def main():
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SessionBus()

    # Construct the service. Its __init__ calls dbus.SystemBus internally
    # but we patched it above to return a SessionBus connected to the
    # ephemeral bus that dbus-run-session set up.
    svc = archer_dbus.ArcherDBusService(FakeHardware(), bus=bus)  # noqa: F841

    main_loop = GLib.MainLoop()

    # Run the loop in a worker thread so the test thread can issue D-Bus
    # calls. dbus-python's blocking calls would deadlock if the main loop
    # ran on the same thread.
    threading.Thread(target=main_loop.run, daemon=True).start()

    try:
        proxy = bus.get_object(archer_dbus.DBUS_NAME, archer_dbus.DBUS_PATH)
        iface = dbus.Interface(proxy, archer_dbus.DBUS_IFACE)

        ping_resp = str(iface.Ping(timeout=5))
        if "success" not in ping_resp:
            _fail(f"Ping returned: {ping_resp!r}")
        print(f"OK: Ping -> {ping_resp}")

        introspect = dbus.Interface(proxy, "org.freedesktop.DBus.Introspectable")
        xml = str(introspect.Introspect(timeout=5))
        root = ET.fromstring(xml)

        method_names = {
            m.attrib["name"]
            for inode in root.iter("interface")
            if inode.attrib.get("name") == archer_dbus.DBUS_IFACE
            for m in inode.findall("method")
        }
        signal_names = {
            s.attrib["name"]
            for inode in root.iter("interface")
            if inode.attrib.get("name") == archer_dbus.DBUS_IFACE
            for s in inode.findall("signal")
        }

        missing_m = [m for m in REQUIRED_METHODS if m not in method_names]
        if missing_m:
            _fail(f"Missing D-Bus methods: {missing_m}")
        print(f"OK: methods present: {sorted(method_names)}")

        missing_s = [s for s in REQUIRED_SIGNALS if s not in signal_names]
        if missing_s:
            _fail(f"Missing D-Bus signals: {missing_s}")
        print(f"OK: signals present: {sorted(signal_names)}")

        # Wait for one TelemetryUpdated emit. Daemon timer is 2s, so ~5s
        # is comfortably enough for the first tick.
        seen = threading.Event()

        def on_telemetry(_payload):
            seen.set()

        proxy.connect_to_signal(
            "TelemetryUpdated", on_telemetry,
            dbus_interface=archer_dbus.DBUS_IFACE,
        )

        if not seen.wait(timeout=5.0):
            _fail("TelemetryUpdated signal never fired within 5s")
        print("OK: TelemetryUpdated fired")

        print("PASS: D-Bus smoke complete")
    finally:
        main_loop.quit()
        # Restore in case dbus is re-used by other tests in the same process.
        dbus.SystemBus = _orig_system_bus


if __name__ == "__main__":
    main()
