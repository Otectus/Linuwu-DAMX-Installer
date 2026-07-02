# Archer — Implementation Plan (Remediation Roadmap)

Companion to `AUDIT_REPORT.md`. Fixes are grouped into phases by risk and dependency. Each item lists the files likely to change, the change risk, the tests to add **before** (to capture current behavior / red) and **after** (to lock the fix), and notes. A "Do not touch yet" section closes the doc.

**Guiding constraints (from the audit brief):** small reviewable changes; never weaken a safety check without a stronger replacement; don't broaden polkit/sudo/D-Bus scope for convenience; add tests around each change; validate anything that mutates the system in a disposable Arch/CachyOS VM, never the host.

**Prerequisite (do first):** get the test suite green and gating.
- Fix **F-TEST1** (bats `run` shadowing): the product `run()` in `lib/utils.sh` shadows bats' `run` helper, so `install.bats:86` and `:114` see an empty `$status`. Either rename the product wrapper (`run`→`arun`, mechanical, touches all modules + lib) **or** change those two tests to call the functions directly and check `$?`. Prefer the test-side fix first (smaller, no product churn) unless a rename is independently desired. Verify `bats tests/*.bats` is 67/67.
- Fix **F-TEST2**: change `.github/workflows/ci.yml` triggers to run on all branches / all PRs so subsequent phases are actually gated.
- These two unblock trustworthy CI for everything below.

---

## Phase 0 — Immediate safety & security

| Item | Files | Risk | Notes |
|---|---|---|---|
| **F-STAB1** mkinitcpio shim cleanup trap | `modules/gpu.sh` | Low-Med | Add `trap … EXIT INT TERM` restoring the shim, guarded by a flag; clear after restore. Two shim windows (install + uninstall) — ensure the trap keys on the active window and doesn't misfire. VM-verify interrupt behavior. |
| **F-SEC1** fail-closed `_authorize` | `gui/archer_dbus.py` | Low | Explicit `READ_ONLY` set; deny anything unmapped + not read-only. No behavior change for current methods. |
| **F-STAB3** `error`→`return 1` in module bodies | `modules/gui.sh` (audit other modules for stray `error` in `module_*`) | Low | Preserves per-module rollback contract. |
| **F-STAB4** dry-run leak | `modules/audio-enhance.sh` (+ scan for other unwrapped mutating calls) | Low | Wrap `makepkg`/`mktemp -d` in `run`, or short-circuit the branch under `DRY_RUN`. |
| **F-SEC2** pin DKMS/PyPI/AUR sources | `modules/driver.sh`, `modules/battery.sh`, `modules/audio-enhance.sh`, `modules/gpu.sh` | Med | Add `git checkout <SHA>` after each clone; pin `envycontrol==<ver>`; record pins centrally (README/a `pins.sh`). VM-verify the pinned commits still build. |

**Tests before:** bats interrupt-simulation for gpu shim (stub `envycontrol` to `kill -INT $$`); AST test enumerating D-Bus methods vs `READ_ONLY ∪ POLKIT_ACTIONS`; bats asserting `module_install` returns (not exits) on missing file; bats dry-run marker test for makepkg.
**Tests after:** all the above green; add a lint test that every `git clone` in `modules/` is followed by a pinned `git checkout`.

---

## Phase 1 — Functional correctness & crash prevention

| Item | Files | Risk | Notes |
|---|---|---|---|
| **F-FUNC1** `display_mode` contract + per-page load isolation | `gui/archer_daemon.py` (`get_all_settings` → store `["mode"]`), `gui/archer/widgets/hero.py`, `gui/archer/pages/display.py` (defensive `isinstance` guard), `gui/archer/window.py` (`try/except` per page in `_on_settings_loaded`) | Low-Med | This is the highest-value functional fix. Update `tests/test_gui_construct.py:58` stub to the **real dict shape** so it can't regress. |
| **F-STAB5** `-Syu`→`-S --needed` | `install.sh` | Low | Behavior change (no longer upgrades system); note in CHANGELOG. |
| **F-FUNC2** firmware row leak | `gui/archer/pages/firmware.py` | Low | Track/remove dynamic rows before re-adding. |
| **F-FUNC3** empty fan-curve rejection | `gui/archer_validate.py` | Low | Require ≥2 monotonic points. |
| **F-FUNC4** camera-enhance manifest version + dkms-remove | `modules/camera-enhance.sh` | Low | Derive real version or omit; add `dkms remove` to uninstall. |
| **F-MAINT5** narrow exception in `get_firmware_info` | `gui/archer_daemon.py` | Low | Drop the redundant broad `Exception`. |

**Tests before:** GUI regression test feeding daemon-shaped `display_mode` dict into `hero.load_settings`/`display.load_settings` (currently raises); `test_validate.py` empty/one-point fan curve (currently passes — should fail after).
**Tests after:** those green; `test_gui_construct.py` stub corrected; grep test that install deps use `-S` not `-Syu`.

---

## Phase 2 — Install/uninstall reliability & system integration

| Item | Files | Risk | Notes |
|---|---|---|---|
| **F-STAB2** incremental manifest + interrupt warning trap | `install.sh`, `lib/manifest.sh` | Med | Append each module to the manifest as it completes (so uninstall can always reverse actual state); add an INT/TERM trap that reports reached state. |
| **F-STAB7** don't disable shared services on uninstall | `uninstall.sh`, `modules/firmware.sh`, `modules/power.sh`, `lib/manifest.sh` | Med | Record at install time whether Archer enabled a shared service (fwupd, etc.); only reverse what Archer changed. Never blind-disable `fwupd`. |
| **F-STAB8** GRUB backup + literal param removal + gate PCI reset | `lib/utils.sh`, `modules/wifi.sh` | Med | `.archer-bak` before GRUB edits; replace `sed "s|$p||g"` with literal word-boundary removal; confirm before PCI remove/rescan. |
| **F-SEC3** validate/remove `SetUsbWake` | `gui/archer_daemon.py`, `gui/archer_validate.py` | Low | Add explicit validator or delete the unused method (see F-MAINT1). |
| **F-SEC5/6** file perms + systemd `UMask` | `gui/archer-daemon.service`, `gui/archer_daemon.py`, `modules/gui.sh` | Low-Med | `UMask=0027`; 0640 on settings/log. Capability/syscall filters need VM validation — can slip to Phase 4. |

**Tests before:** `lib/manifest.sh` round-trip unit test (currently none); uninstall test asserting pre-existing fwupd state preserved; utils.bats GRUB add/remove with dotted params + idempotency.
**Tests after:** all green; container/VM install→uninstall smoke asserting only Archer-owned files removed.

---

## Phase 3 — GUI / UX

| Item | Files | Risk | Notes |
|---|---|---|---|
| **F-UX1** confirmations on impactful actions | `gui/archer/pages/internals.py` (modprobe apply, daemon restart) | Low | Reuse `widgets/confirm.py`. |
| **F-UX2** surface silent launch failures | `gui/archer/pages/system.py` | Low | Toast on `FileNotFoundError`. |
| **F-UX4** typed D-Bus error handling | `gui/archer/client.py` | Low | Branch on `DBusException.get_dbus_name()` instead of string match. |
| **F-STAB6** offload long daemon calls off the GLib loop | `gui/archer_daemon.py`, `gui/archer_dbus.py` | Med-High | Threading review required; `SetDisplayMode`/firmware/nvidia-smi. Do after Phase 0–2 stabilize. |
| **F-UX3 / F-MAINT1** MUX + dead-code decision | `gui/archer_daemon.py`, `gui/archer/pages/display.py`, `gui/archer/client.py`, `gui/archer/widgets/capability_row.py` | Low | Needs owner intent (see Do-not-touch). Prune or wire up. |
| **F-UX6** desktop categories hint | `gui/io.github.archer.desktop` | Low | Single main category. |

**Tests before:** GUI test asserting confirm dialog appears for modprobe/daemon-restart; timing test that telemetry continues during a stubbed-slow method (red before F-STAB6).
**Tests after:** those green; manual GUI QA per report §7.4.

---

## Phase 4 — Tests, CI, docs, release polish

| Item | Files | Risk | Notes |
|---|---|---|---|
| **F-TEST3** install/uninstall/manifest/polkit tests | `tests/` (new), `.github/workflows/ci.yml` | Med | Manifest round-trip unit; container install/uninstall smoke job; a real-polkit test (or document why stubbed). |
| **F-TEST4** ruff/bandit/pip-audit CI jobs + fix real lint | `.github/workflows/ci.yml`, `tests/test_gui_construct.py` (drop unused `Gtk`) | Low | Curated ignore list (E402 for `gi.require_version`; document the `shell=True` bandit finding as accepted with rationale). |
| **F-DOC1 / F-MAINT2 / F-PKG4** centralize version + tag releases | new `VERSION` file, `lib/utils.sh`, `gui/archer_daemon.py`, `gui/archer/__init__.py`, `gui/archer/pages/system.py`, installer banners | Med | Single source of truth; `git tag` 2.1.0 and wire CHANGELOG compare links. |
| **F-DOC2/3/4/5** doc sync | `CONTRIBUTING.md`, `README.md` | Low | Fix flake8 flags, CI job list, `bats` package name; note `--dry-run` guarantee after F-STAB4; align version banners; consider in-repo screenshot + named LICENSE holder. |
| **F-PKG2/3** launcher + file modes | `gui/io.github.archer.desktop`, repo file modes | Low | `Exec=archer-gui`; `chmod 0644` non-scripts. |
| **F-PKG1** packaging format | new `PKGBUILD` | High | Larger effort; evaluate replacing custom install/manifest with pacman-tracked packaging. Decide with owner. |
| **F-COMPAT1** bootloader-coverage docs | `README.md`, `lib/utils.sh` | Low | Document systemd-boot/Limine kernel-param limitations. |

**Tests after:** green ruff/bandit/pip-audit jobs; manifest + install/uninstall smoke in CI; version-consistency test asserting all literals match `VERSION`.

---

## Suggested implementation order

1. Prerequisite: F-TEST1 (green bats) + F-TEST2 (CI on branches).
2. Phase 0 (all five) — merge as one reviewable safety PR each or a small batch.
3. Phase 1 — F-FUNC1 first (user-visible crash), then the rest.
4. Phase 2 — manifest work is the backbone; do F-STAB2 before F-STAB7 (shared-service tracking depends on richer manifest).
5. Phase 3 — UX quick wins first; defer F-STAB6 threading until the above are stable.
6. Phase 4 — CI/docs/version last, then tag a release.

## "Do not touch yet" (need owner intent before changing)

- **F-STAB9 / `_maybe_autoforce_v4` self-restart in `__init__`** — a deliberate self-heal for DMI-unmatched gaming Acers. Changing where/how it restarts risks breaking fan/RGB on exactly the models it targets. Confirm intended behavior and get a test model before refactoring.
- **F-UX3 MUX feature** (`detect_mux`) — decide whether MUX switching is a planned feature (wire it up) or abandoned (remove the UI group). Don't guess.
- **F-STAB6 daemon threading** — architectural; correct but invasive. Only after Phase 0–2 land and with a threading-model review.
- **F-PKG1 PKGBUILD** — would replace much of the install/uninstall/manifest layer; a strategic decision, not a bug fix.
- **EnvyControl interaction semantics** (the reason the shim exists) — the shim workaround is a symptom of EnvyControl's internal `mkinitcpio -P`; before redesigning it, confirm the CachyOS/Limine hang still reproduces on current EnvyControl versions.
- **`NoNewPrivileges=false` / `ProtectKernelModules` bypass** — documented and load-bearing for polkit + modprobe-via-systemd-run. Do not "harden" these away without verifying polkit auth and driver reloads still work.
