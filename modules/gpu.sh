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

# Remove the no-op mkinitcpio shim and restore any original wrapper. Safe to
# call repeatedly; called explicitly on every exit path (no RETURN trap — those
# persist past this function under bash and would fire on later modules).
_gpu_restore_mkinitcpio() {
    local shim_path="$1" had_existing="$2"
    run_sudo rm -f "$shim_path"
    if [[ "$had_existing" -eq 1 ]] && [[ -f "$shim_path.archer-bak" ]]; then
        run_sudo mv "$shim_path.archer-bak" "$shim_path"
    fi
}

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
    # EnvyControl internally calls 'mkinitcpio -P' via subprocess.run, which
    # hangs on CachyOS due to the Limine wrapper's interactive prompt and
    # multi-kernel preset rebuilds. We temporarily replace mkinitcpio with a
    # no-op shim so envycontrol skips it, then do our own rebuild afterwards.
    local _shim_path="/usr/local/bin/mkinitcpio"
    local _had_existing=0
    if [[ -f "$_shim_path" ]]; then
        _had_existing=1
        run_sudo mv "$_shim_path" "$_shim_path.archer-bak"
    fi
    run_sudo tee "$_shim_path" > /dev/null <<'SHIM'
#!/bin/sh
exit 0
SHIM
    run_sudo chmod 755 "$_shim_path"

    # Run envycontrol, then ALWAYS restore the shim on both success and failure.
    # (No RETURN trap: bash RETURN traps aren't function-scoped without
    # 'functrace', so one set here would re-fire on later modules' returns and,
    # with the now-unset locals under 'set -u', crash with "_shim_path: unbound
    # variable".)
    local _rc=0
    if [[ "$gpu_mode" = "hybrid" ]]; then
        run_sudo envycontrol -s hybrid --rtd3 2 || _rc=1
    else
        run_sudo envycontrol -s "$gpu_mode" || _rc=1
    fi
    _gpu_restore_mkinitcpio "$_shim_path" "$_had_existing"

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
        # envycontrol --reset also calls mkinitcpio -P internally; use same shim trick
        local _shim_path="/usr/local/bin/mkinitcpio"
        local _had_existing=0
        if [[ -f "$_shim_path" ]]; then
            _had_existing=1
            run_sudo mv "$_shim_path" "$_shim_path.archer-bak"
        fi
        printf '#!/bin/sh\nexit 0\n' | run_sudo tee "$_shim_path" > /dev/null
        run_sudo chmod 755 "$_shim_path"

        run_sudo envycontrol --reset 2>/dev/null || true

        # Explicit restore (no RETURN trap — see module_install for why).
        _gpu_restore_mkinitcpio "$_shim_path" "$_had_existing"

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
