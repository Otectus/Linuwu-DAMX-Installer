#!/usr/bin/env fish

set MODULE_DIR "$HOME/src/Linuwu-Sense"

if not test -d $MODULE_DIR
    echo "❌ Linuwu-Sense source directory not found at $MODULE_DIR"
    exit 1
end

echo ">>> Installing rebuild script and service for Linuwu-Sense..."

set SCRIPT_PATH "/usr/local/bin/linuwu_rebuild.sh"
set SERVICE_PATH "/etc/systemd/system/linuwu-rebuild.service"
set MODULE_DIR_ESCAPED (string escape --style=double $MODULE_DIR)

printf '#!/bin/bash
set -euo pipefail

MODULE_DIR=%s

if [[ ! -d "$MODULE_DIR" ]]; then
    echo "Linuwu-Sense source directory not found: $MODULE_DIR" >&2
    exit 1
fi

KVER="$(uname -r)"
BUILD_DIR="/usr/lib/modules/$KVER/build"
MAKE_FLAGS=()

if [[ -f "$BUILD_DIR/include/config/cc/version.text" ]]; then
    if grep -iq "clang" "$BUILD_DIR/include/config/cc/version.text"; then
        MAKE_FLAGS+=(LLVM=1)
        MAKE_FLAGS+=(CC=clang)
    fi
elif grep -iq "clang" /proc/version 2>/dev/null; then
    MAKE_FLAGS+=(LLVM=1)
    MAKE_FLAGS+=(CC=clang)
fi

cd "$MODULE_DIR"
make clean
make "${MAKE_FLAGS[@]}" install
' $MODULE_DIR_ESCAPED | sudo tee $SCRIPT_PATH > /dev/null

sudo chmod +x $SCRIPT_PATH

printf '[Unit]
Description=Rebuild Linuwu-Sense Kernel Module After Boot
After=multi-user.target

[Service]
Type=oneshot
ExecStart=%s

[Install]
WantedBy=multi-user.target
' $SCRIPT_PATH | sudo tee $SERVICE_PATH > /dev/null

sudo systemctl daemon-reload
sudo systemctl enable --now linuwu-rebuild.service

echo "✅ linuwu-rebuild.service installed and enabled."
