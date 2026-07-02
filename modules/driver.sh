#!/usr/bin/env bash
# Module: Linuwu-Sense Kernel Driver
# Installs the Linuwu-Sense DKMS kernel driver for Acer fan/RGB/battery hardware access.
# Blacklists acer_wmi for exclusive control.

MODULE_NAME="Linuwu-Sense Kernel Driver"
MODULE_ID="driver"
MODULE_DESCRIPTION="Linuwu-Sense kernel driver for fan/RGB hardware access (DKMS)"

REPO_DRIVER="https://github.com/0x7375646F/Linuwu-Sense.git"
DRIVER_MODULE="linuwu_sense"
DKMS_NAME="linuwu-sense"
DKMS_VERSION="1.0"

module_detect() {
    # Relevant for gaming Acer models; usable on others with warning
    case "$MODEL_FAMILY" in
        nitro|predator|helios|triton) return 0 ;;
        *) return 1 ;;
    esac
}

module_check_installed() {
    if dkms status 2>/dev/null | grep -q "$DKMS_NAME"; then
        return 0
    fi
    return 1
}

module_install() {
    local src_dir="/usr/src/${DKMS_NAME}-${DKMS_VERSION}"

    # --- Kernel Module (Linuwu-Sense) via DKMS ---
    log "Setting up $DRIVER_MODULE via DKMS..."
    run_sudo rm -rf "$src_dir"
    run_sudo git clone "$REPO_DRIVER" "$src_dir"
    # Pin to a reviewed commit (lib/pins.sh) — never build upstream HEAD as root.
    run_sudo git -C "$src_dir" checkout --detach "$ARCHER_PIN_LINUWU_SENSE" \
        || { warn "Failed to checkout pinned Linuwu-Sense commit $ARCHER_PIN_LINUWU_SENSE."; return 1; }

    # Use centralized Clang detection from detect_kernel()
    local make_flags="$CLANG_BUILD_FLAGS"
    if [[ "$IS_CLANG_KERNEL" -eq 1 ]]; then
        log "Clang-built kernel detected. Using LLVM build flags."
    fi

    # Create DKMS config
    run_sudo tee "$src_dir/dkms.conf" > /dev/null <<DKMS_EOF
PACKAGE_NAME="$DKMS_NAME"
PACKAGE_VERSION="$DKMS_VERSION"
CLEAN="make clean"
MAKE[0]="make KVERSION=\\\$kernelver $make_flags"
BUILT_MODULE_NAME[0]="$DRIVER_MODULE"
BUILT_MODULE_LOCATION[0]="src/"
DEST_MODULE_LOCATION[0]="/kernel/drivers/platform/x86"
AUTOINSTALL="yes"
DKMS_EOF

    # Verify kernel headers are available before building
    local build_dir
    build_dir="/usr/lib/modules/$(uname -r)/build"
    if [[ ! -d "$build_dir" ]]; then
        warn "Kernel headers not found at $build_dir"
        warn "Running kernel $(uname -r) may not match installed headers."
        warn "If you recently updated your kernel, reboot first, then re-run the installer."
        warn "Attempting to build for the installed kernel instead..."
    fi

    # Clean up existing DKMS entry before adding (handles re-runs)
    if dkms status -m "$DKMS_NAME" -v "$DKMS_VERSION" 2>/dev/null | grep -q "$DKMS_NAME"; then
        log "Removing existing DKMS entry for clean rebuild..."
        run_sudo dkms remove -m "$DKMS_NAME" -v "$DKMS_VERSION" --all 2>/dev/null || true
    fi

    run_sudo dkms add -m "$DKMS_NAME" -v "$DKMS_VERSION"
    log "Building DKMS module (this may take a few minutes)..."
    run_sudo dkms install -m "$DKMS_NAME" -v "$DKMS_VERSION"

    # Blacklist acer_wmi
    log "Blacklisting acer_wmi..."
    echo "blacklist acer_wmi" | run_sudo tee /etc/modprobe.d/blacklist-acer-wmi.conf > /dev/null

    # Ensure linuwu_sense loads deterministically at boot. With acer_wmi
    # blacklisted, systemd-modules-load modprobes linuwu_sense early instead of
    # relying on modalias autoload (which doesn't always fire).
    log "Configuring $DRIVER_MODULE to load at boot..."
    echo "$DRIVER_MODULE" | run_sudo tee "/etc/modules-load.d/${DRIVER_MODULE}.conf" > /dev/null

    mark_reboot_required

    INSTALLED_FILES+=" /etc/modprobe.d/blacklist-acer-wmi.conf"
    INSTALLED_FILES+=" /etc/modules-load.d/${DRIVER_MODULE}.conf"
    INSTALLED_DKMS+=" ${DKMS_NAME}/${DKMS_VERSION}"
}

module_uninstall() {
    log "Removing Linuwu-Sense DKMS module..."
    run_sudo dkms remove -m "$DKMS_NAME" -v "$DKMS_VERSION" --all 2>/dev/null || true
    run_sudo rm -rf "/usr/src/${DKMS_NAME}-${DKMS_VERSION}"

    log "Restoring acer_wmi (removing blacklist)..."
    run_sudo rm -f /etc/modprobe.d/blacklist-acer-wmi.conf
    run_sudo rm -f "/etc/modules-load.d/${DRIVER_MODULE}.conf"
}

module_verify() {
    local failures=0

    if ! dkms status 2>/dev/null | grep -q "$DKMS_NAME.*installed"; then
        warn "DKMS module $DKMS_NAME not showing as installed"
        failures=$((failures + 1))
    fi

    if ! lsmod 2>/dev/null | grep -q "$DRIVER_MODULE"; then
        warn "$DRIVER_MODULE not loaded (may require reboot)"
    fi

    return $(( failures > 0 ? 1 : 0 ))
}
