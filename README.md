# Linuwu-DAMX Unified Installer

This repository provides a high-performance, automated deployment suite for the Linuwu-Sense kernel driver and the DAMX (Div Acer Manager Max) GUI suite. It is engineered specifically for Acer Nitro, Predator, Helios, and Triton series laptops running Arch Linux or CachyOS.

## Core Features

- **Automated DKMS Integration**: The Linuwu-Sense driver is registered via Dynamic Kernel Module Support (DKMS), ensuring the module persists and automatically rebuilds during kernel updates without manual user intervention.
- **CachyOS Optimization**: Logic includes automatic detection of the CachyOS kernel to resolve and install the appropriate LLVM/Clang headers instead of generic linux-headers.
- **System-Native Dependency Management**: Installation scripts prefer pacman-managed Python packages (pyside6, requests) over pip to maintain system integrity and avoid environment conflicts.
- **Conflict Mitigation**: Automatically handles the blacklisting of the legacy acer_wmi module to ensure the linuwu_sense driver retains exclusive control over hardware registers.
- **Universal Shell Support**: Includes native installation and uninstallation logic for both Bash and Fish shells.

## Installation Procedures

Ensure you have an active internet connection and that your system is up to date before running the installer.

### Fish Shell Users
```fish
./setup.fish
```

### Bash and Other Shell Users
```bash
./install.sh
```

## Verification and Validation

After installation, verify the state of the system using the following commands:

1.  **Driver Status**: Run `dkms status` to confirm `linuwu-sense` is listed as `installed`.
2.  **Kernel Module**: Run `lsmod | grep linuwu_sense` to ensure the module is actively loaded.
3.  **Application Daemon**: Run `systemctl --user status damx-daemon` to confirm the background manager is active.

## Uninstallation

To safely revert all system modifications, including the removal of DKMS modules, blacklists, and application data:

### Fish Shell
```fish
./uninstall.fish
```

### Bash Shell
```bash
./uninstall.sh
```

## Technical Notes

- **Secure Boot**: If Secure Boot is enabled, you must manually sign the linuwu_sense module or disable Secure Boot to allow the kernel to load the driver.
- **Hardware Support**: This suite is intended for Acer laptops that utilize the WMI interface for fan and RGB control. Installation on unsupported hardware will result in a compatibility warning.

---
*Maintained for the Acer Linux Community.*