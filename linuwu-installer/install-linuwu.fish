#!/usr/bin/env fish
# === Model Compatibility Check ===
set ACER_MODEL (cat /sys/devices/virtual/dmi/id/product_name)
echo ">>> Detected Acer model: $ACER_MODEL"

# List of supported substrings (can be expanded)
set SUPPORTED_MODELS Nitro Predator Helios Triton

set IS_SUPPORTED 0
# === Detect Kernel Compiler (GCC vs Clang) ===
set KVER (uname -r)
set BUILD_DIR /usr/lib/modules/$KVER/build
set CC_CLANG 0
set MAKE_FLAGS

# Check for Clang compiler tag in the kernel build version
if test -f "$BUILD_DIR/include/config/cc/version.text"
    if grep -iq "clang" $BUILD_DIR/include/config/cc/version.text
        set CC_CLANG 1
        set MAKE_FLAGS LLVM=1 CC=clang
    end
else if test -f /proc/version
    if grep -iq "clang" /proc/version
        set CC_CLANG 1
        set MAKE_FLAGS LLVM=1 CC=clang
    end
end

if test $CC_CLANG -eq 1
    echo ">>> Kernel was built with Clang. Using LLVM=1 CC=clang..."
else
    echo ">>> Kernel appears to use GCC. Using standard make..."
end
for model in $SUPPORTED_MODELS
    if string match -q "*$model*" "$ACER_MODEL"
        set IS_SUPPORTED 1
        break
    end
end

if test $IS_SUPPORTED -eq 0
    echo "❌ This Acer model ($ACER_MODEL) is not officially supported by Linuwu-Sense."
    echo "    Please check the GitHub repo to confirm compatibility:"
    echo "    https://github.com/0x7375646F/Linuwu-Sense"
    exit 1
end

echo ">>> Installing dependencies..."
sudo pacman -Syu --noconfirm
sudo pacman -S --needed --noconfirm base-devel linux-headers clang llvm lld git

set LINUX_MODULE_DIR ~/src/Linuwu-Sense
if not test -d $LINUX_MODULE_DIR
    echo ">>> Cloning Linuwu-Sense..."
    mkdir -p ~/src
    cd ~/src
    git clone https://github.com/0x7375646F/Linuwu-Sense.git
else
    echo ">>> Repository already exists. Pulling latest changes..."
    cd $LINUX_MODULE_DIR
    git pull
end

cd $LINUX_MODULE_DIR
echo ">>> Building Linuwu-Sense kernel module..."
sudo make clean
sudo make $MAKE_FLAGS install

echo ">>> Loading Linuwu-Sense module..."
sudo modprobe -r linuwu_sense >/dev/null 2>&1
if sudo modprobe linuwu_sense
    echo -n ">>> Verifying module install... "
    if lsmod | grep -q linuwu_sense
        echo "OK"
    else
        echo "FAILED - module not loaded"
    end
else
    echo "❌ Failed to load linuwu_sense. Check dmesg for details."
end

echo ">>> Blacklisting acer_wmi to prevent conflicts..."
echo "blacklist acer_wmi" | sudo tee /etc/modprobe.d/blacklist-acer-wmi.conf >/dev/null

echo ">>> Enabling module to load at boot..."
echo "linuwu_sense" | sudo tee /etc/modules-load.d/linuwu_sense.conf >/dev/null

echo ">>> Rebuilding initramfs..."
sudo mkinitcpio -P

set ALIAS_PATH ~/.config/fish/functions/linuwu_rebuild.fish
echo ">>> Creating 'linuwu_rebuild' function..."
mkdir -p ~/.config/fish/functions
echo "function linuwu_rebuild" > $ALIAS_PATH
echo "    set MODULE_DIR \"$LINUX_MODULE_DIR\"" >> $ALIAS_PATH
echo "    if not test -d \$MODULE_DIR" >> $ALIAS_PATH
echo "        echo \"❌ Linuwu-Sense source directory not found at \$MODULE_DIR\"" >> $ALIAS_PATH
echo "        return 1" >> $ALIAS_PATH
echo "    end" >> $ALIAS_PATH
echo "" >> $ALIAS_PATH
echo "    set KVER (uname -r)" >> $ALIAS_PATH
echo "    set BUILD_DIR /usr/lib/modules/\$KVER/build" >> $ALIAS_PATH
echo "    set MAKE_FLAGS" >> $ALIAS_PATH
echo "    if test -f \"\$BUILD_DIR/include/config/cc/version.text\"" >> $ALIAS_PATH
echo "        if grep -iq \"clang\" \"\$BUILD_DIR/include/config/cc/version.text\"" >> $ALIAS_PATH
echo "            set MAKE_FLAGS LLVM=1 CC=clang" >> $ALIAS_PATH
echo "        end" >> $ALIAS_PATH
echo "    else if test -f /proc/version" >> $ALIAS_PATH
echo "        if grep -iq \"clang\" /proc/version" >> $ALIAS_PATH
echo "            set MAKE_FLAGS LLVM=1 CC=clang" >> $ALIAS_PATH
echo "        end" >> $ALIAS_PATH
echo "    end" >> $ALIAS_PATH
echo "" >> $ALIAS_PATH
echo "    cd \$MODULE_DIR" >> $ALIAS_PATH
echo "    sudo make clean" >> $ALIAS_PATH
echo "    if test (count \$MAKE_FLAGS) -gt 0" >> $ALIAS_PATH
echo "        sudo make \$MAKE_FLAGS install" >> $ALIAS_PATH
echo "    else" >> $ALIAS_PATH
echo "        sudo make install" >> $ALIAS_PATH
echo "    end" >> $ALIAS_PATH
echo "end" >> $ALIAS_PATH

echo ""
echo "✅ Linuwu-Sense installation complete!"
echo "📌 REBOOT NOW to finalize changes: run 'reboot'"
echo "🔁 After kernel updates, re-run: linuwu_rebuild"
