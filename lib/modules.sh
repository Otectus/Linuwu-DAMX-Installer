#!/usr/bin/env bash
# Canonical module registry for Archer Compatibility Suite.
# Sourced by install.sh and uninstall.sh so both validate against the same
# allowlist and order. Adding a new module: append to MODULE_IDS *and*
# MODULE_LABELS at the same index.

MODULE_IDS=("driver" "battery" "gpu" "touchpad" "audio" "wifi" "power" "thermal" "gui" "gamemode" "audio-enhance" "camera-enhance" "firmware")
MODULE_LABELS=(
    "Linuwu-Sense Kernel Driver"
    "Battery Charge Limit (80%)"
    "GPU Switching (EnvyControl)"
    "Touchpad Fix (I2C HID)"
    "Audio Fix (SOF/ALSA)"
    "WiFi/Bluetooth Troubleshooting"
    "Power Management (TLP)"
    "Kernel Thermal Profiles"
    "Archer GUI (Control Panel)"
    "Game Mode Support"
    "Audio Enhancement (Noise Suppression)"
    "Camera Enhancement (Virtual Camera)"
    "Firmware Update Advisor"
)

# Return 0 iff $1 is a valid, known module ID. Rejects path-traversal attempts
# and shell metacharacters before the allowlist check.
is_known_module() {
    local id="$1"
    [[ "$id" =~ ^[a-z][a-z0-9_-]+$ ]] || return 1
    local m
    for m in "${MODULE_IDS[@]}"; do
        [[ "$m" == "$id" ]] && return 0
    done
    return 1
}
