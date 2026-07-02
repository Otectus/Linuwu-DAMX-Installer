#!/usr/bin/env bash
# Central pin registry for third-party code that is built or installed as
# root. Every git clone in modules/ must be followed by a checkout of one of
# these pins (enforced by tests/pins.bats), so an upstream compromise or a
# force-push cannot change what runs on users' machines without a reviewed
# bump here.
#
# To update a pin: resolve the new commit (git ls-remote <repo> HEAD, or a
# release tag), verify the build in a disposable Arch/CachyOS VM, then change
# the value in its own commit.
#
# Residual risk (accepted): AUR-helper paths (paru/yay -S envycontrol,
# acer-wmi-battery-dkms-git, noise-suppression-for-voice) cannot be
# commit-pinned through a helper; those follow the AUR package. The pins
# below cover every no-helper path, which is where code is built as root
# directly from upstream.
#
# shellcheck disable=SC2034  # consumed by modules/*.sh

# Linuwu-Sense DKMS driver (modules/driver.sh) — HEAD as of 2026-07-01
ARCHER_PIN_LINUWU_SENSE="73a25ec243a44ba2b1703e8d0a76fa2735062506"

# acer-wmi-battery DKMS driver (modules/battery.sh) — HEAD as of 2026-07-01
ARCHER_PIN_ACER_WMI_BATTERY="9f90d75cc9237aeed7964622d10dbdf4d2c7b518"

# noise-suppression-for-voice AUR PKGBUILD (modules/audio-enhance.sh)
# — HEAD as of 2026-07-01
ARCHER_PIN_NSV_AUR="e92e4069cead7e8367d093267b45a322e6c88edc"

# EnvyControl (modules/gpu.sh pip fallback). NOTE: envycontrol is NOT on
# PyPI (pip install envycontrol 404s), so the fallback installs straight
# from the upstream repo at a pinned release commit.
ARCHER_PIN_ENVYCONTROL_REPO="https://github.com/bayasdev/envycontrol.git"
ARCHER_PIN_ENVYCONTROL="a65724bfa25fe78408adeea6a5015647b5a826da"  # v3.5.2
