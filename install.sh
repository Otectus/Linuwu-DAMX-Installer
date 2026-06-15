#!/usr/bin/env bash
# Archer Compatibility Suite v2.0
# Comprehensive Acer laptop compatibility suite for Arch Linux
# Supports: Nitro, Predator, Helios, Triton, Swift, Aspire, and more

set -euo pipefail

# --- Resolve script directory ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --- Source libraries ---
source "$SCRIPT_DIR/lib/utils.sh"
source "$SCRIPT_DIR/lib/modules.sh"
source "$SCRIPT_DIR/lib/detect.sh"
source "$SCRIPT_DIR/lib/manifest.sh"

# --- Module registry (defined in lib/modules.sh) ---
MODULE_SELECTED=()
INSTALLED_FILES=""
INSTALLED_DKMS=""
INSTALLED_PACKAGES=""

# --- CLI argument parsing ---
SELECT_ALL_RECOMMENDED=0
EXPLICIT_MODULES=""
SHOW_HELP=0
SHOW_VERSION=0
VERIFY_ONLY=0

parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --all)        SELECT_ALL_RECOMMENDED=1 ;;
            --modules)    EXPLICIT_MODULES="$2"; shift ;;
            --no-confirm) NO_CONFIRM=1 ;;
            --dry-run)    DRY_RUN=1 ;;
            --verbose)    VERBOSE=1 ;;
            --log)        LOG_FILE="$2"; shift ;;
            --verify)     VERIFY_ONLY=1 ;;
            --help|-h)    SHOW_HELP=1 ;;
            --version|-v) SHOW_VERSION=1 ;;
            *) error "Unknown option: $1. Use --help for usage." ;;
        esac
        shift
    done
}

show_help() {
    echo "Archer Compatibility Suite v${INSTALLER_VERSION}"
    echo ""
    echo "Usage: ./install.sh [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  --all            Install all recommended modules (non-interactive)"
    echo "  --modules LIST   Comma-separated list of modules to install"
    echo "  --verify         Check status of previously installed modules"
    echo "  --no-confirm     Skip all confirmation prompts"
    echo "  --dry-run        Show what would be done without making changes"
    echo "  --verbose        Enable debug output for troubleshooting"
    echo "  --log FILE       Write all output to FILE (in addition to console)"
    echo "  --help, -h       Show this help message"
    echo "  --version, -v    Show version"
    echo ""
    echo "Available modules:"
    echo "  driver      Linuwu-Sense kernel driver for fan/RGB hardware access (DKMS)"
    echo "  battery     Limits battery charging to 80% via acer-wmi-battery"
    echo "  gpu         EnvyControl for NVIDIA Optimus hybrid graphics switching"
    echo "  touchpad    Fix I2C HID touchpad detection (module reload, kernel params)"
    echo "  audio       SOF firmware, ALSA configuration, and audio codec fixes"
    echo "  wifi        Diagnose and fix WiFi/Bluetooth issues for various chipsets"
    echo "  power       TLP power management with Acer-optimized configuration"
    echo "  thermal     Native kernel thermal profiles via acer_wmi (kernel 6.8+)"
    echo "  gui         GTK4/Adwaita control panel and hardware daemon"
    echo "  gamemode    Linux Game Mode with performance governor switching"
    echo "  audio-enhance  Noise suppression via PipeWire/rnnoise"
    echo "  camera-enhance Virtual camera with background blur (v4l2loopback)"
    echo "  firmware    Firmware update advisor via fwupd"
    echo ""
    echo "Interactive mode (default): Detects hardware and presents a menu."
}

# --- Menu display and interaction ---
display_menu() {
    echo ""
    echo -e "${_BOLD}=== Archer Compatibility Suite v${INSTALLER_VERSION} ===${_RESET}"
    echo ""
    print_hw_summary
    echo ""
    echo -e "${_BOLD}Select modules to install:${_RESET}"

    for i in "${!MODULE_IDS[@]}"; do
        local id="${MODULE_IDS[$i]}"
        local label="${MODULE_LABELS[$i]}"
        local num=$((i + 1))
        local marker=" "
        local tag=""

        # Determine tag
        if is_in_list "$id" "${RECOMMENDED_MODULES[*]}"; then
            tag="${_GREEN}[RECOMMENDED]${_RESET}"
        elif is_in_list "$id" "${OPTIONAL_MODULES[*]}"; then
            tag="[OPTIONAL]"
        fi

        # Check conflicts
        if [[ "$id" = "thermal" ]] && [[ "${MODULE_SELECTED[0]}" -eq 1 ]]; then
            tag="${_RED}[CONFLICTS WITH #1]${_RESET}"
        fi
        if [[ "$id" = "driver" ]] && [[ "${MODULE_SELECTED[7]}" -eq 1 ]]; then
            tag="${_RED}[CONFLICTS WITH #8]${_RESET}"
        fi

        # GUI dependency hint
        if [[ "$id" = "gui" ]] && [[ "${MODULE_SELECTED[0]}" -eq 0 ]]; then
            tag="${tag} ${_YELLOW}(needs #1 Linuwu-Sense)${_RESET}"
        fi

        # Selection marker
        if [[ "${MODULE_SELECTED[$i]}" -eq 1 ]]; then
            marker="${_GREEN}*${_RESET}"
        fi

        printf "  [%b] %d. %-40s %b\n" "$marker" "$num" "$label" "$tag"
    done

    echo ""
    echo "Toggle: Enter number (1-${#MODULE_IDS[@]}) | a=all recommended | n=none | c=confirm"
}

is_in_list() {
    local item="$1"
    local list="$2"
    [[ " $list " == *" $item "* ]]
}

init_selections() {
    MODULE_SELECTED=()
    for i in "${!MODULE_IDS[@]}"; do
        local id="${MODULE_IDS[$i]}"
        if is_in_list "$id" "${RECOMMENDED_MODULES[*]}"; then
            MODULE_SELECTED+=(1)
        else
            MODULE_SELECTED+=(0)
        fi
    done
}

check_conflicts() {
    # driver (#0) and thermal (#7) conflict
    if [[ "${MODULE_SELECTED[0]}" -eq 1 ]] && [[ "${MODULE_SELECTED[7]}" -eq 1 ]]; then
        warn "Linuwu-Sense driver and Kernel Thermal Profiles both selected."
        warn "These conflict: Linuwu-Sense blacklists acer_wmi, which thermal profiles require."
        warn "Please deselect one of them."
        return 1
    fi
    return 0
}

run_menu() {
    while true; do
        display_menu
        read -rp "> " choice

        case "$choice" in
            [1-9]|[1-9][0-9])
                if [[ "$choice" -le "${#MODULE_IDS[@]}" ]] 2>/dev/null; then
                    local idx=$((choice - 1))
                    if [[ "${MODULE_SELECTED[$idx]}" -eq 1 ]]; then
                        MODULE_SELECTED[idx]=0
                    else
                        MODULE_SELECTED[idx]=1
                    fi
                else
                    warn "Invalid number. Enter 1-${#MODULE_IDS[@]}, a, n, or c."
                fi
                ;;
            a|A)
                init_selections
                ;;
            n|N)
                for i in "${!MODULE_SELECTED[@]}"; do
                    MODULE_SELECTED[i]=0
                done
                ;;
            c|C)
                if check_conflicts; then
                    break
                fi
                ;;
            *)
                warn "Invalid input. Enter 1-${#MODULE_IDS[@]}, a, n, or c."
                ;;
        esac
    done
}

# --- Module execution ---
install_shared_deps() {
    log "Installing shared system dependencies..."
    debug "Kernel headers package: $KERNEL_HEADERS"

    # Verify the kernel headers package exists in repos before attempting install
    if ! pacman -Si "$KERNEL_HEADERS" &>/dev/null && ! pacman -Qi "$KERNEL_HEADERS" &>/dev/null; then
        warn "Kernel headers package '$KERNEL_HEADERS' not found in repos or installed."
        warn "DKMS modules may fail to build. Check: pacman -Ss headers"
    fi

    local deps=(base-devel dkms git curl "$KERNEL_HEADERS" python-pip)

    # Clang-built kernels require clang/llvm toolchain for DKMS module compilation
    if [[ "$IS_CLANG_KERNEL" -eq 1 ]]; then
        log "Clang-built kernel detected — including LLVM toolchain for DKMS builds."
        deps+=(clang llvm)
    fi

    run_sudo pacman -Syu --needed --noconfirm "${deps[@]}"
}

run_selected_modules() {
    local installed_names=()

    for i in "${!MODULE_IDS[@]}"; do
        if [[ "${MODULE_SELECTED[$i]}" -eq 1 ]]; then
            local id="${MODULE_IDS[$i]}"
            local label="${MODULE_LABELS[$i]}"

            # GUI dependency warning (driver-or-already-installed check)
            if [[ "$id" = "gui" ]]; then
                if ! is_in_list "driver" "${installed_names[*]}" && \
                   ! dkms status 2>/dev/null | grep -q "linuwu-sense"; then
                    warn "Linuwu-Sense driver not installed. The daemon will have limited functionality."
                    warn "Consider installing the 'driver' module for full hardware control."
                fi
            fi

            section "Installing: $label"
            # Snapshot manifest accumulators so a failed module's partial writes
            # don't leak into the saved manifest.
            local _files_pre="$INSTALLED_FILES"
            local _dkms_pre="$INSTALLED_DKMS"
            local _pkgs_pre="$INSTALLED_PACKAGES"

            source "$SCRIPT_DIR/modules/${id}.sh"
            if ! module_install; then
                warn "Module $id failed to install. Rolling back manifest entries; continuing with remaining modules."
                INSTALLED_FILES="$_files_pre"
                INSTALLED_DKMS="$_dkms_pre"
                INSTALLED_PACKAGES="$_pkgs_pre"
                continue
            fi
            installed_names+=("$id")
        fi
    done

    # Write manifest with only modules that actually installed cleanly.
    local modules_joined="${installed_names[*]}"
    if [[ -z "$modules_joined" ]]; then
        warn "No modules installed successfully — skipping manifest write."
        return
    fi
    write_manifest "$modules_joined" "$INSTALLED_FILES" "$INSTALLED_DKMS" "$INSTALLED_PACKAGES"
}

verify_modules() {
    section "Verification"
    local total=0
    local passed=0

    for i in "${!MODULE_IDS[@]}"; do
        if [[ "${MODULE_SELECTED[$i]}" -eq 1 ]]; then
            local id="${MODULE_IDS[$i]}"
            local label="${MODULE_LABELS[$i]}"
            total=$((total + 1))

            # Re-source to restore this module's function definitions (each module
            # overrides the same names: module_verify, module_install, etc.)
            source "$SCRIPT_DIR/modules/${id}.sh"
            if module_verify; then
                success "$label"
                passed=$((passed + 1))
            else
                warn "$label (check warnings above)"
            fi
        fi
    done

    echo ""
    log "Verification: $passed/$total modules passed"
}

# --- Main entry point ---
main() {
    parse_args "$@"

    if [[ "$SHOW_VERSION" -eq 1 ]]; then
        echo "Archer Compatibility Suite v${INSTALLER_VERSION}"
        exit 0
    fi
    if [[ "$SHOW_HELP" -eq 1 ]]; then
        show_help
        exit 0
    fi

    # Move any legacy manifest into the new system path before any read.
    migrate_legacy_manifest

    # Standalone verify mode: check installed modules from manifest
    if [[ "$VERIFY_ONLY" -eq 1 ]]; then
        if ! has_manifest; then
            error "No install manifest found. Nothing to verify."
        fi
        section "Verifying Installed Modules"
        local mods
        mods=$(read_manifest_modules)
        local total=0
        local passed=0
        for id in $mods; do
            if ! is_known_module "$id"; then
                warn "Manifest references unknown module '$id' — skipping (refusing to source untrusted name)."
                continue
            fi
            local mod_file="$SCRIPT_DIR/modules/${id}.sh"
            if [[ -f "$mod_file" ]]; then
                total=$((total + 1))
                source "$mod_file"
                if module_verify; then
                    success "$MODULE_NAME"
                    passed=$((passed + 1))
                else
                    warn "$MODULE_NAME (check warnings above)"
                fi
            else
                warn "Module file not found: $mod_file"
            fi
        done
        echo ""
        log "Verification: $passed/$total modules passed"
        exit 0
    fi

    if [[ "$DRY_RUN" -eq 1 ]]; then
        log "DRY RUN mode enabled. No changes will be made."
    fi

    # Run hardware detection
    log "Detecting hardware..."
    detect_all
    build_recommendations

    # Vendor check
    if [[ "$ACER_SYS_VENDOR" != *"Acer"* ]] && [[ "$ACER_PRODUCT_NAME" == "Unknown" ]]; then
        warn "This does not appear to be an Acer system."
        warn "Some modules may not function correctly."
    fi

    # Distro check
    if [[ "$DISTRO_FAMILY" != "arch" ]]; then
        warn "This installer is designed for Arch-based distributions."
        warn "Detected: ${DISTRO_NAME:-Unknown} (family: $DISTRO_FAMILY)"
        confirm "Continue anyway?" || exit 0
    fi

    # Initialize selections
    init_selections

    # Handle non-interactive modes
    if [[ -n "$EXPLICIT_MODULES" ]]; then
        # Reset all, then select explicit modules
        for i in "${!MODULE_SELECTED[@]}"; do
            MODULE_SELECTED[i]=0
        done
        IFS=',' read -ra explicit_list <<< "$EXPLICIT_MODULES"
        for mod in "${explicit_list[@]}"; do
            if ! is_known_module "$mod"; then
                error "Unknown or invalid module: '$mod' (available: ${MODULE_IDS[*]})"
            fi
            for i in "${!MODULE_IDS[@]}"; do
                if [[ "${MODULE_IDS[$i]}" = "$mod" ]]; then
                    MODULE_SELECTED[i]=1
                fi
            done
        done
        if ! check_conflicts; then
            error "Module conflict detected. Aborting."
        fi
    elif [[ "$SELECT_ALL_RECOMMENDED" -eq 1 ]]; then
        # Already initialized with recommendations
        :
    else
        # Interactive menu
        run_menu
    fi

    # Count selected modules
    local count=0
    for sel in "${MODULE_SELECTED[@]}"; do
        count=$((count + sel))
    done
    if [[ "$count" -eq 0 ]]; then
        log "No modules selected. Nothing to install."
        exit 0
    fi

    # Display selected modules
    section "Installation Plan"
    for i in "${!MODULE_IDS[@]}"; do
        if [[ "${MODULE_SELECTED[$i]}" -eq 1 ]]; then
            echo "  - ${MODULE_LABELS[$i]}"
        fi
    done
    echo ""

    if [[ "$NO_CONFIRM" -eq 0 ]] && [[ "$SELECT_ALL_RECOMMENDED" -eq 0 ]] && [[ -z "$EXPLICIT_MODULES" ]]; then
        confirm "Proceed with installation?" || exit 0
    fi

    # Install shared dependencies
    install_shared_deps

    # Run selected modules
    run_selected_modules

    # Verify
    verify_modules

    # Final summary
    section "Installation Complete"
    success "All selected modules have been installed."

    if [[ "$REBOOT_REQUIRED" -eq 1 ]]; then
        echo ""
        warn "A reboot is required for some changes to take effect."
    fi

    echo ""
    log "Manifest saved to: $MANIFEST_FILE"
    log "To uninstall, run: ./uninstall.sh"
}

# Only run main when executed directly (not when sourced for testing)
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
