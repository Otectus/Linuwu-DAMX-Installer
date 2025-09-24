#!/usr/bin/env fish

set MODULE_DIR "$HOME/src/Linuwu-Sense"

if not test -d $MODULE_DIR
    echo "❌ Linuwu-Sense source directory not found at $MODULE_DIR"
    exit 1
end

echo ">>> Installing rebuild script and service for Linuwu-Sense..."

# Write rebuild script
set SCRIPT_PATH "/usr/local/bin/linuwu_rebuild.sh"
echo '#!/bin/bash
cd $MODULE_DIR
make clean
make LLVM=1 CC=clang install' | sudo tee $SCRIPT_PATH > /dev/null
sudo chmod +x $SCRIPT_PATH

# Write systemd service
set SERVICE_PATH "/etc/systemd/system/linuwu-rebuild.service"
echo '[Unit]
Description=Rebuild Linuwu-Sense Kernel Module After Boot
After=multi-user.target

[Service]
Type=oneshot
ExecStart=/usr/local/bin/linuwu_rebuild.sh

[Install]
WantedBy=multi-user.target' | sudo tee $SERVICE_PATH > /dev/null

# Reload systemd and enable the service
sudo systemctl daemon-reexec
sudo systemctl enable linuwu-rebuild.service

echo "✅ linuwu-rebuild.service installed and enabled."