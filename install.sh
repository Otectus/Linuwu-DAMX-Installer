#!/usr/bin/env bash
# Linuwu-DAMX Unified One-Click Setup (Bash version)
# Targeted for Arch Linux / CachyOS (Acer Laptops)

set -euo pipefail

REPO_DRIVER="https://github.com/0x7375646F/Linuwu-Sense.git"
REPO_APP="PXDiv/Div-Acer-Manager-Max"
INSTALL_DIR="$HOME/.local/share/damx"
MODULE_NAME="linuwu_sense"

log() { echo -e "\033[0;36m>>>\033[0m $*"; }
error() { echo -e "\033[0;31m\033[0m $*"; exit 1; }

# 1. Compatibility Check
ACER_MODEL=$(cat /sys/devices/virtual/dmi/id/product_name)
log "Detected Acer model: $ACER_MODEL"
if [[ ! "$ACER_MODEL" =~ (Nitro|Predator|Helios|Triton) ]]; then
    echo -e "\033[0;33m\u26a0 Warning: Model not explicitly supported. Proceeding anyway...\033[0m"
fi

# 2. Dependency Installation
log "Installing system dependencies..."
KERNEL_HEADERS="linux-headers"
if [[ "$(uname -r)" == *"cachyos"* ]]; then
    KERNEL_HEADERS="linux-cachyos-headers"
fi

sudo pacman -Syu --needed --noconfirm base-devel dkms git curl "$KERNEL_HEADERS" python-pip

# 3. Kernel Module (Linuwu-Sense) via DKMS
log "Setting up $MODULE_NAME via DKMS..."
SRC_DIR="/usr/src/linuwu-sense-1.0"
sudo rm -rf "$SRC_DIR"
sudo git clone "$REPO_DRIVER" "$SRC_DIR"

# Determine Compiler Flags
MAKE_FLAGS=""
if grep -q "clang" /proc/version; then
    log "Clang kernel detected. Using LLVM flags."
    MAKE_FLAGS="LLVM=1 CC=clang"
fi

# Create DKMS Config
sudo tee "$SRC_DIR/dkms.conf" > /dev/null <<DKMS_EOF
PACKAGE_NAME="linuwu-sense"
PACKAGE_VERSION="1.0"
CLEAN="make clean"
MAKE[0]="make KVERSION=\\\$kernelver $MAKE_FLAGS"
BUILT_MODULE_NAME[0]="$MODULE_NAME"
DEST_MODULE_LOCATION[0]="/kernel/drivers/platform/x86"
AUTOINSTALL="yes"
DKMS_EOF

sudo dkms add -m linuwu-sense -v 1.0 || true
sudo dkms install -m linuwu-sense -v 1.0

# Blacklist acer_wmi
log "Blacklisting acer_wmi..."
echo "blacklist acer_wmi" | sudo tee /etc/modprobe.d/blacklist-acer-wmi.conf > /dev/null

# 4. DAMX GUI & Daemon Setup
log "Fetching latest DAMX..."
mkdir -p "$INSTALL_DIR"
cd "$INSTALL_DIR"

LATEST_RELEASE=$(curl -s "https://api.github.com/repos/$REPO_APP/releases/latest" | python3 -c "import sys, json; print(json.load(sys.stdin)['tag_name'])")
log "Latest version found: $LATEST_RELEASE"

V_NUM=$(echo "$LATEST_RELEASE" | sed 's/v//')
DL_URL="https://github.com/$REPO_APP/releases/download/$LATEST_RELEASE/DAMX-$V_NUM.tar.xz"
curl -L "$DL_URL" -o damx.tar.xz
tar -xf damx.tar.xz --strip-components=1

pip install -r requirements.txt --break-system-packages > /dev/null 2>&1 || log "Warning: pip install encountered issues."

# 5. Systemd Service Setup
log "Configuring systemd units..."
SERVICE_FILE="$HOME/.config/systemd/user/damx-daemon.service"
mkdir -p "$(dirname "$SERVICE_FILE")"

tee "$SERVICE_FILE" > /dev/null <<SERVICE_EOF
[Unit]
Description=DAMX Daemon - Fan & RGB Manager
After=graphical-session.target

[Service]
ExecStart=$INSTALL_DIR/DAMX.py --daemon
Restart=on-failure
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target
SERVICE_EOF

systemctl --user daemon-reload
systemctl --user enable --now damx-daemon.service

log "Installation complete! \u2705"
log "Check service status: systemctl --user status damx-daemon"
