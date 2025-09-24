# Linuwu + DAMX Installer

This repository contains a complete installation suite for:

- **Linuwu-Sense**: A kernel module for enhanced Acer fan/RGB control.
- **DAMX (Div Acer Manager Max)**: A GUI and background daemon to control Acer laptop features.

## Features

- Fish shell compatible
- Auto-detects Clang/GCC
- Systemd service integration
- Full daemonized support for fan/RGB settings
- Designed for **CachyOS** (may work on other Arch-based distros)

## Installation

```bash
# Clone the repo and run the installers
cd damx-installer
fish install-damx.fish

cd ../linuwu-installer
fish install-linuwu.fish
fish install-linuwu-rebuild.fish
```

## Auto-Rebuild After Kernel Update

The `linuwu-rebuild.service` ensures your kernel module is rebuilt after each reboot or kernel upgrade.

## License

MIT License. Provided as-is with no warranty.

## Compatibility

Supports all Acer devices listed as compatible with Linuwu and DAMX.
# Linuwu-DAMX-Installer
