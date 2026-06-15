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
# call repeatedly; used both on the happy path and from a RETURN trap so the
# shim is never left behind if envycontrol fails or is interrupted.
_gpu_restore_mkinitcpio() {
    local shim_path="$1" had_existing="$2"
    run_sudo rm -f "$shim_path"
    if [[ "$had_existing" -eq 1 ]] && [[ -f "$shim_path.archer-bak" ]]; then
        run_sudo mv "$shim_path.archer-bak" "$shim_path"
    fi
}

module_install() {
    # Ensure NVIDIA driver is installed
    if ! pacman -Qi nvidia &>/dev/null && ! pacman -Qi nvidia-dkms &>/dev/null; then
        log "NVIDIA driver not installed. Installing nvidia-dkms..."
        run_sudo pacman -S --needed --noconfirm nvidia-dkms nvidia-utils
        INSTALLED_PACKAGES+=" nvidia-dkms nvidia-utils"
    fi

    # Install EnvyControl
    if [[ -n "$AUR_HELPER" ]]; then
        log "Installing EnvyControl via $AUR_HELPER..."
        run "$AUR_HELPER" -S --needed --noconfirm envycontrol
    else
        log "No AUR helper found. Installing EnvyControl via pip..."
        run pip install envycontrol --break-system-packages 2>/dev/null || warn "pip install encountered issues."
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
    # Guarantee the shim is removed and any original wrapper restored even if
    # envycontrol exits non-zero or the function returns early.
    trap '_gpu_restore_mkinitcpio "$_shim_path" "$_had_existing"' RETURN

    if [[ "$gpu_mode" = "hybrid" ]]; then
        run_sudo envycontrol -s hybrid --rtd3 2 || { warn "envycontrol failed to set hybrid mode."; return 1; }
    else
        run_sudo envycontrol -s "$gpu_mode" || { warn "envycontrol failed to set $gpu_mode mode."; return 1; }
    fi

    # Restore original wrapper now (clear the trap so it doesn't run twice).
    _gpu_restore_mkinitcpio "$_shim_path" "$_had_existing"
    trap - RETURN

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
        trap '_gpu_restore_mkinitcpio "$_shim_path" "$_had_existing"' RETURN

        run_sudo envycontrol --reset 2>/dev/null || true

        _gpu_restore_mkinitcpio "$_shim_path" "$_had_existing"
        trap - RETURN

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
