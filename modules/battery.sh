#!/usr/bin/env bash
# Module: Battery Charge Limit
# Installs acer-wmi-battery DKMS module for 80% charge limiting

MODULE_NAME="Battery Charge Limit"
MODULE_ID="battery"
MODULE_DESCRIPTION="Limits battery charging to 80% for health (acer-wmi-battery)"

_BATTERY_DKMS_NAME="acer-wmi-battery"
_BATTERY_DKMS_VERSION="0.1.0"
_BATTERY_REPO="https://github.com/frederik-h/acer-wmi-battery.git"
_BATTERY_HEALTH_PATH="/sys/bus/wmi/drivers/acer-wmi-battery/health_mode"
_BATTERY_UDEV_RULE="/etc/udev/rules.d/99-acer-battery-health.rules"

module_detect() {
    [[ "$HAS_BATTERY" -eq 1 ]]
}

module_check_installed() {
    if [[ -f "$_BATTERY_HEALTH_PATH" ]]; then
        return 0
    fi
    if dkms status 2>/dev/null | grep -q "$_BATTERY_DKMS_NAME"; then
        return 0
    fi
    return 1
}

module_install() {
    # Check if the interface already exists natively (mainlined driver)
    if [[ -f "$_BATTERY_HEALTH_PATH" ]]; then
        log "Battery health mode interface already available (native driver)."
        log "Enabling 80% charge limit..."
        echo 1 | run_sudo tee "$_BATTERY_HEALTH_PATH" > /dev/null
        _install_udev_rule
        return 0
    fi

    # Install via AUR helper or manual DKMS
    if [[ -n "$AUR_HELPER" ]]; then
        log "Installing acer-wmi-battery via $AUR_HELPER..."
        run "$AUR_HELPER" -S --needed --noconfirm acer-wmi-battery-dkms-git
    else
        log "No AUR helper found. Installing manually from GitHub..."
        local src_dir="/usr/src/${_BATTERY_DKMS_NAME}-${_BATTERY_DKMS_VERSION}"
        run_sudo rm -rf "$src_dir"
        run_sudo git clone "$_BATTERY_REPO" "$src_dir"

        # Inject Clang build flags into DKMS config if kernel was built with Clang
        if [[ "$IS_CLANG_KERNEL" -eq 1 ]] && [[ -f "$src_dir/dkms.conf" ]]; then
            log "Patching dkms.conf with Clang/LLVM build flags..."
            run_sudo sed -i "s|^MAKE\[0\]=.*|& $CLANG_BUILD_FLAGS|" "$src_dir/dkms.conf"
        fi

        # Clean up existing DKMS entry before adding (handles re-runs)
        if dkms status -m "$_BATTERY_DKMS_NAME" -v "$_BATTERY_DKMS_VERSION" 2>/dev/null | grep -q "$_BATTERY_DKMS_NAME"; then
            log "Removing existing DKMS entry for clean rebuild..."
            run_sudo dkms remove -m "$_BATTERY_DKMS_NAME" -v "$_BATTERY_DKMS_VERSION" --all 2>/dev/null || true
        fi

        run_sudo dkms add -m "$_BATTERY_DKMS_NAME" -v "$_BATTERY_DKMS_VERSION"
        run_sudo dkms install -m "$_BATTERY_DKMS_NAME" -v "$_BATTERY_DKMS_VERSION"
    fi

    # Load the module
    run_sudo modprobe acer_wmi_battery || true

    # Enable health mode
    if [[ -f "$_BATTERY_HEALTH_PATH" ]]; then
        echo 1 | run_sudo tee "$_BATTERY_HEALTH_PATH" > /dev/null
        log "Battery health mode enabled (charge limit: 80%)"
    else
        warn "Battery health mode interface not found after module load."
        warn "This may require a reboot, or your model may not be supported."
    fi

    _install_udev_rule

    INSTALLED_FILES+=" $_BATTERY_UDEV_RULE"
    INSTALLED_DKMS+=" ${_BATTERY_DKMS_NAME}/${_BATTERY_DKMS_VERSION}"
    mark_reboot_required
}

_install_udev_rule() {
    # Persist health mode on boot via udev
    log "Creating udev rule for persistent battery health mode..."
    run_sudo tee "$_BATTERY_UDEV_RULE" > /dev/null <<'UDEV_EOF'
# Acer battery health mode - limit charge to 80%
# Installed by Archer Compatibility Suite
ACTION=="add", SUBSYSTEM=="wmi", DRIVER=="acer-wmi-battery", RUN+="/bin/sh -c 'echo 1 > /sys/bus/wmi/drivers/acer-wmi-battery/health_mode'"
UDEV_EOF
}

module_uninstall() {
    log "Disabling battery health mode..."
    if [[ -f "$_BATTERY_HEALTH_PATH" ]]; then
        echo 0 | run_sudo tee "$_BATTERY_HEALTH_PATH" > /dev/null 2>&1 || true
    fi

    log "Removing udev rule..."
    run_sudo rm -f "$_BATTERY_UDEV_RULE"

    log "Removing acer-wmi-battery DKMS module..."
    run_sudo dkms remove -m "$_BATTERY_DKMS_NAME" -v "$_BATTERY_DKMS_VERSION" --all 2>/dev/null || true
    run_sudo rm -rf "/usr/src/${_BATTERY_DKMS_NAME}-${_BATTERY_DKMS_VERSION}"
    run_sudo modprobe -r acer_wmi_battery 2>/dev/null || true
}

module_verify() {
    if [[ -f "$_BATTERY_HEALTH_PATH" ]]; then
        local val
        val=$(cat "$_BATTERY_HEALTH_PATH" 2>/dev/null)
        if [[ "$val" = "1" ]]; then
            return 0
        fi
    fi

    # Module might need a reboot
    if dkms status 2>/dev/null | grep -q "$_BATTERY_DKMS_NAME.*installed"; then
        warn "DKMS module installed but health_mode not yet active (reboot required)"
        return 0
    fi
    return 1
}
