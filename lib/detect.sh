#!/usr/bin/env bash
# Hardware detection and recommendation engine (Bash)

# --- DMI Information ---
ACER_PRODUCT_NAME=""
ACER_BOARD_NAME=""
ACER_BIOS_VERSION=""
ACER_SYS_VENDOR=""
MODEL_FAMILY="unknown"

# --- GPU ---
HAS_NVIDIA=0
HAS_AMD_DGPU=0
HAS_INTEL_IGPU=0
HAS_AMD_IGPU=0
NVIDIA_MODEL=""

# --- WiFi ---
WIFI_DEVICE=""
WIFI_CHIPSET="unknown"

# --- Audio ---
AUDIO_CODEC=""
SOF_ACTIVE=0
CPU_VENDOR=""

# --- Touchpad ---
HAS_I2C_TOUCHPAD=0
TOUCHPAD_ERRORS=0

# --- Battery ---
HAS_BATTERY=0
BATTERY_WMI_LOADED=0

# --- Kernel ---
KERNEL_VERSION=""
KERNEL_MAJOR=0
KERNEL_MINOR=0
SUPPORTS_THERMAL_PROFILES=0

# --- Distro ---
DISTRO_ID=""
DISTRO_NAME=""
DISTRO_FAMILY="unknown"
AUR_HELPER=""

# --- CachyOS / Clang ---
IS_CACHYOS=0
IS_CLANG_KERNEL=0
CLANG_BUILD_FLAGS=""
KERNEL_HEADERS="linux-headers"

# --- Recommendations ---
RECOMMENDED_MODULES=()
OPTIONAL_MODULES=()

detect_dmi() {
    ACER_PRODUCT_NAME=$(cat /sys/devices/virtual/dmi/id/product_name 2>/dev/null || echo "Unknown")
    ACER_BOARD_NAME=$(cat /sys/devices/virtual/dmi/id/board_name 2>/dev/null || echo "Unknown")
    ACER_BIOS_VERSION=$(cat /sys/devices/virtual/dmi/id/bios_version 2>/dev/null || echo "Unknown")
    ACER_SYS_VENDOR=$(cat /sys/devices/virtual/dmi/id/sys_vendor 2>/dev/null || echo "Unknown")
}

detect_model_family() {
    case "$ACER_PRODUCT_NAME" in
        *Nitro*)      MODEL_FAMILY="nitro" ;;
        *Predator*)   MODEL_FAMILY="predator" ;;
        *Helios*)     MODEL_FAMILY="helios" ;;
        *Triton*)     MODEL_FAMILY="triton" ;;
        *Swift*)      MODEL_FAMILY="swift" ;;
        *Aspire*)     MODEL_FAMILY="aspire" ;;
        *Spin*)       MODEL_FAMILY="spin" ;;
        *Enduro*)     MODEL_FAMILY="enduro" ;;
        *TravelMate*) MODEL_FAMILY="travelmate" ;;
        *)            MODEL_FAMILY="unknown" ;;
    esac
}

detect_gpu() {
    local lspci_out
    lspci_out="${_CACHED_LSPCI:-$(lspci 2>/dev/null || echo "")}"

    if echo "$lspci_out" | grep -qi "nvidia"; then
        HAS_NVIDIA=1
        NVIDIA_MODEL=$(echo "$lspci_out" | grep -i "nvidia" | grep -iE "vga|3d" | head -1 | sed 's/.*: //')
    fi
    if echo "$lspci_out" | grep -qiE "AMD.*(Navi|RDNA|Radeon RX)"; then
        HAS_AMD_DGPU=1
    fi
    if echo "$lspci_out" | grep -qiE "Intel.*(Graphics|UHD|Iris)"; then
        HAS_INTEL_IGPU=1
    fi
    if echo "$lspci_out" | grep -qiE "AMD.*(Renoir|Cezanne|Barcelo|Phoenix|Raphael|Rembrandt|Lucienne|Mendocino)"; then
        HAS_AMD_IGPU=1
    fi
    # Fallback: detect AMD iGPU by VGA class if not caught above
    if [[ "$HAS_AMD_IGPU" -eq 0 ]] && echo "$lspci_out" | grep -qiE "AMD.*VGA.*Radeon"; then
        HAS_AMD_IGPU=1
    fi
}

detect_wifi() {
    local lspci_out="${_CACHED_LSPCI:-$(lspci 2>/dev/null || echo "")}"
    WIFI_DEVICE=$(echo "$lspci_out" | grep -iE "network|wireless" | head -1 || echo "")

    case "$WIFI_DEVICE" in
        *MT7921*|*MT7902*|*MT7925*|*MT7922*|*MediaTek*)
            WIFI_CHIPSET="mediatek" ;;
        *AX200*|*AX201*|*AX210*|*AX211*|*BE200*|*Intel*Wi-Fi*|*Wireless*8265*)
            WIFI_CHIPSET="intel" ;;
        *RTL*|*Realtek*)
            WIFI_CHIPSET="realtek" ;;
        *QCA*|*Qualcomm*|*Atheros*)
            WIFI_CHIPSET="qualcomm" ;;
        *)
            WIFI_CHIPSET="unknown" ;;
    esac
}

detect_audio() {
    AUDIO_CODEC=""
    if [[ -d /proc/asound ]]; then
        AUDIO_CODEC=$(cat /proc/asound/card*/codec* 2>/dev/null | grep "Codec:" | head -1 | sed 's/.*Codec: //' || echo "")
    fi
    SOF_ACTIVE=0
    local dmesg_out="${_CACHED_DMESG:-$(dmesg 2>/dev/null || echo "")}"
    if echo "$dmesg_out" | grep -qi "sof.*firmware\|sof-audio"; then
        SOF_ACTIVE=1
    fi
    CPU_VENDOR=$(grep -m1 "vendor_id" /proc/cpuinfo 2>/dev/null | awk '{print $3}' || echo "")
}

detect_touchpad() {
    HAS_I2C_TOUCHPAD=0
    TOUCHPAD_ERRORS=0

    local dmesg_out="${_CACHED_DMESG:-$(dmesg 2>/dev/null || echo "")}"
    if echo "$dmesg_out" | grep -qi "i2c_hid_acpi.*ELAN\|i2c_hid_acpi.*SYN\|i2c_hid_acpi.*MSFT\|i2c.*hid.*touchpad"; then
        HAS_I2C_TOUCHPAD=1
    fi
    if echo "$dmesg_out" | grep -qi "i2c_hid_acpi.*failed\|i2c_hid_acpi.*error\|i2c_hid.*timeout\|i2c_hid.*weird size"; then
        TOUCHPAD_ERRORS=1
    fi
}

detect_battery() {
    HAS_BATTERY=0
    if [[ -d /sys/class/power_supply/BAT0 ]] || [[ -d /sys/class/power_supply/BAT1 ]]; then
        HAS_BATTERY=1
    fi
    BATTERY_WMI_LOADED=0
    if lsmod 2>/dev/null | grep -q "acer_wmi_battery"; then
        BATTERY_WMI_LOADED=1
    fi
}

detect_kernel() {
    KERNEL_VERSION=$(uname -r)
    KERNEL_MAJOR=$(echo "$KERNEL_VERSION" | cut -d. -f1)
    KERNEL_MINOR=$(echo "$KERNEL_VERSION" | cut -d. -f2)
    debug "Kernel: $KERNEL_VERSION (major=$KERNEL_MAJOR, minor=$KERNEL_MINOR)"
    SUPPORTS_THERMAL_PROFILES=0
    if [[ "$KERNEL_MAJOR" -gt 6 ]] || { [[ "$KERNEL_MAJOR" -eq 6 ]] && [[ "$KERNEL_MINOR" -ge 8 ]]; }; then
        SUPPORTS_THERMAL_PROFILES=1
    fi

    IS_CACHYOS=0
    KERNEL_HEADERS="linux-headers"
    if [[ "$KERNEL_VERSION" == *"cachyos"* ]]; then
        IS_CACHYOS=1
        # Dynamically detect the correct headers package for the installed kernel
        local kernel_pkg
        kernel_pkg=$(pacman -Qoq "/usr/lib/modules/${KERNEL_VERSION}/vmlinuz" 2>/dev/null || echo "")
        if [[ -n "$kernel_pkg" ]]; then
            KERNEL_HEADERS="${kernel_pkg}-headers"
            debug "CachyOS kernel package detected: $kernel_pkg -> headers: $KERNEL_HEADERS"
        else
            # Running kernel may not match installed packages (reboot pending)
            # Try to find the right CachyOS kernel package
            kernel_pkg=$(pacman -Q 2>/dev/null | grep -oP 'linux-cachyos\S*(?=\s)' | grep -v headers | head -1)
            if [[ -n "$kernel_pkg" ]]; then
                KERNEL_HEADERS="${kernel_pkg}-headers"
                debug "CachyOS headers resolved via pacman -Q fallback: $KERNEL_HEADERS"
            else
                KERNEL_HEADERS="linux-cachyos-headers"
                warn "Could not detect exact CachyOS kernel headers package."
                warn "Defaulting to '$KERNEL_HEADERS'. If DKMS builds fail, install the correct headers manually:"
                warn "  pacman -Ss linux-cachyos.*headers"
            fi
        fi
    else
        # For non-CachyOS: try dynamic detection too
        local kernel_pkg
        kernel_pkg=$(pacman -Qoq "/usr/lib/modules/${KERNEL_VERSION}/vmlinuz" 2>/dev/null || echo "")
        if [[ -n "$kernel_pkg" ]]; then
            KERNEL_HEADERS="${kernel_pkg}-headers"
            debug "Kernel headers resolved: $KERNEL_HEADERS"
        fi
    fi

    # Detect Clang-built kernel (CachyOS and other distros may build with Clang/LLVM).
    # /proc/version is the fast path but not always reliable, so also consult the
    # kernel build config (CONFIG_CC_IS_CLANG) via /proc/config.gz or /boot/config-*.
    IS_CLANG_KERNEL=0
    CLANG_BUILD_FLAGS=""
    if grep -q "clang" /proc/version 2>/dev/null; then
        IS_CLANG_KERNEL=1
    elif [[ -r /proc/config.gz ]] && command -v gzip >/dev/null 2>&1 \
        && gzip -dc /proc/config.gz 2>/dev/null | grep -q "^CONFIG_CC_IS_CLANG=y"; then
        IS_CLANG_KERNEL=1
    elif [[ -r "/boot/config-${KERNEL_VERSION}" ]] \
        && grep -q "^CONFIG_CC_IS_CLANG=y" "/boot/config-${KERNEL_VERSION}" 2>/dev/null; then
        IS_CLANG_KERNEL=1
    fi
    if [[ "$IS_CLANG_KERNEL" -eq 1 ]]; then
        CLANG_BUILD_FLAGS="LLVM=1 CC=clang"
    fi
}

detect_distro() {
    DISTRO_ID=""
    DISTRO_NAME=""
    if [[ -f /etc/os-release ]]; then
        DISTRO_ID=$(grep "^ID=" /etc/os-release | cut -d= -f2 | tr -d '"')
        DISTRO_NAME=$(grep "^NAME=" /etc/os-release | cut -d= -f2 | tr -d '"')
    fi

    case "$DISTRO_ID" in
        arch)        DISTRO_FAMILY="arch" ;;
        cachyos)     DISTRO_FAMILY="arch" ;;
        endeavouros) DISTRO_FAMILY="arch" ;;
        manjaro)     DISTRO_FAMILY="arch" ;;
        garuda)      DISTRO_FAMILY="arch" ;;
        artix)       DISTRO_FAMILY="arch" ;;
        *)           DISTRO_FAMILY="unknown" ;;
    esac

    AUR_HELPER=""
    if command -v paru &>/dev/null; then
        AUR_HELPER="paru"
    elif command -v yay &>/dev/null; then
        AUR_HELPER="yay"
    fi
}

# Run all detection functions
detect_all() {
    # Cache expensive command outputs for reuse across detection functions
    _CACHED_DMESG=$(dmesg 2>/dev/null || echo "")
    _CACHED_LSPCI=$(lspci 2>/dev/null || echo "")

    detect_dmi
    detect_model_family
    debug "Model family: $MODEL_FAMILY ($ACER_PRODUCT_NAME)"
    detect_gpu
    debug "GPU: NVIDIA=$HAS_NVIDIA Intel_iGPU=$HAS_INTEL_IGPU AMD_iGPU=$HAS_AMD_IGPU AMD_dGPU=$HAS_AMD_DGPU"
    detect_wifi
    debug "WiFi chipset: $WIFI_CHIPSET"
    detect_audio
    detect_touchpad
    detect_battery
    debug "Battery: present=$HAS_BATTERY"
    detect_kernel
    detect_distro
    debug "Distro: $DISTRO_NAME ($DISTRO_FAMILY) AUR=$AUR_HELPER"
}

# Print a summary of detected hardware
print_hw_summary() {
    local gpu_info=""
    if [[ "$HAS_NVIDIA" -eq 1 ]]; then
        gpu_info="$NVIDIA_MODEL"
    fi
    if [[ "$HAS_INTEL_IGPU" -eq 1 ]]; then
        [[ -n "$gpu_info" ]] && gpu_info="$gpu_info + "
        gpu_info="${gpu_info}Intel iGPU"
    fi
    if [[ "$HAS_AMD_IGPU" -eq 1 ]]; then
        [[ -n "$gpu_info" ]] && gpu_info="$gpu_info + "
        gpu_info="${gpu_info}AMD iGPU"
    fi
    if [[ "$HAS_AMD_DGPU" -eq 1 ]]; then
        [[ -n "$gpu_info" ]] && gpu_info="$gpu_info + "
        gpu_info="${gpu_info}AMD dGPU"
    fi
    [[ -z "$gpu_info" ]] && gpu_info="Unknown"

    local wifi_info="$WIFI_CHIPSET"
    [[ -n "$WIFI_DEVICE" ]] && wifi_info="$WIFI_DEVICE"

    local kernel_extra=""
    if [[ "$IS_CLANG_KERNEL" -eq 1 ]]; then
        kernel_extra=" [Clang]"
    fi

    echo -e "${_BOLD}Detected:${_RESET} $ACER_PRODUCT_NAME ($ACER_SYS_VENDOR)"
    echo -e "${_BOLD}Kernel:${_RESET}   ${KERNEL_VERSION}${kernel_extra} | ${_BOLD}GPU:${_RESET} $gpu_info"
    echo -e "${_BOLD}WiFi:${_RESET}     $wifi_info"
    echo -e "${_BOLD}Battery:${_RESET}  $([[ "$HAS_BATTERY" -eq 1 ]] && echo "Present" || echo "Not detected")"
    echo -e "${_BOLD}Distro:${_RESET}   ${DISTRO_NAME:-Unknown} ($DISTRO_FAMILY)$([[ -n "$AUR_HELPER" ]] && echo " | AUR: $AUR_HELPER")"
}

# Build recommended and optional module lists based on hardware
build_recommendations() {
    RECOMMENDED_MODULES=()
    OPTIONAL_MODULES=()

    # Driver (Linuwu-Sense): recommended for gaming models
    case "$MODEL_FAMILY" in
        nitro|predator|helios|triton)
            RECOMMENDED_MODULES+=("driver")
            ;;
        *)
            OPTIONAL_MODULES+=("driver")
            ;;
    esac

    # Battery: recommended if battery present
    if [[ "$HAS_BATTERY" -eq 1 ]]; then
        RECOMMENDED_MODULES+=("battery")
    fi

    # GPU: recommended if hybrid graphics (NVIDIA + integrated)
    if [[ "$HAS_NVIDIA" -eq 1 ]] && { [[ "$HAS_INTEL_IGPU" -eq 1 ]] || [[ "$HAS_AMD_IGPU" -eq 1 ]]; }; then
        RECOMMENDED_MODULES+=("gpu")
    elif [[ "$HAS_NVIDIA" -eq 1 ]]; then
        OPTIONAL_MODULES+=("gpu")
    fi

    # Touchpad: recommended if errors detected, optional if I2C present
    if [[ "$TOUCHPAD_ERRORS" -eq 1 ]]; then
        RECOMMENDED_MODULES+=("touchpad")
    elif [[ "$HAS_I2C_TOUCHPAD" -eq 1 ]]; then
        OPTIONAL_MODULES+=("touchpad")
    else
        OPTIONAL_MODULES+=("touchpad")
    fi

    # Audio: always optional (user knows if they have issues)
    OPTIONAL_MODULES+=("audio")

    # WiFi: recommended for MediaTek, optional otherwise
    if [[ "$WIFI_CHIPSET" = "mediatek" ]]; then
        RECOMMENDED_MODULES+=("wifi")
    else
        OPTIONAL_MODULES+=("wifi")
    fi

    # Power: always optional
    OPTIONAL_MODULES+=("power")

    # Thermal: recommended for gaming models on 6.8+
    if [[ "$SUPPORTS_THERMAL_PROFILES" -eq 1 ]]; then
        case "$MODEL_FAMILY" in
            nitro|predator|helios|triton)
                OPTIONAL_MODULES+=("thermal")
                ;;
        esac
    fi

    # GUI: recommended on gaming models with display server, optional otherwise
    if [[ -n "${DISPLAY:-}" ]] || [[ -n "${WAYLAND_DISPLAY:-}" ]]; then
        case "$MODEL_FAMILY" in
            nitro|predator|helios|triton)
                RECOMMENDED_MODULES+=("gui")
                ;;
            *)
                OPTIONAL_MODULES+=("gui")
                ;;
        esac
    fi

    # Game Mode: optional for gaming models
    case "$MODEL_FAMILY" in
        nitro|predator|helios|triton)
            OPTIONAL_MODULES+=("gamemode")
            ;;
    esac

    # Audio Enhancement: always optional
    OPTIONAL_MODULES+=("audio-enhance")

    # Camera Enhancement: always optional
    OPTIONAL_MODULES+=("camera-enhance")

    # Firmware Advisor: always optional
    OPTIONAL_MODULES+=("firmware")
}
