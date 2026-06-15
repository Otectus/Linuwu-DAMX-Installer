# Changelog

All notable changes to Archer Compatibility Suite are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.1.0] — 2026-06-15

Full engineering pass: correctness, security hardening, and a GUI
modernization. GUI package version bumped in lockstep: `1.0.1` → `1.1.0`.
The D-Bus method/signal contract is unchanged, so daemon and GUI stay
compatible.

### Fixed

- **Installer no longer relies on array positions.** Module conflict and
  dependency logic (`driver` ↔ `thermal`, `gui` → `driver`) is keyed by module
  ID via new `module_index`/`is_module_selected`/`set_module_selected` helpers,
  so reordering `MODULE_IDS` can't silently break it.
- **Honest install summary.** The installer tracks failed modules, reports
  `N of M installed`, folds in verification pass/total, and exits non-zero on
  real failures instead of always printing "all installed".
- **GPU module no longer leaks a broken `mkinitcpio` shim.** The no-op shim is
  explicitly restored on every exit path (success or `envycontrol` failure).
  A RETURN trap was avoided because bash RETURN traps aren't function-scoped
  and would re-fire on later modules, crashing with `_shim_path: unbound
  variable` under `set -u`.
- **GPU module is resilient to a missing/conflicting NVIDIA setup.** It now
  accepts any existing NVIDIA driver (incl. kernel-bundled `*-nvidia-open`)
  instead of forcing a conflicting `nvidia-dkms`, and fails cleanly with a
  clear message if `envycontrol` couldn't be installed (e.g. AUR offline)
  rather than running `envycontrol` that isn't on PATH.
- **Safer GRUB edits.** `mktemp` failures are caught and temp files cleaned up
  in `add/remove_grub_params`.
- **Broader Clang-kernel detection** via `CONFIG_CC_IS_CLANG` (`/proc/config.gz`,
  `/boot/config-*`) in addition to `/proc/version`.
- **Pango markup bugs** in two row titles ("Boot Animation & Sound", "Restart
  Drivers & Daemon") — unescaped `&` now rendered correctly.
- **Display "reboot required" banner is sticky** — it no longer clears on the
  next settings refresh before you actually reboot.
- **Working tree normalized to LF** (had been bulk-converted to CRLF, which
  broke `bash -n` and CI).

### Security

- **Polkit least privilege.** The broad `set-hardware` action is split into
  per-domain `set-battery` / `set-keyboard` / `set-usb` / `set-audio` actions
  (LCD/boot toggles remain under `set-hardware`). A new test asserts the
  daemon's `POLKIT_ACTIONS` map and the policy file never drift apart.
- **Default-deny D-Bus config.** `io.otectus.Archer1.conf` now allows only the
  Archer interface plus standard introspection/properties/peer, instead of any
  method.
- **Daemon input validation.** New `gui/archer_validate.py` validates every
  mutating method: JSON payloads must be objects (no more uncaught
  `json.loads`/`KeyError`), numerics are range-checked, colors must be hex.
- **Stronger systemd sandbox** for `archer-daemon.service`
  (`ProtectKernelModules`, `ProtectControlGroups`, `RestrictAddressFamilies`,
  `RestrictNamespaces`, `LockPersonality`, `SystemCallArchitectures=native`, …),
  keeping `/sys` writes and polkit working.

### Added

- **Sidebar Control Center GUI.** `Adw.NavigationSplitView` with a sidebar,
  per-page header, dashboard **hero** (model, profile, GPU mode, live temps,
  battery + limit, status badges), and a persistent **status footer**.
  Version-gated with the classic `ViewStack` layout as a fallback.
- **Capability-aware controls** — unsupported features are disabled with an
  explanation instead of hidden.
- **Confirmation dialogs** for risky actions (GPU mode switch, battery
  calibration, full driver+daemon restart).
- **Consistent setter behavior** — all pages use the `async_set`
  revert-on-failure + toast helper; new shared widgets under
  `gui/archer/widgets/` (`hero`, `status_footer`, `status`, `capability_row`,
  `confirm`).
- **Tests + CI**: `tests/test_validate.py`, `tests/test_policy_actions.py`,
  `tests/test_gui_construct.py`, plus `python-unit` and `gui-construct-smoke`
  (Xvfb) CI jobs; negative-validation cases added to the D-Bus smoke test.

## [2.0.1] — 2026-05-01

Hardening sweep triggered by [#4](https://github.com/otectus/Archer/issues/4)
("Archer GUI not updating and some other problems"). Closes that issue and a
broad set of correctness/security bugs surfaced by audit.

GUI package version bumped in lockstep: `1.0.0` → `1.0.1`.

### Fixed

- **Installer no longer requires a reboot to connect.** `modules/gui.sh` now
  reloads `dbus.service` (with `kill -HUP $(pidof dbus-daemon)` fallback) after
  copying `io.otectus.Archer1.conf`, so the new policy takes effect immediately.
- **GUI no longer freezes when the daemon is slow.** Every D-Bus call from
  `gui/archer/client.py` now passes a 5s `timeout=` (longer for `envycontrol`,
  `fwupdmgr`, restart). Without it, dbus-python defaulted to no timeout and a
  single hung sysfs read in the daemon would freeze the polling thread forever.
- **Status label now reflects reality.** The window's "Connected" label was set
  once at startup and never updated. It now flips to "Daemon Offline" or
  "Stale" with exponential-backoff reconnect (5/10/20/60s) and surfaces the
  underlying error in a toast.
- **Audio noise-suppression toggle now actually takes effect.** The daemon's
  `systemctl --user restart pipewire.service` ran inside the *root* user
  manager, never touching the user's pipewire. Replaced with an
  `AudioEnhancementChanged` D-Bus signal that the GUI handles in the user's
  own session.
- **`restart_daemon` no longer "loses" the D-Bus reply.** The synchronous
  `systemctl restart` killed the daemon before the reply flushed. Now uses
  `systemd-run --on-active=2s --no-block` so the GUI sees a clean response.
- **`get_fan_rpm` now picks the right hwmon device.** Allowlists Acer-relevant
  chipsets (`linuwu_sense`, `acer_wmi`, `nct67xx`, `it87`, `dell_smm_hwmon`)
  before falling back to "first device with `fan1_input`".
- **Setter UI controls revert on daemon failure.** Battery limit switch, USB
  charging combo, LCD override switch, boot animation switch, backlight
  timeout switch now flip back to the previous value with an explanatory
  toast when the daemon refuses (was fire-and-forget — UI lied about state).
- **Tray init failures are no longer silent.** Logged at WARNING and surfaced
  in a toast on first window show so the close-to-tray hint isn't bogus.
- **`uninstall.sh` no longer rm-rfs `/.local/...` if `$HOME` is unset under
  sudo.** Guard added.

### Changed

- **Telemetry now arrives via D-Bus signal (`TelemetryUpdated`) instead of
  polling.** The daemon emits every 2s; the GUI subscribes and watches for
  staleness. The previous polling loop spawned a new thread every 2s and
  would silently pile up zombies if any single call hung. `GetMonitoringData`
  remains for the initial settings fetch and backward compat.
- **D-Bus is now mandatory.** The Unix-socket fallback in
  `gui/archer_daemon.py` (`DaemonServer` class, ~340 LOC) was unreachable
  from the user-mode GUI anyway (socket was 0o660 root:root). Removed.
  `gui/archer/client.py` similarly drops the socket-fallback path. A failed
  D-Bus startup now logs an actionable error pointing at the policy file
  and `dbus reload`.
- **Service unit hardened.** `gui/archer-daemon.service` now uses
  `RuntimeDirectory=archer` (so systemd creates `/run/archer/` with
  0755 root:root) and `ReadWritePaths=/etc/archer` (required by
  `ProtectSystem=full`). PID file moved from `/var/run/archer-daemon.pid`
  to `/run/archer/daemon.pid`. `Requires=dbus.service` added.
- **Install manifest moved to `/var/lib/archer/install-manifest.json`**
  (root-owned, 0644). Resolves the install-as-user / uninstall-as-sudo
  `$HOME` mismatch and stops local users tampering with manifest entries
  that `uninstall.sh` later sources. Manifests at the previous user-home
  paths (and the legacy DAMX path) are migrated automatically on the next
  install or uninstall run.
- **Per-module install rollback.** `INSTALLED_FILES` / `INSTALLED_DKMS` /
  `INSTALLED_PACKAGES` are snapshotted before each `module_install` and
  restored on failure, so the saved manifest only lists modules that
  actually installed cleanly.
- **Daemon hot-path probes are cached** (5s TTL). `nvidia-smi`, `lspci`,
  and `which envycontrol` results are reused across the GUI's monitoring
  ticks so a hung NVIDIA driver no longer drives the daemon thread into
  the ground.

### Security

- **Path-traversal in `uninstall.sh` closed.** The uninstall manifest source
  loop now refuses to `source` any module name that fails the
  `^[a-z][a-z0-9_-]+$` allowlist *and* isn't in the canonical `MODULE_IDS`
  array. A tampered `~/.local/share/archer/install-manifest.json` could
  previously inject e.g. `mod="../../tmp/evil"` and gain code execution
  under `sudo` when the user ran uninstall.
- **`run_cmd` shell-meta guard.** `gui/archer_daemon.py:run_cmd` now refuses
  any command containing `;`, `&&`, `||`, `$(`, or backticks unless the
  caller passes `shell_meta_ok=True`. No present callsite is exploitable;
  the guard catches future regressions where a user-supplied value flows
  into a shell string.
- **`MODULE_IDS` is now a single source of truth** in `lib/modules.sh`,
  consumed by both `install.sh` (validating `--modules`) and `uninstall.sh`
  (validating manifest entries before `source`).

### Added

- **`tests/dbus_smoke.py` + `tests/dbus_smoke.sh`.** Headless smoke harness
  that boots `ArcherDBusService` against a private session bus with a mocked
  `HardwareManager`, asserts the required methods + signals appear in the
  introspection XML, and waits for the first `TelemetryUpdated` emit.
- **CI: `python-syntax` and `dbus-introspect-smoke` jobs.**
  `python -m py_compile` for every `gui/**/*.py`; smoke harness via
  `dbus-run-session` so CI fails loudly on signal/method regressions.
- **`.github/ISSUE_TEMPLATE/gui-not-updating.md`** with required fields:
  distro+kernel, daemon status, journal, `busctl introspect`, GUI logs.
  Would have closed #4 in one round trip.
- **README → Troubleshooting** section covering "Daemon Offline / Stale"
  and "GUI hangs forever" with the exact triage commands.
- **`is_known_module` allowlist with ~25 lines of bats tests** covering
  path-traversal, shell-metacharacter, and well-formed-but-unknown IDs.

### Removed

- **`gui/install-gui.sh`** legacy wrapper. Use `./install.sh --modules gui`.
- **`DaemonServer` class and `/var/run/archer.sock`** from the daemon.
- **Unix-socket fallback path** from `gui/archer/client.py`.

### Migration notes for upgraders from 2.0.0

- The first run of `./install.sh` after upgrading copies your existing
  `~/.local/share/archer/install-manifest.json` (and any legacy
  `~/.local/share/damx/install-manifest.json`) into `/var/lib/archer/`.
  Nothing else needed.
- If the daemon is currently running with a `/var/run/archer-daemon.pid`
  PID file, the new unit's `RuntimeDirectory=archer` will create
  `/run/archer/` on next start. Old `/var/run/archer.sock` is removed by
  the uninstall path; no manual cleanup required.
- A short `systemctl reload dbus.service` happens during the GUI module
  install. On most desktops this is invisible; you may briefly see your DE's
  panel/applets reconnect.

## [2.0.0] — 2026-04-20

Initial release with D-Bus IPC + polkit authorization, 13 installer modules,
GTK4/Adwaita control panel, install manifest, and CI/test scaffolding.
