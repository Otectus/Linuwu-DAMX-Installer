#!/usr/bin/env bash
# Archer Compatibility Suite - Unified Uninstaller v2.0
# Supports manifest-based selective uninstall with legacy fallback

# Note: -e intentionally omitted so uninstall continues if individual steps fail
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Source utilities
source "$SCRIPT_DIR/lib/utils.sh"
source "$SCRIPT_DIR/lib/modules.sh"
source "$SCRIPT_DIR/lib/detect.sh"
source "$SCRIPT_DIR/lib/manifest.sh"

# Move any legacy manifest into the new system path before any read.
migrate_legacy_manifest

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run)    DRY_RUN=1 ;;
        --no-confirm) NO_CONFIRM=1 ;;
        --help|-h)
            echo "Archer Compatibility Suite - Uninstaller v${INSTALLER_VERSION}"
            echo ""
            echo "Usage: ./uninstall.sh [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --dry-run        Show what would be removed without making changes"
            echo "  --no-confirm     Skip confirmation prompts"
            echo "  --help, -h       Show this help message"
            exit 0
            ;;
        *) warn "Unknown option: $1" ;;
    esac
    shift
done

if [[ "$DRY_RUN" -eq 1 ]]; then
    log "DRY RUN mode enabled. No changes will be made."
fi

section "Archer Compatibility Suite - Uninstaller"

if has_manifest; then
    log "Install manifest found. Performing targeted uninstall."
    echo ""

    INSTALLED_MODS=$(read_manifest_modules)
    log "Installed modules: $INSTALLED_MODS"
    echo ""

    for mod in $INSTALLED_MODS; do
        # Allowlist gate: reject path-traversal or arbitrary names from a
        # tampered manifest before sourcing. is_known_module enforces both
        # the safe-name regex and the canonical MODULE_IDS list.
        if ! is_known_module "$mod"; then
            warn "Refusing to source unknown module name '$mod' from manifest (skipping)."
            echo ""
            continue
        fi
        local_mod_file="$SCRIPT_DIR/modules/${mod}.sh"
        if [[ -f "$local_mod_file" ]]; then
            log "Uninstalling: $mod"
            source "$local_mod_file"
            module_uninstall
            success "Removed: $mod"
        else
            warn "Module file not found: $local_mod_file (skipping)"
        fi
        echo ""
    done

    # Remove manifest
    remove_manifest
    log "Install manifest removed."

else
    warn "No install manifest found. Performing legacy uninstall."
    warn "This will attempt to remove all known components."
    echo ""

    # Legacy uninstall: same as original v1 behavior
    # 1. Disable Services (legacy DAMX daemon cleanup)
    log "Checking for legacy DAMX daemon..."
    run systemctl --user disable --now damx-daemon.service 2>/dev/null || true
    run rm -f "$HOME/.config/systemd/user/damx-daemon.service"
    run systemctl --user daemon-reload

    # 2. Remove Driver (DKMS)
    log "Removing Linuwu-Sense DKMS module..."
    run_sudo dkms remove -m linuwu-sense -v 1.0 --all 2>/dev/null || true
    run_sudo rm -rf "/usr/src/linuwu-sense-1.0"

    # 3. Remove Blacklist
    log "Restoring acer_wmi (removing blacklist)..."
    run_sudo rm -f /etc/modprobe.d/blacklist-acer-wmi.conf

    # 4. Remove other possible configs from v2 modules
    run_sudo rm -f /etc/modprobe.d/touchpad-amd-fix.conf
    run_sudo rm -f /etc/modprobe.d/acer-audio-amd.conf
    run_sudo rm -f /etc/modprobe.d/acer-thermal-profiles.conf
    run_sudo rm -f /etc/udev/rules.d/99-acer-battery-health.rules
    run_sudo rm -f /etc/tlp.d/01-acer-optimize.conf

    # Remove touchpad service if present
    if [[ -f /etc/systemd/system/touchpad-fix.service ]]; then
        run_sudo systemctl disable touchpad-fix.service 2>/dev/null || true
        run_sudo rm -f /etc/systemd/system/touchpad-fix.service
        run_sudo systemctl daemon-reload
    fi

    # Remove acer-wmi-battery DKMS if present
    run_sudo dkms remove -m acer-wmi-battery -v 0.1.0 --all 2>/dev/null || true
    run_sudo rm -rf "/usr/src/acer-wmi-battery-0.1.0"

    # 5. Clean application files
    if [[ -n "${HOME:-}" && "$HOME" != "/" ]]; then
        log "Removing application data..."
        run rm -rf "$HOME/.local/share/damx"
        run rm -rf "$HOME/.local/share/archer"
    else
        warn "HOME is unset or '/'; refusing to rm -rf legacy application data."
    fi

    # 6. Remove Archer GUI if installed
    if [[ -d /opt/archer ]]; then
        log "Removing Archer GUI..."
        run_sudo systemctl disable --now archer-daemon.service 2>/dev/null || true
        run_sudo rm -f /etc/systemd/system/archer-daemon.service
        run_sudo systemctl daemon-reload
        run_sudo rm -rf /opt/archer
        run_sudo rm -f /usr/share/applications/io.github.archer.desktop
        run_sudo rm -f /usr/share/icons/hicolor/scalable/apps/io.github.archer.svg
        run_sudo rm -f /usr/local/bin/archer-gui
        run_sudo rm -rf /etc/archer
    fi

    # 7. Remove enhancement configs if present
    run_sudo rm -f /etc/gamemode.d/archer.ini
    run_sudo rm -f /etc/pipewire/filter-chain.conf.d/archer-noise-suppress.conf
    run_sudo rm -f /etc/modprobe.d/archer-v4l2loopback.conf
    run_sudo systemctl disable --now fwupd.service 2>/dev/null || true
fi

section "Cleanup Complete"
success "All installed components have been removed."
echo ""
warn "You may need to reboot to fully restore default driver behavior."
