#!/usr/bin/env fish

set SERVICE_NAME "DAMX-Daemon.service"
set SERVICE_PATH "$HOME/.config/systemd/user/$SERVICE_NAME"

echo ">>> Removing $SERVICE_NAME..."

systemctl --user disable --now $SERVICE_NAME
rm -f $SERVICE_PATH

systemctl --user daemon-reexec
systemctl --user daemon-reload

echo "🗑️  $SERVICE_NAME removed and disabled."
