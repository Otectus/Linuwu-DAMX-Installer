#!/usr/bin/env fish
# Linuwu-DAMX Unified Uninstaller (Fish version)

function log
    echo (set_color yellow)">>> "(set_color normal)$argv
end

# 1. Disable Services
log "Stopping and disabling DAMX Daemon..."
systemctl --user disable --now damx-daemon.service 2>/dev/null
rm -f $HOME/.config/systemd/user/damx-daemon.service
systemctl --user daemon-reload

# 2. Remove Driver (DKMS)
log "Removing Linuwu-Sense DKMS module..."
sudo dkms remove -m linuwu-sense -v 1.0 --all 2>/dev/null
sudo rm -rf /usr/src/linuwu-sense-1.0

# 3. Remove Blacklist
log "Restoring acer_wmi (removing blacklist)..."
sudo rm -f /etc/modprobe.d/blacklist-acer-wmi.conf

# 4. Clean Files
type -q damx; and log "Removing DAMX files..."
rm -rf $HOME/.local/share/damx

log "Cleanup complete. \u2705"
log "You may need to reboot to restore the default 'acer_wmi' driver functions."