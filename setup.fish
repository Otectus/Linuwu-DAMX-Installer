#!/usr/bin/env fish
# Linuwu-DAMX Unified One-Click Setup
# Targeted for Arch Linux / CachyOS (Acer Laptops)

set REPO_DRIVER "https://github.com/0x7375646F/Linuwu-Sense.git"
set REPO_APP "PXDiv/Div-Acer-Manager-Max"
set INSTALL_DIR "$HOME/.local/share/damx"
set MODULE_NAME "linuwu_sense"

function log
    echo (set_color cyan)">>> "(set_color normal)$argv
end

function error
    echo (set_color red)"\u274c "(set_color normal)$argv
    exit 1
end

# 1. Compatibility Check
set ACER_MODEL (cat /sys/devices/virtual/dmi/id/product_name)
log "Detected Acer model: $ACER_MODEL"
if not string match -rq "Nitro|Predator|Helios|Triton" "$ACER_MODEL"
    echo (set_color yellow)"\u26a0 Warning: Model not explicitly supported. Proceeding anyway..."(set_color normal)
end

# 2. Dependency Installation
log "Installing system dependencies..."
set KERNEL_HEADERS "linux-headers"
if string match -q "*cachyos*" (uname -r)
    set KERNEL_HEADERS "linux-cachyos-headers"
end

sudo pacman -Syu --needed --noconfirm base-devel dkms git curl $KERNEL_HEADERS python-pip

# 3. Kernel Module (Linuwu-Sense) via DKMS
log "Setting up $MODULE_NAME via DKMS..."
set SRC_DIR "/usr/src/linuwu-sense-1.0"
sudo rm -rf $SRC_DIR
sudo git clone $REPO_DRIVER $SRC_DIR

# Determine Compiler Flags
set MAKE_FLAGS ""
if grep -q "clang" /proc/version
    log "Clang kernel detected. Using LLVM flags."
    set MAKE_FLAGS "LLVM=1 CC=clang"
end

# Create DKMS Config
sudo tee $SRC_DIR/dkms.conf > /dev/null <<EOF
PACKAGE_NAME="linuwu-sense"
PACKAGE_VERSION="1.0"
CLEAN="make clean"
MAKE[0]="make KVERSION=\$kernelver $MAKE_FLAGS"
BUILT_MODULE_NAME[0]="$MODULE_NAME"
DEST_MODULE_LOCATION[0]="/kernel/drivers/platform/x86"
AUTOINSTALL="yes"
EOF

sudo dkms add -m linuwu-sense -v 1.0
sudo dkms install -m linuwu-sense -v 1.0

# Blacklist acer_wmi
log "Blacklisting acer_wmi..."
echo "blacklist acer_wmi" | sudo tee /etc/modprobe.d/blacklist-acer-wmi.conf > /dev/null

# 4. DAMX GUI & Daemon Setup
log "Fetching latest DAMX..."
mkdir -p $INSTALL_DIR
cd $INSTALL_DIR

set LATEST_RELEASE (curl -s https://api.github.com/repos/$REPO_APP/releases/latest | python3 -c "import sys, json; print(json.load(sys.stdin)['tag_name'])")
log "Latest version found: $LATEST_RELEASE"

set DL_URL "https://github.com/$REPO_APP/releases/download/$LATEST_RELEASE/DAMX-"(string replace "v" "" $LATEST_RELEASE)".tar.xz"
curl -L $DL_URL -o damx.tar.xz
tar -xf damx.tar.xz --strip-components=1

# Install Python deps safely
pip install -r requirements.txt --break-system-packages > /dev/null 2>&1

# 5. Systemd Service Setup
log "Configuring systemd units..."
set SERVICE_FILE "$HOME/.config/systemd/user/damx-daemon.service"
mkdir -p (dirname $SERVICE_FILE)

tee $SERVICE_FILE > /dev/null <<EOF
[Unit]
Description=DAMX Daemon - Fan & RGB Manager
After=graphical-session.target

[Service]
ExecStart=$INSTALL_DIR/DAMX.py --daemon
Restart=on-failure
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now damx-daemon.service

log "Installation complete! \u2705"
log "Check service status: systemctl --user status damx-daemon"