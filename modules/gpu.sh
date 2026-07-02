#!/usr/bin/env bash
# Module: GPU Switching
# Installs EnvyControl for NVIDIA Optimus GPU mode management

MODULE_NAME="GPU Switching"
MODULE_ID="gpu"
MODULE_DESCRIPTION="EnvyControl for NVIDIA Optimus hybrid graphics switching"

module_detect() {
    # Relevant if NVIDIA dGPU + an integrated GPU
    if [[ "$HAS_NVIDIA" -eq 1 ]] && { [[ "$HAS_INTEL_IGPU" -eq 1 ]] || [[ "$HAS_AMD_IGPU" -eq 1 ]]; }; then
        return 0
    fi
    return 1
}

module_check_installed() {
    has_cmd envycontrol
}

# --- mkinitcpio shim lifecycle -----------------------------------------------
# EnvyControl internally runs 'mkinitcpio -P', which hangs on CachyOS/Limine.
# We swap in a no-op shim for the duration of the envycontrol call. If that
# shim ever outlives the installer (Ctrl-C, SIGTERM, crash), every future
# initramfs rebuild silently does nothing — so the window is protected by
# EXIT/INT/TERM traps.
#
# State is GLOBAL, not local: a trap firing after the enclosing function
# returns cannot see locals, and under 'set -u' unset locals would crash it.
# (No RETURN trap: bash RETURN traps aren't function-scoped without
# 'functrace', so one set here would re-fire on later modules' returns.)
_GPU_SHIM_PATH="/usr/local/bin/mkinitcpio"
_GPU_SHIM_ACTIVE=0
_GPU_SHIM_HAD_EXISTING=0

# Swap the shim in. Arms the traps BEFORE touching the filesystem so an
# interrupt landing between the mv and the tee still restores the original
# wrapper (rm -f of a not-yet-created shim is harmless).
# NOTE: this arms a process-global EXIT trap for the window's duration. If a
# global install-rollback trap is ever added (F-STAB2), the two must compose.
_gpu_shim_install() {
    _GPU_SHIM_HAD_EXISTING=0
    _GPU_SHIM_ACTIVE=1
    trap '_gpu_shim_cleanup' EXIT
    trap '_gpu_shim_on_signal INT' INT
    trap '_gpu_shim_on_signal TERM' TERM
    if [[ -f "$_GPU_SHIM_PATH" ]]; then
        _GPU_SHIM_HAD_EXISTING=1
        run_sudo mv "$_GPU_SHIM_PATH" "$_GPU_SHIM_PATH.archer-bak"
    fi
    printf '#!/bin/sh\nexit 0\n' | run_sudo tee "$_GPU_SHIM_PATH" > /dev/null
    run_sudo chmod 755 "$_GPU_SHIM_PATH"
}

# Remove the shim and restore any original wrapper. Idempotent: the guard
# variable makes stray firings (or double calls) no-ops, and disarming the
# traps here prevents them misfiring on later modules or at installer exit.
_gpu_shim_cleanup() {
    [[ "${_GPU_SHIM_ACTIVE:-0}" -eq 1 ]] || return 0
    run_sudo rm -f "$_GPU_SHIM_PATH"
    if [[ "$_GPU_SHIM_HAD_EXISTING" -eq 1 ]] && [[ -f "$_GPU_SHIM_PATH.archer-bak" ]]; then
        run_sudo mv "$_GPU_SHIM_PATH.archer-bak" "$_GPU_SHIM_PATH"
    fi
    _GPU_SHIM_ACTIVE=0
    trap - EXIT INT TERM
}

# On INT/TERM: clean up, then RE-RAISE the signal with default disposition so
# the installer actually dies (a sourced-context trap must not swallow the
# signal) and the exit status reflects the signal.
_gpu_shim_on_signal() {
    local sig="$1"
    _gpu_shim_cleanup
    trap - "$sig"
    kill -s "$sig" "$$"
}
# -----------------------------------------------------------------------------

# Return 0 if any usable NVIDIA kernel driver is already present. Accept every
# variant — nvidia, nvidia-dkms, nvidia-open(-dkms), or a kernel-bundled module
# such as linux-cachyos-lts-nvidia-open — so we never force a conflicting
# package onto a system that already has one.
_nvidia_driver_present() {
    modinfo nvidia &>/dev/null && return 0
    pacman -Qq 2>/dev/null | grep -qiE '^nvidia(-open)?(-dkms)?$|-nvidia(-open)?$' && return 0
    return 1
}

module_install() {
    # Ensure an NVIDIA kernel driver is present (don't clobber an existing one).
    if _nvidia_driver_present; then
        debug "NVIDIA kernel driver already present; skipping nvidia-dkms install."
    else
        log "NVIDIA driver not installed. Installing nvidia-dkms..."
        if run_sudo pacman -S --needed --noconfirm nvidia-dkms nvidia-utils; then
            INSTALLED_PACKAGES+=" nvidia-dkms nvidia-utils"
        else
            warn "Could not install nvidia-dkms (it may conflict with an existing NVIDIA package)."
            warn "Continuing — EnvyControl works with whatever NVIDIA driver is already installed."
        fi
    fi

    # Install EnvyControl (skip if it's already on PATH).
    if has_cmd envycontrol; then
        debug "EnvyControl already installed."
    elif [[ -n "$AUR_HELPER" ]]; then
        log "Installing EnvyControl via $AUR_HELPER..."
        run "$AUR_HELPER" -S --needed --noconfirm envycontrol \
            || warn "$AUR_HELPER could not install envycontrol (network/AUR issue?)."
    else
        log "No AUR helper found. Installing EnvyControl via pip..."
        run pip install envycontrol --break-system-packages 2>/dev/null || warn "pip install encountered issues."
    fi

    # If EnvyControl still isn't available, fail cleanly BEFORE touching the
    # mkinitcpio shim — otherwise we'd create a shim we then have to roll back
    # and the mode switch can't work anyway.
    if [[ "${DRY_RUN:-0}" -eq 0 ]] && ! has_cmd envycontrol; then
        warn "EnvyControl is not installed (AUR/pip unavailable?). Skipping GPU mode switch."
        warn "Install it manually, then re-run: ./install.sh --modules gpu"
        return 1
    fi

    # GPU mode selection
    log "GPU Switching Modes:"
    log "  1) hybrid      - iGPU by default, NVIDIA on demand (recommended)"
    log "  2) nvidia       - Always use NVIDIA GPU (best performance)"
    log "  3) integrated   - Disable NVIDIA entirely (best battery life)"

    local gpu_mode="hybrid"
    if [[ "$NO_CONFIRM" -eq 0 ]]; then
        read -rp "Select mode [1]: " gpu_choice
        case "${gpu_choice:-1}" in
            2) gpu_mode="nvidia" ;;
            3) gpu_mode="integrated" ;;
            *) gpu_mode="hybrid" ;;
        esac
    fi

    log "Setting GPU mode to: $gpu_mode"
    # Shim mkinitcpio for the envycontrol run (see shim lifecycle above); the
    # trap-protected window restores it on success, failure, or interrupt.
    _gpu_shim_install
    local _rc=0
    if [[ "$gpu_mode" = "hybrid" ]]; then
        run_sudo envycontrol -s hybrid --rtd3 2 || _rc=1
    else
        run_sudo envycontrol -s "$gpu_mode" || _rc=1
    fi
    _gpu_shim_cleanup

    if [[ "$_rc" -ne 0 ]]; then
        warn "envycontrol failed to set $gpu_mode mode."
        return 1
    fi

    # Now rebuild initramfs properly (single preset, with timeout, bypasses wrapper)
    rebuild_initramfs

    INSTALLED_PACKAGES+=" envycontrol"
    mark_reboot_required
    log "GPU mode set to '$gpu_mode'. A reboot is required to apply changes."
}

module_uninstall() {
    log "Resetting GPU configuration..."
    if has_cmd envycontrol; then
        # envycontrol --reset also calls mkinitcpio -P internally; same
        # trap-protected shim window as module_install.
        _gpu_shim_install
        run_sudo envycontrol --reset 2>/dev/null || true
        _gpu_shim_cleanup

        rebuild_initramfs
    fi
    log "EnvyControl package retained (remove manually if desired)."
}

module_verify() {
    if has_cmd envycontrol; then
        local mode
        mode=$(envycontrol --query 2>/dev/null || echo "unknown")
        log "Current GPU mode: $mode"
        return 0
    fi
    warn "EnvyControl not found"
    return 1
}
