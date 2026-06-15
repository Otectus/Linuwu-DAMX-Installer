#!/usr/bin/env python3
"""
Archer Compatibility Suite - System Daemon
Runs as root, communicates with Linuwu-Sense driver via sysfs.
Exposes a Unix socket for GUI communication.
"""

import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

# --- Configuration ---
# /run/archer is created by systemd via RuntimeDirectory=archer in the unit
# file. The PID location matches PIDFile= in archer-daemon.service.
PID_FILE = "/run/archer/daemon.pid"
LOG_FILE = "/var/log/archer-daemon.log"
SETTINGS_FILE = "/etc/archer/settings.json"
VERSION = "2.0.1"

# Linuwu-Sense sysfs base paths (tried in order)
DRIVER_BASE_PATHS = [
    "/sys/module/linuwu_sense/drivers/platform:acer-wmi/acer-wmi",
    "/sys/devices/platform/acer-wmi",
]

# System paths
PLATFORM_PROFILE = "/sys/firmware/acpi/platform_profile"
PLATFORM_PROFILE_CHOICES = "/sys/firmware/acpi/platform_profile_choices"
DMI_PRODUCT = "/sys/class/dmi/id/product_name"
DMI_BOARD = "/sys/class/dmi/id/board_name"
DMI_VENDOR = "/sys/class/dmi/id/sys_vendor"
POWER_SUPPLY_DIR = "/sys/class/power_supply"

# --- Logging ---
logger = logging.getLogger("archer-daemon")


def setup_logging():
    handler = RotatingFileHandler(LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    ))
    logger.addHandler(handler)
    logger.addHandler(logging.StreamHandler())
    logger.setLevel(logging.INFO)


# --- Utility Functions ---
def read_sysfs(path):
    """Read a sysfs file, return stripped string or None."""
    try:
        return Path(path).read_text().strip()
    except (OSError, FileNotFoundError):
        return None


def write_sysfs(path, value):
    """Write a value to a sysfs file. Returns True on success."""
    try:
        Path(path).write_text(str(value))
        return True
    except (OSError, PermissionError) as e:
        logger.error(f"Failed to write '{value}' to {path}: {e}")
        return False


# Shell metacharacters we forbid in dynamic strings. Static literal commands
# (no $ interpolation) can still pass shell_meta_ok=True if they need pipes
# or substitutions — see callsites in get_cpu_usage / get_system_info.
_SHELL_META = (";", "&&", "||", "$(", "`")


def run_cmd(cmd, timeout=10, shell_meta_ok=False):
    """Run a shell command and return stdout.

    shell_meta_ok must be True for any command that contains pipes or
    substitutions. The default of False catches future regressions where a
    user-supplied value flows into a shell string.
    """
    if not shell_meta_ok:
        for tok in _SHELL_META:
            if tok in cmd:
                logger.error(
                    f"run_cmd refused: shell metacharacter {tok!r} in command "
                    f"(set shell_meta_ok=True if intentional): {cmd!r}"
                )
                return ""
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        )
        return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


class _TtlCache:
    """Tiny single-value-per-key cache with monotonic TTL.

    Used for hot-path probes (nvidia-smi, lspci) that the GUI's 2-second
    monitoring loop would otherwise hit too often.
    """

    def __init__(self, ttl_s):
        self._ttl = ttl_s
        self._values = {}
        self._lock = threading.Lock()

    def get_or_compute(self, key, fn):
        now = time.monotonic()
        with self._lock:
            entry = self._values.get(key)
            if entry is not None:
                ts, val = entry
                if now - ts < self._ttl:
                    return val
        # Compute outside the lock so a slow probe doesn't block other keys.
        val = fn()
        with self._lock:
            self._values[key] = (time.monotonic(), val)
        return val


# 5-second TTL is short enough to feel live and long enough to skip 2/3rds
# of the GUI's 2s polling ticks. Touched by HardwareManager methods below.
_PROBE_CACHE = _TtlCache(ttl_s=5.0)

# hwmon device names that ship a meaningful fan1_input/temp1_input on Acer
# laptops. Order is preference — first match wins. Anything else falls back
# to the legacy "first device with fan1_input" behaviour.
_HWMON_FAN_NAMES = (
    "linuwu_sense", "acer_wmi", "nct6775", "nct6779", "nct6798",
    "it87", "dell_smm_hwmon",
)
_HWMON_GPU_TEMP_NAMES = ("nvidia", "amdgpu", "nouveau")


# --- Persistent Settings Store ---
class SettingsStore:
    """Saves and loads user-applied settings so they survive reboots."""

    def __init__(self, path=SETTINGS_FILE):
        self.path = path
        self._data = {}
        self._load()

    def _load(self):
        try:
            with open(self.path) as f:
                self._data = json.load(f)
            logger.info(f"Loaded saved settings from {self.path}")
        except FileNotFoundError:
            self._data = {}
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Could not load settings from {self.path}: {e}")
            self._data = {}

    def _save(self):
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w") as f:
                json.dump(self._data, f, indent=2)
            os.replace(tmp, self.path)
        except OSError as e:
            logger.error(f"Failed to save settings to {self.path}: {e}")

    def get(self, key, default=None):
        return self._data.get(key, default)

    def set(self, key, value):
        self._data[key] = value
        self._save()

    def remove(self, key):
        if key in self._data:
            del self._data[key]
            self._save()

    @property
    def data(self):
        return dict(self._data)


# --- Fan Curve Engine ---
class FanCurveEngine:
    """Runs a 2Hz control loop to drive fan speed along a temperature curve."""

    def __init__(self, get_temp_fn, set_fan_fn, restore_auto_fn):
        self._get_temp = get_temp_fn
        self._set_fan = set_fan_fn
        self._restore_auto = restore_auto_fn
        self._curves = {}  # "cpu" and/or "gpu" -> [(temp_c, fan_pct), ...]
        self._active = {}  # "cpu" -> bool, "gpu" -> bool
        self._fail_counts = {"cpu": 0, "gpu": 0}
        self._lock = threading.Lock()
        self._curve_thread = None
        self._running = False

    def start(self, target, points):
        """Start a fan curve for target ('cpu' or 'gpu')."""
        sorted_pts = sorted(points, key=lambda p: p[0])
        with self._lock:
            self._curves[target] = sorted_pts
            self._active[target] = True
            self._fail_counts[target] = 0
        self._ensure_thread()

    def stop(self, target=None):
        """Stop fan curve for target, or both if None."""
        targets = [target] if target else ["cpu", "gpu"]
        with self._lock:
            for t in targets:
                self._active[t] = False
                self._fail_counts[t] = 0
        # Restore EC auto control
        self._restore_auto()
        # Stop thread if nothing is active
        with self._lock:
            if not any(self._active.get(t) for t in ["cpu", "gpu"]):
                self._running = False
        if self._curve_thread and not self._running:
            self._curve_thread.join(timeout=1.0)

    def get_state(self):
        with self._lock:
            return {
                "cpu": {
                    "active": self._active.get("cpu", False),
                    "points": self._curves.get("cpu", []),
                },
                "gpu": {
                    "active": self._active.get("gpu", False),
                    "points": self._curves.get("gpu", []),
                },
            }

    def _ensure_thread(self):
        if self._running:
            return
        self._running = True
        self._curve_thread = threading.Thread(target=self._loop, daemon=True)
        self._curve_thread.start()

    def _loop(self):
        while self._running:
            with self._lock:
                targets = {t: self._curves.get(t) for t in ["cpu", "gpu"]
                           if self._active.get(t) and self._curves.get(t)}
            for target, points in targets.items():
                try:
                    temp = self._get_temp(target)
                    pct = self._interpolate(points, temp)
                    pct = max(30, min(100, pct))
                    self._set_fan(target, pct)
                    with self._lock:
                        self._fail_counts[target] = 0
                except Exception as e:
                    logger.error(f"Fan curve tick failed for {target}: {e}")
                    should_restore = False
                    with self._lock:
                        self._fail_counts[target] += 1
                        if self._fail_counts[target] >= 3:
                            logger.warning(f"Fan curve watchdog: 3 consecutive failures for {target}, restoring EC auto")
                            self._active[target] = False
                            self._fail_counts[target] = 0
                            should_restore = True
                    if should_restore:
                        self._restore_auto()
            time.sleep(0.5)  # 2 Hz

    @staticmethod
    def _interpolate(points, temp):
        """Linearly interpolate fan percentage from curve points."""
        if not points:
            return 30
        if temp <= points[0][0]:
            return points[0][1]
        if temp >= points[-1][0]:
            return points[-1][1]
        for i in range(len(points) - 1):
            t0, p0 = points[i]
            t1, p1 = points[i + 1]
            if t0 <= temp <= t1:
                if t1 == t0:
                    return p0
                frac = (temp - t0) / (t1 - t0)
                return p0 + frac * (p1 - p0)
        return points[-1][1]


# --- Hardware Detection ---
class HardwareManager:
    """Manages hardware detection and control via sysfs."""

    def __init__(self, settings_store=None):
        self.driver_base = None
        self.sense_base = None  # predator_sense or nitro_sense subdirectory
        self.laptop_type = "unknown"
        self.features = []
        self.settings = settings_store or SettingsStore()
        self._game_mode_active = False
        self._game_mode_saved = {}
        self._fan_curve_engine = FanCurveEngine(
            get_temp_fn=self._fan_curve_get_temp,
            set_fan_fn=self._fan_curve_set_fan,
            restore_auto_fn=self._fan_curve_restore_auto,
        )
        self._detect_driver()
        self._detect_laptop_type()
        self._detect_features()
        logger.info(f"Laptop type: {self.laptop_type}")
        logger.info(f"Driver base: {self.driver_base}")
        logger.info(f"Sense base: {self.sense_base}")
        logger.info(f"Available features: {self.features}")
        self._restore_saved_settings()

    def _detect_driver(self):
        for base in DRIVER_BASE_PATHS:
            if os.path.isdir(base):
                self.driver_base = base
                return
        logger.warning("Linuwu-Sense driver not found in sysfs")

    def _detect_laptop_type(self):
        if self.driver_base:
            predator_path = os.path.join(self.driver_base, "predator_sense")
            nitro_path = os.path.join(self.driver_base, "nitro_sense")
            if os.path.exists(predator_path):
                self.laptop_type = "predator"
                self.sense_base = predator_path
            elif os.path.exists(nitro_path):
                self.laptop_type = "nitro"
                self.sense_base = nitro_path
        # Fallback to DMI
        if self.laptop_type == "unknown":
            product = read_sysfs(DMI_PRODUCT) or ""
            product_lower = product.lower()
            if "predator" in product_lower or "helios" in product_lower:
                self.laptop_type = "predator"
            elif "nitro" in product_lower:
                self.laptop_type = "nitro"
            elif "triton" in product_lower:
                self.laptop_type = "predator"

    def _detect_features(self):
        self.features = []
        # Thermal profiles
        if os.path.exists(PLATFORM_PROFILE):
            self.features.append("thermal_profiles")
        # Keyboard features (under driver_base/four_zoned_kb/)
        if self.driver_base:
            kb_base = os.path.join(self.driver_base, "four_zoned_kb")
            if os.path.isdir(kb_base):
                if os.path.exists(os.path.join(kb_base, "per_zone_mode")):
                    self.features.append("keyboard_per_zone")
                if os.path.exists(os.path.join(kb_base, "four_zone_mode")):
                    self.features.append("keyboard_effects")
        # Sense-specific features (under predator_sense/ or nitro_sense/)
        if self.sense_base:
            sense_features = {
                "fan_speed": "fan_control",
                "battery_calibration": "battery_calibration",
                "battery_limiter": "battery_limiter",
                "usb_charging": "usb_charging",
                "lcd_override": "lcd_override",
                "boot_animation_sound": "boot_animation_sound",
                "backlight_timeout": "backlight_timeout",
            }
            for sysfs_file, feature_name in sense_features.items():
                path = os.path.join(self.sense_base, sysfs_file)
                if os.path.exists(path):
                    self.features.append(feature_name)
        # Battery detection
        bat_paths = [
            os.path.join(POWER_SUPPLY_DIR, d)
            for d in os.listdir(POWER_SUPPLY_DIR)
            if d.startswith("BAT")
        ] if os.path.isdir(POWER_SUPPLY_DIR) else []
        if bat_paths:
            self.features.append("battery_info")
        # Display mode (envycontrol)
        if _PROBE_CACHE.get_or_compute(
            "which-envycontrol",
            lambda: run_cmd("which envycontrol 2>/dev/null", shell_meta_ok=True),
        ):
            self.features.append("display_mode")
        # Game mode (always available)
        self.features.append("game_mode")
        # USB wake policy
        if os.path.exists("/proc/acpi/wakeup"):
            self.features.append("usb_wake_policy")
        # Firmware info (always available)
        self.features.append("firmware_info")

    def _restore_saved_settings(self):
        """Re-apply any previously saved settings on daemon startup."""
        restored = []

        # Keyboard lighting — restore whichever mode was last applied
        last_kb = self.settings.get("last_keyboard_mode")

        if last_kb == "effect":
            effect = self.settings.get("four_zone_mode")
            if effect and "keyboard_effects" in self.features:
                ok = self.set_four_zone_mode(
                    effect["mode"], effect["speed"], effect["brightness"],
                    effect["direction"], effect["red"], effect["green"], effect["blue"],
                )
                if ok:
                    restored.append("keyboard_effects")
        else:
            pz = self.settings.get("per_zone_mode")
            if pz and "keyboard_per_zone" in self.features:
                ok = self.set_per_zone_mode(
                    pz["zone1"], pz["zone2"], pz["zone3"], pz["zone4"],
                    pz["brightness"],
                )
                if ok:
                    restored.append("keyboard_per_zone")

        # Backlight timeout
        bl = self.settings.get("backlight_timeout")
        if bl is not None and "backlight_timeout" in self.features:
            ok = self.set_backlight_timeout(bl)
            if ok:
                restored.append("backlight_timeout")

        # Thermal profile
        tp = self.settings.get("thermal_profile")
        if tp and "thermal_profiles" in self.features:
            ok, _ = self.set_thermal_profile(tp)
            if ok:
                restored.append("thermal_profile")

        # Fan speed
        fan = self.settings.get("fan_speed")
        if fan and "fan_control" in self.features:
            ok = self.set_fan_speed(fan["cpu"], fan["gpu"])
            if ok:
                restored.append("fan_speed")

        # Battery limiter
        bl_lim = self.settings.get("battery_limiter")
        if bl_lim is not None and "battery_limiter" in self.features:
            ok = self.set_battery_limiter(bl_lim)
            if ok:
                restored.append("battery_limiter")

        # USB charging
        usb = self.settings.get("usb_charging")
        if usb is not None and "usb_charging" in self.features:
            ok = self.set_usb_charging(usb)
            if ok:
                restored.append("usb_charging")

        # LCD override
        lcd = self.settings.get("lcd_override")
        if lcd is not None and "lcd_override" in self.features:
            ok = self.set_lcd_override(lcd)
            if ok:
                restored.append("lcd_override")

        # Boot animation sound
        boot = self.settings.get("boot_animation_sound")
        if boot is not None and "boot_animation_sound" in self.features:
            ok = self.set_boot_animation_sound(boot)
            if ok:
                restored.append("boot_animation_sound")

        # Fan curves
        for target in ("cpu", "gpu"):
            key = f"fan_curve_{target}"
            curve_data = self.settings.get(key)
            if curve_data and curve_data.get("enabled") and curve_data.get("points"):
                self.start_fan_curve(target, curve_data["points"])
                restored.append(key)

        # Game mode
        if self.settings.get("game_mode_active"):
            self.activate_game_mode()
            restored.append("game_mode")

        if restored:
            logger.info(f"Restored saved settings: {restored}")
        else:
            logger.info("No saved settings to restore")

    def _driver_path(self, relative):
        if not self.driver_base:
            return None
        return os.path.join(self.driver_base, relative)

    def _sense_path(self, relative):
        """Path under predator_sense/ or nitro_sense/."""
        if not self.sense_base:
            return None
        return os.path.join(self.sense_base, relative)

    # --- Thermal Profiles ---
    def get_thermal_profile(self):
        return read_sysfs(PLATFORM_PROFILE) or "unknown"

    def get_thermal_profile_choices(self):
        choices = read_sysfs(PLATFORM_PROFILE_CHOICES)
        return choices.split() if choices else []

    def set_thermal_profile(self, profile):
        choices = self.get_thermal_profile_choices()
        if profile not in choices:
            return False, f"Invalid profile '{profile}'. Available: {choices}"
        ok = write_sysfs(PLATFORM_PROFILE, profile)
        return ok, None if ok else "Failed to write profile"

    # --- Fan Control ---
    def get_fan_speed(self):
        path = self._sense_path("fan_speed")
        if not path:
            return None, None
        val = read_sysfs(path)
        if val and "," in val:
            try:
                parts = val.split(",")
                return int(parts[0]), int(parts[1])
            except (ValueError, IndexError):
                logger.warning(f"Malformed fan_speed value: {val}")
                return None, None
        return None, None

    def set_fan_speed(self, cpu, gpu):
        path = self._sense_path("fan_speed")
        if not path:
            return False
        return write_sysfs(path, f"{cpu},{gpu}")

    # --- Battery Features ---
    def get_battery_calibration(self):
        path = self._sense_path("battery_calibration")
        if not path:
            return None
        val = read_sysfs(path)
        return val == "1" if val else None

    def set_battery_calibration(self, enabled):
        path = self._sense_path("battery_calibration")
        if not path:
            return False
        return write_sysfs(path, "1" if enabled else "0")

    def get_battery_limiter(self):
        path = self._sense_path("battery_limiter")
        if not path:
            return None
        val = read_sysfs(path)
        return val == "1" if val else None

    def set_battery_limiter(self, enabled):
        path = self._sense_path("battery_limiter")
        if not path:
            return False
        return write_sysfs(path, "1" if enabled else "0")

    def get_usb_charging(self):
        path = self._sense_path("usb_charging")
        if not path:
            return None
        return read_sysfs(path)

    def set_usb_charging(self, level):
        path = self._sense_path("usb_charging")
        if not path:
            return False
        return write_sysfs(path, str(level))

    def get_battery_info(self):
        """Get battery percentage, status, and time remaining."""
        info = {"present": False}
        for name in sorted(os.listdir(POWER_SUPPLY_DIR)) if os.path.isdir(POWER_SUPPLY_DIR) else []:
            if not name.startswith("BAT"):
                continue
            bat_dir = os.path.join(POWER_SUPPLY_DIR, name)
            info["present"] = True
            try:
                info["percentage"] = int(read_sysfs(os.path.join(bat_dir, "capacity")) or 0)
            except ValueError:
                info["percentage"] = 0
            info["status"] = read_sysfs(os.path.join(bat_dir, "status")) or "Unknown"
            # Calculate time remaining
            try:
                energy_now = read_sysfs(os.path.join(bat_dir, "energy_now"))
                power_now = read_sysfs(os.path.join(bat_dir, "power_now"))
                energy_full = read_sysfs(os.path.join(bat_dir, "energy_full"))
                if energy_now and power_now and int(power_now) > 0:
                    en = int(energy_now)
                    pn = int(power_now)
                    if info["status"] == "Discharging":
                        hours = en / pn
                    elif info["status"] == "Charging" and energy_full:
                        hours = (int(energy_full) - en) / pn
                    else:
                        hours = 0
                    h = int(hours)
                    m = int((hours - h) * 60)
                    info["time_remaining"] = f"{h}h {m}m"
                else:
                    info["time_remaining"] = ""
            except (ValueError, ZeroDivisionError):
                info["time_remaining"] = ""
            break
        return info

    # --- Keyboard Lighting ---
    def set_per_zone_mode(self, zone1, zone2, zone3, zone4, brightness):
        path = self._driver_path("four_zoned_kb/per_zone_mode")
        if not path:
            return False
        val = f"{zone1},{zone2},{zone3},{zone4},{brightness}"
        return write_sysfs(path, val)

    def set_four_zone_mode(self, mode, speed, brightness, direction, r, g, b):
        path = self._driver_path("four_zoned_kb/four_zone_mode")
        if not path:
            return False
        val = f"{mode},{speed},{brightness},{direction},{r},{g},{b}"
        return write_sysfs(path, val)

    # --- LCD & Boot ---
    def get_lcd_override(self):
        path = self._sense_path("lcd_override")
        if not path:
            return None
        val = read_sysfs(path)
        return val == "1" if val else None

    def set_lcd_override(self, enabled):
        path = self._sense_path("lcd_override")
        if not path:
            return False
        return write_sysfs(path, "1" if enabled else "0")

    def get_boot_animation_sound(self):
        path = self._sense_path("boot_animation_sound")
        if not path:
            return None
        val = read_sysfs(path)
        return val == "1" if val else None

    def set_boot_animation_sound(self, enabled):
        path = self._sense_path("boot_animation_sound")
        if not path:
            return False
        return write_sysfs(path, "1" if enabled else "0")

    def get_backlight_timeout(self):
        path = self._sense_path("backlight_timeout")
        if not path:
            return None
        val = read_sysfs(path)
        return val == "1" if val else None

    def set_backlight_timeout(self, enabled):
        path = self._sense_path("backlight_timeout")
        if not path:
            return False
        return write_sysfs(path, "1" if enabled else "0")

    # --- System Monitoring ---
    def get_cpu_temp(self):
        """Get CPU temperature from thermal zones or hwmon."""
        for tz in sorted(Path("/sys/class/thermal").glob("thermal_zone*")):
            tz_type = read_sysfs(tz / "type")
            if tz_type and any(k in tz_type.lower() for k in ["x86_pkg", "coretemp", "k10temp", "cpu"]):
                val = read_sysfs(tz / "temp")
                if val:
                    return int(val) // 1000
        # Fallback: first thermal zone
        val = read_sysfs("/sys/class/thermal/thermal_zone0/temp")
        return int(val) // 1000 if val else 0

    def get_gpu_temp(self):
        """Get GPU temperature from hwmon."""
        for hwmon in sorted(Path("/sys/class/hwmon").glob("hwmon*")):
            name = read_sysfs(hwmon / "name")
            if name and name.lower() in _HWMON_GPU_TEMP_NAMES:
                val = read_sysfs(hwmon / "temp1_input")
                if val:
                    return int(val) // 1000
        # Try nvidia-smi (cached; the binary is slow, sometimes hangs)
        temp = _PROBE_CACHE.get_or_compute(
            "nvidia-smi-temp",
            lambda: run_cmd(
                "nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader,nounits 2>/dev/null",
                timeout=3, shell_meta_ok=True,
            ),
        )
        if temp and temp.isdigit():
            return int(temp)
        return 0

    def get_cpu_usage(self):
        """Get CPU usage percentage."""
        # Static literal awk pipeline; shell_meta_ok=True intentionally.
        usage = run_cmd(
            "awk '/^cpu / {u=$2+$4; t=$2+$4+$5; printf \"%.0f\", u/t*100}' /proc/stat",
            shell_meta_ok=True,
        )
        return int(usage) if usage and usage.isdigit() else 0

    def get_gpu_usage(self):
        """Get GPU usage from nvidia-smi or amdgpu."""
        # NVIDIA (cached)
        val = _PROBE_CACHE.get_or_compute(
            "nvidia-smi-util",
            lambda: run_cmd(
                "nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits 2>/dev/null",
                timeout=3, shell_meta_ok=True,
            ),
        )
        if val and val.isdigit():
            return int(val)
        # AMD
        for hwmon in Path("/sys/class/hwmon").glob("hwmon*"):
            name = read_sysfs(hwmon / "name")
            if name and name.lower() == "amdgpu":
                val = read_sysfs(hwmon / "device/gpu_busy_percent")
                if val:
                    return int(val)
        return 0

    def get_fan_rpm(self):
        """Get fan RPM from hwmon. Prefer Acer-relevant chipsets by name."""
        cpu_rpm, gpu_rpm = 0, 0
        # Pass 1: allowlisted chipsets only.
        for hwmon in sorted(Path("/sys/class/hwmon").glob("hwmon*")):
            name = read_sysfs(hwmon / "name") or ""
            if name.lower() not in _HWMON_FAN_NAMES:
                continue
            fan1 = read_sysfs(hwmon / "fan1_input")
            fan2 = read_sysfs(hwmon / "fan2_input")
            if fan1:
                cpu_rpm = int(fan1)
            if fan2:
                gpu_rpm = int(fan2)
            if cpu_rpm or gpu_rpm:
                return cpu_rpm, gpu_rpm
        # Pass 2 (fallback): the legacy "first device with fan1_input" rule.
        for hwmon in sorted(Path("/sys/class/hwmon").glob("hwmon*")):
            fan1 = read_sysfs(hwmon / "fan1_input")
            fan2 = read_sysfs(hwmon / "fan2_input")
            if fan1:
                cpu_rpm = int(fan1)
            if fan2:
                gpu_rpm = int(fan2)
            if cpu_rpm or gpu_rpm:
                break
        return cpu_rpm, gpu_rpm

    def get_power_source(self):
        """Check if running on AC power."""
        for name in os.listdir(POWER_SUPPLY_DIR) if os.path.isdir(POWER_SUPPLY_DIR) else []:
            supply_dir = os.path.join(POWER_SUPPLY_DIR, name)
            supply_type = read_sysfs(os.path.join(supply_dir, "type"))
            if supply_type and supply_type.lower() == "mains":
                online = read_sysfs(os.path.join(supply_dir, "online"))
                return online == "1"
        return True  # Default to AC if unknown

    def get_system_info(self):
        """Get general system information."""
        product = read_sysfs(DMI_PRODUCT) or "Unknown"
        vendor = read_sysfs(DMI_VENDOR) or "Unknown"
        cpu_model = ""
        try:
            with open("/proc/cpuinfo") as f:
                for line in f:
                    if line.startswith("model name"):
                        cpu_model = line.split(":")[1].strip()
                        break
        except OSError:
            pass
        gpu_model = _PROBE_CACHE.get_or_compute(
            "lspci-gpu",
            lambda: run_cmd(
                "lspci 2>/dev/null | grep -iE 'vga|3d' | head -1 | sed 's/.*: //'",
                shell_meta_ok=True,
            ),
        )
        driver_version = read_sysfs(
            os.path.join(self.driver_base, "version") if self.driver_base else "/dev/null"
        ) or "N/A"
        return {
            "product_name": product,
            "vendor": vendor,
            "cpu_model": cpu_model,
            "gpu_model": gpu_model,
            "laptop_type": self.laptop_type,
            "driver_version": driver_version,
            "daemon_version": VERSION,
            "kernel": run_cmd("uname -r"),
        }

    def get_all_settings(self):
        """Get all current settings for the GUI to load."""
        cpu_fan, gpu_fan = self.get_fan_speed()
        cpu_rpm, gpu_rpm = self.get_fan_rpm()
        return {
            "laptop_type": self.laptop_type,
            "features": self.features,
            "daemon_version": VERSION,
            "thermal_profile": self.get_thermal_profile(),
            "thermal_choices": self.get_thermal_profile_choices(),
            "fan_speed_cpu": cpu_fan,
            "fan_speed_gpu": gpu_fan,
            "fan_rpm_cpu": cpu_rpm,
            "fan_rpm_gpu": gpu_rpm,
            "battery_calibration": self.get_battery_calibration(),
            "battery_limiter": self.get_battery_limiter(),
            "usb_charging": self.get_usb_charging(),
            "lcd_override": self.get_lcd_override(),
            "boot_animation_sound": self.get_boot_animation_sound(),
            "backlight_timeout": self.get_backlight_timeout(),
            "battery_info": self.get_battery_info(),
            "power_source_ac": self.get_power_source(),
            "system_info": self.get_system_info(),
            "fan_curve": self.get_fan_curve_state(),
            "display_mode": self.get_display_mode() if "display_mode" in self.features else None,
            "game_mode": self.get_game_mode(),
            "firmware_info": self.get_firmware_info(),
            "saved_settings": self.settings.data,
        }

    def get_monitoring_data(self):
        """Get real-time monitoring metrics for dashboard."""
        cpu_rpm, gpu_rpm = self.get_fan_rpm()
        return {
            "cpu_temp": self.get_cpu_temp(),
            "gpu_temp": self.get_gpu_temp(),
            "cpu_usage": self.get_cpu_usage(),
            "gpu_usage": self.get_gpu_usage(),
            "fan_rpm_cpu": cpu_rpm,
            "fan_rpm_gpu": gpu_rpm,
            "battery_info": self.get_battery_info(),
            "power_source_ac": self.get_power_source(),
        }

    # --- Fan Curve Methods ---
    def _fan_curve_get_temp(self, target):
        if target == "cpu":
            return self.get_cpu_temp()
        else:
            return self.get_gpu_temp()

    def _fan_curve_set_fan(self, target, pct):
        cpu_fan, gpu_fan = self.get_fan_speed()
        cpu_fan = cpu_fan or 0
        gpu_fan = gpu_fan or 0
        if target == "cpu":
            self.set_fan_speed(int(pct), gpu_fan)
        else:
            self.set_fan_speed(cpu_fan, int(pct))

    def _fan_curve_restore_auto(self):
        path = self._sense_path("fan_speed")
        if path:
            write_sysfs(path, "0,0")

    def start_fan_curve(self, target, points):
        """Start a fan curve for 'cpu' or 'gpu'."""
        self._fan_curve_engine.start(target, points)
        self.settings.set(f"fan_curve_{target}", {"enabled": True, "points": points})
        logger.info(f"Fan curve started for {target} with {len(points)} points")

    def stop_fan_curve(self, target=None):
        """Stop fan curve. None stops both."""
        self._fan_curve_engine.stop(target)
        targets = [target] if target else ["cpu", "gpu"]
        for t in targets:
            self.settings.set(f"fan_curve_{t}", {"enabled": False, "points": self.settings.get(f"fan_curve_{t}", {}).get("points", [])})
        logger.info(f"Fan curve stopped for {targets}")

    def get_fan_curve_state(self):
        return self._fan_curve_engine.get_state()

    def shutdown_fan_curves(self):
        """Stop all fan curves and restore EC auto control. Called on daemon shutdown."""
        self._fan_curve_engine.stop()

    # --- Display Mode ---
    def get_display_mode(self):
        mode = _PROBE_CACHE.get_or_compute(
            "envycontrol-query",
            lambda: run_cmd("envycontrol --query 2>/dev/null", shell_meta_ok=True),
        )
        available_modes = ["integrated", "hybrid", "nvidia"]
        return {
            "mode": mode if mode in available_modes else "unknown",
            "available_modes": available_modes,
            "reboot_required": False,
        }

    def set_display_mode(self, mode):
        valid_modes = ["integrated", "hybrid", "nvidia"]
        if mode not in valid_modes:
            return {"success": False, "error": f"Invalid mode '{mode}'. Available: {valid_modes}"}
        if not _PROBE_CACHE.get_or_compute(
            "which-envycontrol",
            lambda: run_cmd("which envycontrol 2>/dev/null", shell_meta_ok=True),
        ):
            return {"success": False, "error": "envycontrol not installed"}
        # Static format string with whitelisted mode value (validated above);
        # the trailing 2>&1 makes this a shell construct.
        result = run_cmd(f"envycontrol -s {mode} 2>&1", timeout=30, shell_meta_ok=True)
        if not result or "error" in result.lower():
            logger.warning(f"Display mode change may have failed: {result}")
            return {"success": False, "error": f"envycontrol failed: {result or 'no output'}", "mode": mode}
        logger.info(f"Display mode set to {mode}: {result}")
        return {"success": True, "mode": mode, "reboot_required": True, "output": result}

    def detect_mux(self):
        """Check DRM topology to see if internal panel is on iGPU or dGPU."""
        mux_info = {"has_mux": False, "active_gpu": "unknown"}
        try:
            drm_path = Path("/sys/class/drm")
            for card in sorted(drm_path.glob("card*-*")):
                status = read_sysfs(card / "status")
                if status and status.lower() == "connected":
                    card_name = card.name
                    if "eDP" in card_name or "LVDS" in card_name:
                        # Determine which GPU the internal panel is on
                        device_link = card / "device"
                        if device_link.exists():
                            vendor = read_sysfs(device_link / "vendor")
                            if vendor:
                                if vendor == "0x10de":
                                    mux_info["active_gpu"] = "nvidia"
                                    mux_info["has_mux"] = True
                                elif vendor in ("0x8086", "0x1002"):
                                    mux_info["active_gpu"] = "igpu"
                        break
        except Exception as e:
            logger.error(f"MUX detection error: {e}")
        return mux_info

    # --- Game Mode ---
    def _find_epp_path(self):
        """Find energy_performance_preference sysfs file."""
        for i in range(16):
            path = f"/sys/devices/system/cpu/cpu{i}/cpufreq/energy_performance_preference"
            if os.path.exists(path):
                return path
        return None

    def activate_game_mode(self):
        """Save current profile/EPP and set everything to performance."""
        if self._game_mode_active:
            return
        # Save current state
        self._game_mode_saved["platform_profile"] = self.get_thermal_profile()
        epp_path = self._find_epp_path()
        if epp_path:
            self._game_mode_saved["epp"] = read_sysfs(epp_path) or "balance_performance"
            self._game_mode_saved["epp_path"] = epp_path
        # Apply performance settings
        self.set_thermal_profile("performance")
        if epp_path:
            write_sysfs(epp_path, "performance")
        # Start nvidia persistence mode
        run_cmd("nvidia-smi -pm 1 2>/dev/null")
        self._game_mode_active = True
        self.settings.set("game_mode_active", True)
        self.settings.set("game_mode_saved_state", self._game_mode_saved)
        logger.info("Game mode activated")

    def deactivate_game_mode(self):
        """Restore saved profile and EPP values."""
        if not self._game_mode_active:
            return
        saved_profile = self._game_mode_saved.get("platform_profile", "balanced")
        saved_epp = self._game_mode_saved.get("epp", "balance_performance")
        self.set_thermal_profile(saved_profile)
        epp_path = self._game_mode_saved.get("epp_path") or self._find_epp_path()
        if epp_path:
            write_sysfs(epp_path, saved_epp)
        run_cmd("nvidia-smi -pm 0 2>/dev/null")
        self._game_mode_active = False
        self._game_mode_saved = {}
        self.settings.set("game_mode_active", False)
        self.settings.remove("game_mode_saved_state")
        logger.info("Game mode deactivated")

    def get_game_mode(self):
        return {"active": self._game_mode_active}

    # --- USB Wake Policy ---
    def get_usb_wake_sources(self):
        """Parse /proc/acpi/wakeup for USB controller entries."""
        sources = []
        try:
            with open("/proc/acpi/wakeup") as f:
                lines = f.readlines()
            for line in lines[1:]:  # Skip header line
                parts = line.split()
                if len(parts) >= 3:
                    device = parts[0]
                    sysfs_node = parts[-1] if len(parts) >= 4 else ""
                    enabled = parts[2].strip("*").lower() == "enabled"
                    sources.append({
                        "device": device,
                        "enabled": enabled,
                        "sysfs_node": sysfs_node,
                    })
        except (OSError, FileNotFoundError) as e:
            logger.error(f"Failed to read /proc/acpi/wakeup: {e}")
        return sources

    def set_usb_wake(self, device, enabled):
        """Toggle a wakeup device by writing its name to /proc/acpi/wakeup."""
        # /proc/acpi/wakeup toggles state when device name is written
        # First check current state
        sources = self.get_usb_wake_sources()
        current = None
        for s in sources:
            if s["device"] == device:
                current = s["enabled"]
                break
        if current is None:
            return False
        if current == enabled:
            return True  # already in desired state
        try:
            with open("/proc/acpi/wakeup", "w") as f:
                f.write(device)
            return True
        except OSError as e:
            logger.error(f"Failed to set USB wake for {device}: {e}")
            return False

    # --- Firmware Info ---
    def get_firmware_info(self):
        """Get BIOS version and firmware update info."""
        info = {}
        info["bios_version"] = read_sysfs("/sys/class/dmi/id/bios_version") or "Unknown"
        info["vendor"] = read_sysfs("/sys/class/dmi/id/sys_vendor") or "Unknown"
        info["fwupd_available"] = bool(run_cmd("which fwupdmgr 2>/dev/null"))
        info["updates"] = []
        if info["fwupd_available"]:
            try:
                raw = run_cmd("fwupdmgr get-updates --json 2>/dev/null", timeout=30)
                if raw:
                    info["updates"] = json.loads(raw).get("Devices", [])
            except (json.JSONDecodeError, Exception) as e:
                logger.error(f"Failed to parse fwupd updates: {e}")
        return info

    # --- Driver Management ---
    def restart_daemon(self):
        # Schedule via systemd-run with a 2s delay so the D-Bus reply
        # for RestartDaemon has time to flush before SIGTERM lands. The
        # previous synchronous systemctl restart killed the daemon
        # before the reply reached the GUI.
        run_cmd(
            "systemd-run --on-active=2s --no-block "
            "systemctl restart archer-daemon.service"
        )

    def restart_drivers_and_daemon(self):
        # Same deferred-restart trick. modprobe runs before the daemon
        # restart so the new daemon picks up the freshly-loaded module.
        # Each step is its own systemd-run unit so a modprobe failure
        # doesn't abort the daemon restart.
        run_cmd(
            "systemd-run --on-active=1s --no-block "
            "/bin/sh -c 'modprobe -r linuwu_sense; modprobe linuwu_sense'",
            shell_meta_ok=True,
        )
        run_cmd(
            "systemd-run --on-active=3s --no-block "
            "systemctl restart archer-daemon.service"
        )

    def set_modprobe_parameter(self, param):
        """Set a permanent modprobe parameter for linuwu_sense."""
        conf = "/etc/modprobe.d/linuwu-sense.conf"
        try:
            Path(conf).write_text(f"options linuwu_sense {param}=1\n")
            return True
        except OSError as e:
            logger.error(f"Failed to write modprobe config: {e}")
            return False

    def remove_modprobe_parameter(self):
        conf = "/etc/modprobe.d/linuwu-sense.conf"
        try:
            Path(conf).unlink(missing_ok=True)
            return True
        except OSError:
            return False

    def force_driver_parameter(self, param):
        """Force a one-time driver parameter reload."""
        if self.driver_base:
            write_sysfs(os.path.join(self.driver_base, "force_parameter"), param)


# --- Main ---
def write_pid():
    Path(PID_FILE).write_text(str(os.getpid()))


def cleanup_pid():
    Path(PID_FILE).unlink(missing_ok=True)


def main():
    if os.geteuid() != 0:
        print("Error: Archer daemon must run as root.", file=sys.stderr)
        sys.exit(1)

    setup_logging()
    logger.info(f"Archer Daemon v{VERSION} starting...")

    write_pid()
    settings = SettingsStore()
    hw = HardwareManager(settings_store=settings)

    # D-Bus is mandatory. The previous Unix-socket fallback was unreachable
    # by the user-mode GUI (socket was 0o660 root:root) and only masked real
    # D-Bus startup failures behind a "deprecated" warning.
    try:
        import dbus.mainloop.glib
        from gi.repository import GLib
        from archer_dbus import ArcherDBusService
    except ImportError as e:
        logger.error(
            f"Failed to import D-Bus dependencies: {e}. "
            "Install python-dbus and python-gobject, then restart."
        )
        cleanup_pid()
        sys.exit(1)

    try:
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        _dbus_service = ArcherDBusService(hw)  # noqa: F841 — prevent GC
        main_loop = GLib.MainLoop()
        logger.info("D-Bus service registered (io.otectus.Archer1)")
    except Exception as e:
        logger.error(
            f"Failed to register D-Bus service: {e}. "
            "Check that /etc/dbus-1/system.d/io.otectus.Archer1.conf exists "
            "and 'systemctl reload dbus.service' has been run."
        )
        cleanup_pid()
        sys.exit(1)

    def signal_handler(sig, frame):
        logger.info("Shutting down...")
        hw.shutdown_fan_curves()
        hw.deactivate_game_mode()
        main_loop.quit()
        cleanup_pid()
        sys.exit(0)

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    try:
        main_loop.run()
    except KeyboardInterrupt:
        pass
    finally:
        hw.shutdown_fan_curves()
        hw.deactivate_game_mode()
        cleanup_pid()
        logger.info("Daemon stopped.")


if __name__ == "__main__":
    main()
