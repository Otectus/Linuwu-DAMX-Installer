#!/usr/bin/env fish

set SERVICE_NAME "DAMX-Daemon.service"
set SERVICE_PATH "$HOME/.config/systemd/user/$SERVICE_NAME"
set SCRIPT_DIR (pwd)

echo ">>> Installing $SERVICE_NAME..."

# Ensure systemd user dir exists
mkdir -p ~/.config/systemd/user

# Copy service file
cp $SCRIPT_DIR/$SERVICE_NAME $SERVICE_PATH

# Reload systemd and enable service
systemctl --user daemon-reexec
systemctl --user daemon-reload
systemctl --user enable --now $SERVICE_NAME

echo "✅ $SERVICE_NAME installed and enabled."
echo "Check status with: systemctl --user status $SERVICE_NAME"
