#!/usr/bin/env bash
# Module: Audio Enhancement (Noise Suppression)
# Sets up PipeWire noise suppression via rnnoise

MODULE_NAME="Audio Enhancement (Noise Suppression)"
MODULE_ID="audio-enhance"
MODULE_DESCRIPTION="Noise suppression via PipeWire/rnnoise"

_FILTER_CONF="/etc/pipewire/filter-chain.conf.d/archer-noise-suppress.conf"

module_detect() {
    pacman -Qi pipewire &>/dev/null
}

module_check_installed() {
    [[ -f "$_FILTER_CONF" ]]
}

module_install() {
    log "Installing audio enhancement dependencies..."
    run_sudo pacman -S --needed --noconfirm pipewire wireplumber

    if has_cmd paru; then
        log "Installing noise-suppression-for-voice via paru..."
        run paru -S --needed --noconfirm noise-suppression-for-voice
    elif has_cmd yay; then
        log "Installing noise-suppression-for-voice via yay..."
        run yay -S --needed --noconfirm noise-suppression-for-voice
    else
        log "No AUR helper found. Building noise-suppression-for-voice from AUR..."
        local _nsv_dir
        if ! _nsv_dir="$(mktemp -d "${TMPDIR:-/tmp}/archer-nsv-XXXXXX")"; then
            warn "Failed to create temp build directory. Install 'noise-suppression-for-voice' manually."
        elif run git clone https://aur.archlinux.org/noise-suppression-for-voice.git "$_nsv_dir"; then
            (cd "$_nsv_dir" && makepkg -si --needed --noconfirm) || warn "makepkg failed. Install 'noise-suppression-for-voice' manually."
            rm -rf "$_nsv_dir"
        else
            warn "Failed to clone AUR package. Install 'noise-suppression-for-voice' manually."
            rm -rf "$_nsv_dir"
        fi
    fi

    log "Creating PipeWire noise suppression filter..."
    run_sudo mkdir -p "$(dirname "$_FILTER_CONF")"
    run_sudo tee "$_FILTER_CONF" > /dev/null <<'FILTER_EOF'
context.modules = [
    { name = libpipewire-module-filter-chain
        args = {
            node.description = "Archer Noise Suppression"
            media.name = "Archer Noise Suppression"
            filter.graph = {
                nodes = [
                    {
                        type = ladspa
                        name = rnnoise
                        plugin = librnnoise_ladspa
                        label = noise_suppressor_mono
                        control = { "VAD Threshold (%)" = 50.0 }
                    }
                ]
            }
            capture.props = {
                node.name = "archer_noise_capture"
                node.passive = true
                audio.rate = 48000
            }
            playback.props = {
                node.name = "archer_noise_suppressed"
                media.class = "Audio/Source"
                audio.rate = 48000
            }
        }
    }
]
FILTER_EOF

    log "Audio enhancement installed."
    log "Select 'Archer Noise Suppression' as your mic in application settings."
    log "Restart PipeWire to activate: systemctl --user restart pipewire.service"

    INSTALLED_FILES+=" $_FILTER_CONF"
    INSTALLED_PACKAGES+=" pipewire wireplumber"
}

module_uninstall() {
    run_sudo rm -f "$_FILTER_CONF"
    log "Filter config removed. Restart PipeWire to deactivate."
}

module_verify() {
    [[ -f "$_FILTER_CONF" ]] && return 0
    warn "Noise suppression config not found at $_FILTER_CONF"
    return 1
}
