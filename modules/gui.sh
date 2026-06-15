#!/usr/bin/env bash
# Module: Archer GUI
# GTK4/Adwaita control panel and system daemon for hardware management

MODULE_NAME="Archer GUI (Control Panel)"
MODULE_ID="gui"
MODULE_DESCRIPTION="GTK4/Adwaita control panel and hardware daemon"

_GUI_INSTALL_DIR="/opt/archer"
_GUI_SERVICE="/etc/systemd/system/archer-daemon.service"
_GUI_DESKTOP="/usr/share/applications/io.github.archer.desktop"
_GUI_ICON="/usr/share/icons/hicolor/scalable/apps/io.github.archer.svg"
_GUI_LAUNCHER="/usr/local/bin/archer-gui"
_GUI_SETTINGS_DIR="/etc/archer"

module_detect() {
    # Relevant if a display server is running (not headless/SSH)
    [[ -n "${DISPLAY:-}" ]] || [[ -n "${WAYLAND_DISPLAY:-}" ]]
}

module_check_installed() {
    [[ -f "$_GUI_INSTALL_DIR/archer_daemon.py" ]] && [[ -f "$_GUI_SERVICE" ]]
}

module_install() {
    # Verify all source files exist before any sudo write so a partial install
    # doesn't leave the system in a broken state.
    local _required=(
        "$SCRIPT_DIR/gui/archer_daemon.py"
        "$SCRIPT_DIR/gui/archer_dbus.py"
        "$SCRIPT_DIR/gui/archer_gui.py"
        "$SCRIPT_DIR/gui/io.otectus.Archer1.conf"
        "$SCRIPT_DIR/gui/io.otectus.Archer1.policy"
        "$SCRIPT_DIR/gui/archer-daemon.service"
        "$SCRIPT_DIR/gui/io.github.archer.desktop"
        "$SCRIPT_DIR/gui/assets/archer.svg"
    )
    local _src
    for _src in "${_required[@]}"; do
        [[ -f "$_src" ]] || error "Required GUI source file missing: $_src"
    done
    [[ -d "$SCRIPT_DIR/gui/archer" ]] || error "Required GUI package directory missing: $SCRIPT_DIR/gui/archer"
    [[ -d "$SCRIPT_DIR/gui/assets" ]] || error "Required GUI assets directory missing: $SCRIPT_DIR/gui/assets"

    # Install dependencies
    log "Installing GUI dependencies..."
    run_sudo pacman -S --needed --noconfirm python-gobject gtk4 libadwaita python python-pillow python-dbus

    # Create directories
    run_sudo mkdir -p "$_GUI_INSTALL_DIR"
    run_sudo mkdir -p "$_GUI_SETTINGS_DIR"

    # Copy application files
    log "Installing Archer GUI to $_GUI_INSTALL_DIR..."
    run_sudo cp "$SCRIPT_DIR/gui/archer_daemon.py" "$_GUI_INSTALL_DIR/"
    run_sudo cp "$SCRIPT_DIR/gui/archer_dbus.py" "$_GUI_INSTALL_DIR/"
    run_sudo cp "$SCRIPT_DIR/gui/archer_gui.py" "$_GUI_INSTALL_DIR/"
    run_sudo cp -r "$SCRIPT_DIR/gui/archer" "$_GUI_INSTALL_DIR/"
    run_sudo cp -r "$SCRIPT_DIR/gui/assets" "$_GUI_INSTALL_DIR/"

    # Install D-Bus service configuration
    log "Installing D-Bus and polkit configuration..."
    run_sudo cp "$SCRIPT_DIR/gui/io.otectus.Archer1.conf" /etc/dbus-1/system.d/
    run_sudo cp "$SCRIPT_DIR/gui/io.otectus.Archer1.policy" /usr/share/polkit-1/actions/

    # Reload dbus-daemon so the new policy file takes effect immediately.
    # Without this, the daemon can't claim io.otectus.Archer1 until reboot
    # (which is the symptom reported in issue #4).
    log "Reloading dbus-daemon to pick up new policy..."
    if ! run_sudo systemctl reload dbus.service 2>/dev/null; then
        # Fallback for systems where dbus.service has no reload action.
        local dbus_pid
        dbus_pid="$(pidof dbus-daemon 2>/dev/null | awk '{print $1}')"
        if [[ -n "$dbus_pid" ]]; then
            run_sudo kill -HUP "$dbus_pid" || warn "Could not signal dbus-daemon (PID $dbus_pid)."
        else
            warn "dbus-daemon not found; the new policy may require a reboot to take effect."
        fi
    fi

    # Set permissions
    run_sudo chmod 755 "$_GUI_INSTALL_DIR/archer_daemon.py"
    run_sudo chmod 755 "$_GUI_INSTALL_DIR/archer_gui.py"

    # Install systemd service
    log "Installing daemon service..."
    run_sudo cp "$SCRIPT_DIR/gui/archer-daemon.service" "$_GUI_SERVICE"
    run_sudo systemctl daemon-reload
    run_sudo systemctl enable archer-daemon.service

    # Start daemon (may fail if Linuwu-Sense not yet loaded)
    if ! run_sudo systemctl start archer-daemon.service 2>/dev/null; then
        warn "Daemon did not start — Linuwu-Sense driver may not be loaded yet."
        warn "It will start automatically after reboot if the driver module is installed."
    fi

    # Verify the bus name is claimable. Best-effort: skip during dry-run and
    # if busctl is unavailable. A failure here is a warning, not a hard error,
    # because the daemon may legitimately not be running yet (e.g. driver
    # module not loaded). The reboot-as-workaround footgun is gone either way.
    if [[ "${DRY_RUN:-0}" -ne 1 ]] && has_cmd busctl; then
        if ! busctl --no-pager list 2>/dev/null | grep -q "io.otectus.Archer1"; then
            warn "io.otectus.Archer1 not yet visible on the system bus."
            warn "Check 'systemctl status archer-daemon' once the driver module is loaded."
        fi
    fi

    # Install desktop entry
    log "Installing desktop entry..."
    run_sudo cp "$SCRIPT_DIR/gui/io.github.archer.desktop" "$_GUI_DESKTOP"

    # Install icon
    run_sudo mkdir -p "$(dirname "$_GUI_ICON")"
    run_sudo cp "$SCRIPT_DIR/gui/assets/archer.svg" "$_GUI_ICON"
    run_sudo gtk-update-icon-cache /usr/share/icons/hicolor/ 2>/dev/null || true

    # Create launcher script
    log "Creating launcher script..."
    run_sudo tee "$_GUI_LAUNCHER" > /dev/null <<'LAUNCHER_EOF'
#!/bin/bash
exec python3 /opt/archer/archer_gui.py "$@"
LAUNCHER_EOF
    run_sudo chmod 755 "$_GUI_LAUNCHER"

    # Check for Linuwu-Sense driver
    if ! dkms status 2>/dev/null | grep -q "linuwu-sense"; then
        warn "Linuwu-Sense driver not detected. The daemon will have limited functionality."
        warn "Install the 'driver' module for full hardware control."
    fi

    log "Archer GUI installed."
    log "Start the GUI:  archer-gui"
    log "Daemon status:  sudo systemctl status archer-daemon"

    INSTALLED_FILES+=" $_GUI_INSTALL_DIR $_GUI_SERVICE $_GUI_DESKTOP $_GUI_ICON $_GUI_LAUNCHER $_GUI_SETTINGS_DIR /etc/dbus-1/system.d/io.otectus.Archer1.conf /usr/share/polkit-1/actions/io.otectus.Archer1.policy"
    INSTALLED_PACKAGES+=" python-gobject gtk4 libadwaita python-pillow python-dbus"
}

module_uninstall() {
    log "Stopping Archer daemon..."
    run_sudo systemctl disable --now archer-daemon.service 2>/dev/null || true
    run_sudo rm -f "$_GUI_SERVICE"
    run_sudo systemctl daemon-reload

    log "Removing Archer GUI files..."
    run_sudo rm -rf "$_GUI_INSTALL_DIR"
    run_sudo rm -f "$_GUI_DESKTOP"
    run_sudo rm -f "$_GUI_ICON"
    run_sudo rm -f "$_GUI_LAUNCHER"
    run_sudo rm -rf "$_GUI_SETTINGS_DIR"

    log "Removing D-Bus and polkit configuration..."
    run_sudo rm -f /etc/dbus-1/system.d/io.otectus.Archer1.conf
    run_sudo rm -f /usr/share/polkit-1/actions/io.otectus.Archer1.policy

    # Reload dbus-daemon so the removed policy stops being active immediately.
    if ! run_sudo systemctl reload dbus.service 2>/dev/null; then
        local dbus_pid
        dbus_pid="$(pidof dbus-daemon 2>/dev/null | awk '{print $1}')"
        if [[ -n "$dbus_pid" ]]; then
            run_sudo kill -HUP "$dbus_pid" || true
        fi
    fi

    # Clean up legacy socket/PID locations if lingering (pre-RuntimeDirectory).
    run_sudo rm -f /var/run/archer.sock 2>/dev/null || true
    run_sudo rm -f /var/run/archer-daemon.pid 2>/dev/null || true

    log "Archer GUI removed. Packages retained (remove manually with: sudo pacman -Rns python-gobject gtk4 libadwaita python-pillow)"
}

module_verify() {
    local ok=0

    if [[ ! -f "$_GUI_INSTALL_DIR/archer_daemon.py" ]]; then
        warn "Daemon not found at $_GUI_INSTALL_DIR"
        ok=1
    fi

    if ! systemctl is-enabled --quiet archer-daemon.service 2>/dev/null; then
        warn "Daemon service not enabled"
        ok=1
    fi

    if [[ ! -f "$_GUI_DESKTOP" ]]; then
        warn "Desktop entry not found"
        ok=1
    fi

    return $ok
}
