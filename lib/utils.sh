#!/usr/bin/env bash
# Shared utility functions for Archer Compatibility Suite (Bash)

# Colors
_CYAN="\033[0;36m"
_RED="\033[0;31m"
_YELLOW="\033[0;33m"
_GREEN="\033[0;32m"
_BOLD="\033[1m"
_RESET="\033[0m"

INSTALLER_VERSION="2.0.1"
DRY_RUN="${DRY_RUN:-0}"
NO_CONFIRM="${NO_CONFIRM:-0}"
VERBOSE="${VERBOSE:-0}"
LOG_FILE="${LOG_FILE:-}"
REBOOT_REQUIRED=0

# Internal logging helper: writes to stdout and optionally to a log file
_emit() {
    echo -e "$*"
    if [[ -n "${LOG_FILE:-}" ]]; then
        # Strip ANSI color codes for log file
        echo -e "$*" | sed 's/\x1b\[[0-9;]*m//g' >> "$LOG_FILE" 2>/dev/null || true
    fi
    return 0
}

log()     { _emit "${_CYAN:-}>>>${_RESET:-} $*"; return 0; }
warn()    { _emit "${_YELLOW:-}\u26a0${_RESET:-}  $*"; return 0; }
error()   { _emit "${_RED:-}\u274c${_RESET:-} $*"; exit 1; }
success() { _emit "${_GREEN:-}\u2705${_RESET:-} $*"; return 0; }
debug() {
    if [[ "${VERBOSE:-0}" -eq 1 ]]; then
        _emit "${_BOLD:-}[DEBUG]${_RESET:-} $*"
    fi
    return 0
}

# Execute a command, or print it in dry-run mode
run() {
    if [[ "${DRY_RUN:-0}" -eq 1 ]]; then
        echo -e "${_YELLOW:-}[DRY RUN]${_RESET:-} $*"
        return 0
    fi
    "$@"
}

# Execute a command with sudo, or print it in dry-run mode
run_sudo() {
    if [[ "${DRY_RUN:-0}" -eq 1 ]]; then
        echo -e "${_YELLOW:-}[DRY RUN]${_RESET:-} sudo $*"
        return 0
    fi
    sudo "$@"
}

# Execute a command with sudo and a timeout
# Usage: run_sudo_timeout <seconds> <command...>
run_sudo_timeout() {
    local timeout_secs="${1:-300}"
    shift
    if [[ "${DRY_RUN:-0}" -eq 1 ]]; then
        echo -e "${_YELLOW:-}[DRY RUN]${_RESET:-} sudo (timeout ${timeout_secs}s) $*"
        return 0
    fi
    timeout --signal=TERM --kill-after=30 "$timeout_secs" sudo "$@"
}

# Rebuild initramfs for the current kernel only (with timeout)
# Falls back to mkinitcpio -P if preset detection fails
rebuild_initramfs() {
    local kernel_version
    kernel_version="$(uname -r)"
    local preset="/etc/mkinitcpio.d/${kernel_version%.*}.preset"

    # Try common preset naming patterns
    if [[ ! -f "$preset" ]]; then
        # Try exact kernel version match
        preset="/etc/mkinitcpio.d/${kernel_version}.preset"
    fi
    if [[ ! -f "$preset" ]]; then
        # Try matching by major version (e.g., linux, linux-lts, linux-cachyos)
        local found_preset=""
        for p in /etc/mkinitcpio.d/*.preset; do
            [[ -f "$p" ]] || continue
            local pname
            pname="$(basename "$p" .preset)"
            if pacman -Qo "/usr/lib/modules/${kernel_version}" 2>/dev/null | grep -qF "$pname"; then
                found_preset="$p"
                break
            fi
        done
        if [[ -n "$found_preset" ]]; then
            preset="$found_preset"
        fi
    fi

    # Use /usr/bin/mkinitcpio directly to avoid any wrapper scripts (e.g.
    # CachyOS/Limine wrapper at /usr/local/bin/mkinitcpio that prompts
    # interactively and hangs non-interactive subprocess calls).
    local mkinitcpio_bin="/usr/bin/mkinitcpio"

    if [[ -f "$preset" ]]; then
        local preset_name
        preset_name="$(basename "$preset" .preset)"
        log "Regenerating initramfs for preset '$preset_name' (timeout 5min)..."
        if ! run_sudo_timeout 300 "$mkinitcpio_bin" -p "$preset_name"; then
            warn "Initramfs rebuild failed or timed out for '$preset_name'."
            warn "You may need to run 'sudo mkinitcpio -P' manually after reboot."
        fi
    else
        log "Could not detect kernel preset. Regenerating all initramfs (timeout 5min)..."
        if ! run_sudo_timeout 300 "$mkinitcpio_bin" -P; then
            warn "Initramfs rebuild failed or timed out."
            warn "You may need to run 'sudo mkinitcpio -P' manually after reboot."
        fi
    fi

    # If limine is in use, update its boot entries too
    if has_cmd limine-mkinitcpio; then
        log "Limine bootloader detected. Updating boot entries..."
        run_sudo_timeout 120 limine-mkinitcpio || warn "limine-mkinitcpio failed. Run it manually if needed."
    fi
}

# Prompt for confirmation (respects --no-confirm)
confirm() {
    local prompt="${1:-Continue?}"
    if [[ "${NO_CONFIRM:-0}" -eq 1 ]]; then
        return 0
    fi
    read -rp "$prompt [y/N]: " answer
    [[ "${answer,,}" == "y" ]]
}

# Mark that a reboot is needed
mark_reboot_required() {
    REBOOT_REQUIRED=1
}

# Detect the script's own directory
detect_script_dir() {
    cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd
}

# Print a section header
section() {
    echo ""
    echo -e "${_BOLD}=== $* ===${_RESET}"
    echo ""
    return 0
}

# Check if a command exists
has_cmd() {
    command -v "$1" &>/dev/null
}

# Safely add kernel parameters to GRUB config
# Usage: add_grub_params "param1 param2"
add_grub_params() {
    local params="$1"
    if [[ -f /etc/default/grub ]]; then
        local current
        current=$(grep "^GRUB_CMDLINE_LINUX_DEFAULT=" /etc/default/grub | sed 's/^GRUB_CMDLINE_LINUX_DEFAULT="//;s/"$//')
        # Only add params not already present
        local new_params=""
        for p in $params; do
            if ! echo "$current" | grep -qF "$p"; then
                new_params="$new_params $p"
            fi
        done
        if [[ -n "$new_params" ]]; then
            log "Adding kernel parameters to GRUB:$new_params"
            local updated="$new_params $current"
            # Use awk for safe replacement (no sed delimiter issues)
            local tmpfile
            tmpfile="$(mktemp)"
            run_sudo awk -v val="$updated" '/^GRUB_CMDLINE_LINUX_DEFAULT=/{print "GRUB_CMDLINE_LINUX_DEFAULT=\"" val "\""; next} {print}' \
                /etc/default/grub > "$tmpfile" && run_sudo mv "$tmpfile" /etc/default/grub
            run_sudo grub-mkconfig -o /boot/grub/grub.cfg
        fi
    elif [[ -d /boot/loader/entries ]]; then
        log "systemd-boot detected. Please manually add these kernel parameters:"
        log "  $params"
        log "  Edit files in /boot/loader/entries/ and add to the 'options' line."
    fi
}

# Safely remove kernel parameters from GRUB config
# Usage: remove_grub_params "param1 param2"
remove_grub_params() {
    local params="$1"
    if [[ -f /etc/default/grub ]]; then
        local needs_update=0
        for p in $params; do
            if grep -qF "$p" /etc/default/grub; then
                needs_update=1
                break
            fi
        done
        if [[ "$needs_update" -eq 1 ]]; then
            log "Removing kernel parameters from GRUB: $params"
            local current
            current=$(grep "^GRUB_CMDLINE_LINUX_DEFAULT=" /etc/default/grub | sed 's/^GRUB_CMDLINE_LINUX_DEFAULT="//;s/"$//')
            local updated="$current"
            for p in $params; do
                updated=$(echo "$updated" | sed "s|$p||g" | tr -s ' ')
            done
            local tmpfile
            tmpfile="$(mktemp)"
            run_sudo awk -v val="$updated" '/^GRUB_CMDLINE_LINUX_DEFAULT=/{print "GRUB_CMDLINE_LINUX_DEFAULT=\"" val "\""; next} {print}' \
                /etc/default/grub > "$tmpfile" && run_sudo mv "$tmpfile" /etc/default/grub
            run_sudo grub-mkconfig -o /boot/grub/grub.cfg
        fi
    fi
}
