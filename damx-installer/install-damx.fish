#!/usr/bin/env fish

# === DAMX Smart Installer: SKIP DRIVER MODE ===
# Downloads and installs DAMX GUI + Daemon without touching kernel modules

echo ">>> Installing DAMX without overwriting Linuwu-Sense driver..."

# Ensure dependencies
sudo pacman -Syu --noconfirm
sudo pacman -S --needed --noconfirm curl tar systemd unzip

# Create temp dir
set TMPDIR /tmp/damx-skipdriver
rm -rf $TMPDIR
mkdir -p $TMPDIR
cd $TMPDIR

# Download DAMX release
set DAMX_VERSION "v0.9.1"
set TAR_URL "https://github.com/PXDiv/Div-Acer-Manager-Max/releases/download/$DAMX_VERSION/DAMX-0.9.1.tar.xz"
echo ">>> Downloading DAMX $DAMX_VERSION..."
curl -L $TAR_URL -o DAMX.tar.xz

# Verify success
if not test -s DAMX.tar.xz
    echo "❌ Failed to download DAMX."
    exit 1
end

# Extract
echo ">>> Extracting..."
tar -xf DAMX.tar.xz
cd DAMX-0.9.1

# Disable driver install logic
echo ">>> Skipping driver install by overriding driver installer..."
printf '#!/bin/bash\necho "Driver install skipped. Using pre-installed Linuwu-Sense."\n' > Linuwu-Sense/install.sh
chmod +x Linuwu-Sense/install.sh

# Run main setup script (should still install daemon + GUI)
echo ">>> Running DAMX setup (driver suppressed)..."
chmod +x setup.sh
sudo ./setup.sh

# Enable DAMX Daemon
if systemctl list-unit-files | grep -q "damx-daemon.service"
    echo ">>> Enabling DAMX Daemon..."
    sudo systemctl enable --now damx-daemon.service
else
    echo "⚠ DAMX Daemon not detected. You may need to launch GUI manually."
end

echo "✅ DAMX GUI + Daemon installed (driver untouched)."
