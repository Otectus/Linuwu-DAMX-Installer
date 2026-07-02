# Archer Compatibility Suite — Full Audit Report

**Audit date:** 2026-07-01
**Target:** working tree of branch `fix/issue-4-hardening-sweep` (uncommitted changes included), commit base `4eeb845`.
**Scope:** installer/module shell layer, root D-Bus daemon, GTK4/libadwaita GUI, packaging, tests, CI, docs.
**Codebase size:** ~8,940 LOC (bash + Python).
**Method:** static review + isolated dynamic testing (shellcheck, `bash -n`, ruff, bandit, pip-audit, bats, pytest-style unit runs, desktop-file-validate, systemd-analyze verify, Arch container dry-run + GUI construct smoke). No changes were made to Archer source; no installer/uninstaller was run on the host.

---

## 1. Executive summary

Archer is a **modular compatibility suite for Acer laptops on Arch Linux** (and Arch derivatives: CachyOS, EndeavourOS, Manjaro, Garuda). It ships a bash installer with 13 feature modules, a root-privileged D-Bus system daemon (`io.otectus.Archer1`) authorized by polkit, and a GTK4 control panel. This is privileged, system-mutating software touching DKMS drivers, initramfs, GRUB, sysfs, modprobe, TLP/power, audio, Wi-Fi, thermal, firmware, and desktop integration.

**Overall posture: better than typical for this class of tool.** The current branch is a hardening sweep, and it shows: the D-Bus surface has a real input-validation module, the systemd unit carries substantial sandboxing, module names are allowlist-gated before sourcing, the manifest is written root-owned to resist tampering, temp files use `mktemp`, and there is a genuine test suite + 8-job CI. Static analysis is clean: **shellcheck 0 findings, `bash -n` clean, pip-audit found no vulnerable dependencies, bats 65/67 passing, Python validator/policy unit tests passing, GUI construct smoke passing for all 10 pages.**

The remaining risk concentrates in a few places:

- **Stability (highest concern):** a temporary no-op `mkinitcpio` shim placed in `/usr/local/bin` during GPU configuration, with **no trap/EXIT cleanup anywhere in the codebase**. An interrupt (Ctrl-C, SIGTERM, power loss, SSH drop) between shim creation and restore leaves a system-wide `mkinitcpio` that silently does nothing — every future initramfs rebuild (including the automatic one after the next kernel update) produces no output and the machine can become **unbootable**, with no error to explain why.
- **Correctness:** `display_mode` is returned by the daemon as a **dict** but consumed as a **string** in two GUI widgets. On any machine with EnvyControl installed this raises `TypeError` during `load_settings`, and because the page-load loop has no per-page error isolation, it **aborts loading of every page**.
- **Security:** `_authorize()` **fail-opens** — any D-Bus method not present in the `POLKIT_ACTIONS` map is treated as unauthenticated-OK. Correct for today's read-only methods, but a single future mutating method added without a map entry becomes an unauthenticated root primitive. Separately, all DKMS drivers are built from **unpinned upstream git clones** executed as root.
- **Install robustness:** no rollback trap; `gui.sh` calls `error` (which `exit`s the whole installer) instead of `return 1`, defeating the per-module rollback path; the installer performs a full `pacman -Syu` system upgrade as a side effect.

None of these are being actively exploited and none are remotely triggerable by default (the D-Bus bus policy + polkit gate mutating methods for local callers only). They are correctness and safety hardening items, prioritized in `IMPLEMENTATION_PLAN.md`.

---

## 2. Architecture overview

### 2.1 Entry points

| Entry point | Runs as | Purpose |
|---|---|---|
| `install.sh` | user + `sudo` per-command | Detect hardware, select modules, install |
| `uninstall.sh` | user + `sudo` per-command | Manifest-based (or legacy) removal |
| `modules/*.sh` | sourced by install/uninstall | 13 feature modules (`module_detect/install/uninstall/verify`) |
| `gui/archer_daemon.py` | **root** (systemd `archer-daemon.service`) | Hardware control backend; owns D-Bus name |
| `gui/archer_gui.py` → `archer/application.py` | unprivileged user | GTK4 control panel |
| `/usr/local/bin/archer-gui` | user | Launcher installed by `gui.sh` |

### 2.2 Install flow (`install.sh:306-470`)

`migrate_legacy_manifest` → `detect_all` + `build_recommendations` → vendor/distro gate (`confirm` on non-Arch) → module selection (explicit `--modules`, `--all`, or interactive menu) → `check_conflicts` (driver⇄thermal) → plan display + `confirm` → `install_shared_deps` (**`pacman -Syu` full upgrade** + base-devel/dkms/headers) → `run_selected_modules` (source each module, `module_install`, snapshot/rollback manifest accumulators on failure) → `verify_modules` → write manifest to `/var/lib/archer/install-manifest.json` (root-owned 0644) → summary. Exit 1 if any module failed.

### 2.3 Uninstall flow (`uninstall.sh`)

`set -uo pipefail` (no `-e`, intentional). **Manifest path** (safe): reads module list, gates each name through `is_known_module` before sourcing + `module_uninstall`. **Legacy path** (no manifest): blindly removes a hardcoded set of components regardless of what Archer installed — including disabling the **shared** `fwupd.service` (`uninstall.sh:144`) and removing third-party DKMS trees. `$HOME` rm is guarded (`uninstall.sh:119`).

### 2.4 GUI ↔ daemon trust boundary

```
[unprivileged GUI / any local user]
        │  system D-Bus  (io.otectus.Archer1 @ /io/otectus/Archer1)
        │  bus policy (io.otectus.Archer1.conf): only root may own; default-deny
        │  narrowed to the Archer interface
        ▼
[root daemon]  ── per-mutating-method polkit check (auth_admin) ──► [sysfs / modprobe / envycontrol / fwupd]
        │
        └── input validation (archer_validate.py) on parameterized methods
```

- **Transport:** system bus only (the old Unix-socket fallback was removed).
- **AuthN/AuthZ:** D-Bus bus policy limits reachable interfaces; polkit (`io.otectus.Archer1.policy`, 10 actions, `auth_admin`/`auth_admin_keep`) gates mutating methods **inside** the daemon (`_check_polkit`, `archer_dbus.py:50-93`). Read-only methods intentionally bypass polkit.
- **Shell chokepoint:** all daemon shell execution funnels through `run_cmd()` (`archer_daemon.py:80-101`), which uses `subprocess.run(shell=True)` but refuses dynamic strings containing shell metacharacters unless `shell_meta_ok=True` is explicitly set.
- **Daemon hardening:** `os.geteuid()!=0` guard; systemd unit sets `ProtectSystem=full`, `ProtectHome=read-only`, `PrivateTmp`, `ProtectKernelModules`, `RestrictAddressFamilies=AF_UNIX AF_NETLINK`, `LockPersonality`, and more (§ Security F-S6).

### 2.5 Privileged-operation register

| Operation | Who triggers | Input reaches it | Validated? | Allowlisted? | Arbitrary-cmd risk | Safe failure? |
|---|---|---|---|---|---|---|
| DKMS build (driver/battery) | installer user | none (fixed repo URL) | n/a | n/a | **unpinned upstream code runs as root** | continues on failure |
| `SetDisplayMode` → `envycontrol -s {mode}` | local user via D-Bus | `mode` string | yes (whitelist `integrated/hybrid/nvidia`) | yes | none (whitelisted) | JSON error |
| `SetUsbWake` → write `/proc/acpi/wakeup` | local user via D-Bus | raw `device` string | **presence-check only, no validator** | de-facto (must already exist in file) | low (kernel parses the write) | returns False |
| `SetModprobeParameter` → write conf | local user via D-Bus | `param` | yes (`nitro_v4`/`predator_v4`) | yes | none | JSON error |
| sysfs writes (fan/RGB/thermal/battery/usb) | local user via D-Bus | numeric/JSON | yes (`archer_validate`) | yes | none | logged, False |
| `RestartDriversAndDaemon` | local user via D-Bus | none | n/a | n/a | none (static `systemd-run`) | JSON error |
| GRUB param add/remove | installer user | hardcoded params | n/a | n/a | none (literals) | leaves file unchanged |
| `mkinitcpio` shim swap | installer user | none | n/a | n/a | **persists on interrupt → breaks initramfs** | **no cleanup trap** |

### 2.6 Where state/logs/temp are written

- Manifest: `/var/lib/archer/install-manifest.json` (root 0644, via `mktemp`+`install -m 0644`).
- Settings: `/etc/archer/settings.json` (daemon, atomic `os.replace`; world-readable — no secrets).
- Daemon log: `/var/log/archer-daemon.log` (`RotatingFileHandler` 5 MB × 3; world-readable) + stdout→journald.
- Installer log: optional `--log FILE` (ANSI-stripped).
- Temp: all via `mktemp`/`mktemp -d`.

### 2.7 Detection

`lib/detect.sh` handles distro family (os-release/pacman), model family (DMI product), kernel version + clang-build detection (`/proc/version`, `/proc/config.gz`, `/boot/config-*`), NVIDIA presence (lspci, cached), kernel-headers package resolution (`pacman -Qo …/vmlinuz`). Daemon re-detects driver base, laptop type (sysfs + DMI), and features at startup.

---

## 3. Threat model

**Assets:** boot integrity (initramfs/GRUB), driver/kernel-module state, root daemon integrity, user system configuration.

**Trust boundaries:** (1) internet → installer (git/AUR/PyPI downloads built as root); (2) any local user → root daemon over system D-Bus; (3) manifest file → uninstall/verify code that sources module names.

**Adversaries considered:**
- *Unprivileged local user / compromised desktop session* → can send to `io.otectus.Archer1` (bus policy allows the interface) but every mutating method requires polkit `auth_admin`. Read-only methods (telemetry, settings, firmware query) are reachable without auth by design. Risk: `_authorize` fail-open (F-SEC1) means a future un-mapped mutating method would be callable unauthenticated.
- *Malicious/compromised upstream (Linuwu-Sense, acer-wmi-battery, AUR, PyPI envycontrol)* → unpinned code is compiled and installed as root during install (F-SEC2). No commit pin, tag, or checksum.
- *Tampered manifest* → mitigated: root-owned 0644 + `is_known_module` allowlist before sourcing.
- *Malicious PATH entry* → the deliberately-installed `/usr/local/bin/mkinitcpio` shim is itself a PATH-precedence artifact; the risk is accidental persistence (F-STAB1) rather than injection. `rebuild_initramfs` correctly calls `/usr/bin/mkinitcpio` by absolute path.
- *Env/arg injection* → no `eval`; module names allowlisted; sysfs writes are values not paths; GRUB params are literals. `run_cmd` metachar guard blocks the common shell-injection class.

**Not defended (by design or gap):** offline attacker with local root (out of scope); supply-chain integrity of DKMS sources (gap, F-SEC2); a slow system tool blocking the D-Bus loop is a DoS-of-self, not a privilege issue (F-STAB6).

---

## 4. Findings

Severity: **Critical** (exploitable/data-or-boot-loss now), **High** (serious, conditional), **Medium**, **Low**, **Nitpick**.
Each finding carries the 9 required fields.

### 4.1 Security

---

**F-SEC1 — `_authorize()` fail-opens for unmapped methods** · **Severity: High** · Category: Security
- **File:** `gui/archer_dbus.py:88-93`
- **Problem:** `action_id = POLKIT_ACTIONS.get(command); if not action_id: return True`. Any command not in the map is authorized without polkit.
- **Why it matters:** the daemon runs as root. The current map covers all mutating methods, so today only read-only methods fall through (intended). But the pattern is fail-open: adding a new mutating D-Bus method and forgetting a `POLKIT_ACTIONS` entry silently ships an unauthenticated root operation reachable by any local user (the bus policy allows sending to the interface).
- **Reproduce/verify:** inspect the map vs the `@dbus.service.method` set; note `set_usb_wake`/`set_game_mode`/several booleans are covered, but the guarantee is by-convention only. Add a dummy mutating method without a map entry and observe no polkit prompt.
- **Recommended fix:** invert to fail-closed — maintain an explicit read-only allowlist; deny anything neither read-only nor mapped:
  ```python
  READ_ONLY = frozenset({"ping","get_all_settings","get_monitoring_data",
      "get_supported_features","get_fan_curve","get_display_mode","get_game_mode",
      "get_usb_power_policy","get_firmware_info"})
  def _authorize(self, command, sender):
      action_id = POLKIT_ACTIONS.get(command)
      if action_id:
          return _check_polkit(self._bus, sender, action_id)
      if command in READ_ONLY:
          return True
      logger.error(f"Refusing unmapped command {command!r} (no polkit action)")
      return False
  ```
- **Safe to implement now?** Yes — pure hardening, no behavior change for current methods. Add a test asserting every `@dbus.service.method` is either in `READ_ONLY` or `POLKIT_ACTIONS`.
- **Suggested tests:** extend `tests/test_policy_actions.py` to enumerate decorated methods via AST and assert partition coverage.

---

**F-SEC2 — DKMS/PyPI/AUR code built and installed as root from unpinned sources** · **Severity: High** · Category: Security
- **Files:** `modules/driver.sh:35-36` (Linuwu-Sense git clone), `modules/battery.sh:47` (acer-wmi-battery git clone), `modules/audio-enhance.sh:34-35` (AUR clone + `makepkg -si`), `modules/gpu.sh:65` (`pip install envycontrol --break-system-packages`).
- **Problem:** each clones `HEAD` of an upstream repo (no tag/commit pin, no signature/checksum) and compiles+installs it into the kernel/DKMS/system-python as root.
- **Why it matters:** an upstream account compromise or MITM (for the non-HTTPS-pinned fetch path) yields root code execution on every installing user's machine. This is the highest-impact security exposure because it is *build-time root*, not a runtime gate.
- **Reproduce/verify:** read the clone lines; confirm no `git checkout <pinned>` or `b2sum` verification follows.
- **Recommended fix:** pin each source to a known-good commit SHA (or signed tag) and record it centrally; optionally verify a checksum. For envycontrol, pin a version (`envycontrol==3.5.1`) and prefer the distro/AUR package over `--break-system-packages`. Document the pinned versions in README so updates are a reviewed change.
- **Safe to implement now?** Yes for pinning (no functional change beyond determinism); test in a VM to confirm the pinned commit still builds against current kernels.
- **Suggested tests:** a lint/test asserting every `git clone` in `modules/` is followed by a `git checkout` of a pinned ref.

---

**F-SEC3 — `SetUsbWake` writes an unvalidated client string to `/proc/acpi/wakeup`** · **Severity: Medium** · Category: Security
- **File:** `gui/archer_daemon.py:1160-1180` (write at `:1175-1177`); no validator in `archer_validate.py`.
- **Problem:** the client-supplied `device` string is written verbatim to `/proc/acpi/wakeup`. It is only accepted if a matching `device` name already appears in the file (`:1166-1171`), which constrains it in practice, but the value bypasses `archer_validate` entirely and relies on the kernel’s own parsing.
- **Why it matters:** a mutating root method with no explicit input validator is a latent hazard; the presence-check is the only guard and depends on exact-string matching against parsed `/proc/acpi/wakeup` output (fragile if the parse changes). Note this method has **no GUI caller** today (dead surface), which lowers exposure but also means it is untested in practice.
- **Reproduce/verify:** trace `set_usb_wake`; confirm no `validate_*` call.
- **Recommended fix:** add `validate_choice(device, {s["device"] for s in sources})` explicitly (already implied) and reject any `device` containing whitespace/newlines before the presence check; or remove the unused method entirely (see F-MAINT1).
- **Safe to implement now?** Yes.
- **Suggested tests:** dbus_smoke negative case `SetUsbWake("bogus\n", True)` expecting rejection.

---

**F-SEC4 — Dead but dangerous `force_driver_parameter` writes client param to sysfs** · **Severity: Low** (Medium if ever wired up) · Category: Security
- **File:** `gui/archer_daemon.py:1249-1252`
- **Problem:** writes a `param` value to the driver `force_parameter` sysfs node; currently unreachable (no D-Bus method, no caller).
- **Why it matters:** dead code that performs a privileged write is a footgun for a future contributor who wires it to D-Bus without adding validation/polkit.
- **Reproduce/verify:** grep for callers — none.
- **Recommended fix:** delete it, or if intended for future use, add a validator + `POLKIT_ACTIONS` entry now and a comment.
- **Safe to implement now?** Yes (deletion is safe).
- **Suggested tests:** n/a (removal).

---

**F-SEC5 — World-readable settings and log files** · **Severity: Low** · Category: Security
- **Files:** `gui/archer_daemon.py:44-46` (log, default 0644), `:169-177` (settings, default umask); `modules/gui.sh` sets no mode on `/etc/archer`.
- **Problem:** `/etc/archer/settings.json` and `/var/log/archer-daemon.log` are world-readable.
- **Why it matters:** low — neither contains secrets (only tweak state and operational logs). Still, least-privilege suggests 0640 root:root.
- **Reproduce/verify:** `stat` the files after install; inspect handler creation.
- **Recommended fix:** set an explicit `UMask=0027` in the service unit and/or `os.chmod(self.path, 0o640)` after write; create the log with `0o640`.
- **Safe to implement now?** Yes.
- **Suggested tests:** post-install permission assertion in the VM test plan.

---

**F-SEC6 — systemd hardening gaps** · **Severity: Low** · Category: Security
- **File:** `gui/archer-daemon.service:19-50`
- **Problem:** strong baseline present, but absent: `SystemCallFilter`, `CapabilityBoundingSet`/`AmbientCapabilities`, `UMask`, `ProtectProc`/`ProcSubset`, `MemoryDenyWriteExecute`, `PrivateDevices`. `NoNewPrivileges=false` and no `ProtectKernelTunables` are documented and justified (polkit + sysfs writes). `ProtectKernelModules=true` is bypassed for modprobe via `systemd-run` transient (unconfined) units.
- **Why it matters:** a root daemon benefits from a syscall filter and capability bounding to limit post-exploitation. The current gaps are defense-in-depth, not active holes.
- **Reproduce/verify:** `systemd-analyze security archer-daemon.service` (run in a systemd environment; the unit already passes `systemd-analyze verify`).
- **Recommended fix:** add `CapabilityBoundingSet=CAP_SYS_ADMIN CAP_SYS_MODULE CAP_DAC_OVERRIDE` (scoped to what sysfs/modprobe need), `SystemCallFilter=@system-service`, `UMask=0027`. Validate each addition doesn't break sysfs/envycontrol/fwupd in a VM.
- **Safe to implement now?** Partially — `UMask` is safe; syscall/capability filters need VM validation to avoid breaking function.
- **Suggested tests:** `systemd-analyze security` score before/after in the VM plan.

---

**F-SEC7 — `run_cmd` relies on a metacharacter blacklist rather than argv lists** · **Severity: Low** · Category: Security
- **File:** `gui/archer_daemon.py:74-101`
- **Problem:** `subprocess.run(shell=True)` with a denylist `(";","&&","||","$(","` `` ` ``)`. Blacklists are weaker than passing an argv list with `shell=False`; the denylist omits e.g. `|`, `>`, `<`, newline, `&`, glob.
- **Why it matters:** currently every dynamic value that reaches the shell is whitelisted or literal, so there is no active injection. But the primitive is fragile: a future callsite passing a semi-trusted value could bypass the incomplete denylist.
- **Reproduce/verify:** review `run_cmd` callsites — all current dynamic inputs (`mode`) are whitelisted upstream.
- **Recommended fix:** where no shell features are needed, pass a list and `shell=False`. For the few that need pipes (`get_cpu_usage`, `lspci | grep`), keep `shell=True` but with fully static strings and drop the denylist reliance.
- **Safe to implement now?** Yes, incrementally per callsite; low risk.
- **Suggested tests:** keep the dbus_smoke negative validation cases; add unit tests around `run_cmd` refusal.

---

### 4.2 Stability / safety

---

**F-STAB1 — `mkinitcpio` no-op shim can persist on interrupt and silently break initramfs (potential unbootable system)** · **Severity: Critical** · Category: Stability
- **File:** `modules/gpu.sh:98-121` (install) and `:140-154` (uninstall); no trap anywhere in the repo.
- **Problem:** to stop EnvyControl from invoking the interactive CachyOS/Limine `mkinitcpio` wrapper, the module moves any existing `/usr/local/bin/mkinitcpio` aside and drops a `#!/bin/sh\nexit 0` shim, runs `envycontrol`, then restores via an explicit `_gpu_restore_mkinitcpio` call. There is **no `trap … EXIT/INT/TERM`**. The in-code comment deliberately rejects a RETURN trap (correct reasoning about `functrace`), but no EXIT/INT/TERM trap replaces it.
- **Why it matters:** if the process is interrupted between shim creation (`:104-108`) and restore (`:121`) — Ctrl-C, SIGTERM, SSH disconnect, OOM, power loss, or `envycontrol` hanging past patience — the no-op shim stays in `/usr/local/bin`, which precedes `/usr/bin` in PATH. Every subsequent `mkinitcpio` invocation (including the pacman hook after the **next kernel update**) runs the shim, exits 0, produces no initramfs, and reports success. The user gets an **unbootable or stale-initramfs system** with no error pointing at the cause. This is the single highest-severity issue in the suite.
- **Reproduce/verify:** in a VM, add `sleep 30` inside the shim window, run the GPU module, Ctrl-C during the sleep, then `ls -l /usr/local/bin/mkinitcpio` (shim present) and `mkinitcpio -P` (exits 0, does nothing).
- **Recommended fix:** install an EXIT/INT/TERM trap that restores the shim, keyed on a guard variable so it is idempotent and doesn't fire for unrelated returns. Because bash traps are global, set it immediately before the swap and clear it right after restore:
  ```bash
  _gpu_shim_active=0
  _gpu_cleanup_shim() {
      [[ "$_gpu_shim_active" == 1 ]] || return 0
      _gpu_restore_mkinitcpio "/usr/local/bin/mkinitcpio" "$_gpu_had_existing"
      _gpu_shim_active=0
  }
  trap _gpu_cleanup_shim EXIT INT TERM
  _gpu_had_existing=$_had_existing
  _gpu_shim_active=1
  # ... swap, run envycontrol ...
  _gpu_cleanup_shim
  trap - EXIT INT TERM
  ```
  A more robust alternative avoids the PATH shim entirely: set `PATH=/usr/bin:$PATH` (or a temp dir with only the needed tools) for just the `envycontrol` invocation, or pass EnvyControl a flag/env to skip its initramfs step if one exists.
- **Safe to implement now?** The trap is safe and high-value; validate in a VM that it fires on INT/TERM and doesn't misfire across the two shim windows (install vs uninstall). The PATH-based alternative needs more testing.
- **Suggested tests:** a bats test that stubs `envycontrol` to `kill -INT $$` mid-run and asserts `/usr/local/bin/mkinitcpio` is restored afterward.

---

**F-STAB2 — No rollback trap; interrupted install leaves partial system state** · **Severity: High** · Category: Stability
- **Files:** `install.sh` (no `trap`), `run_selected_modules:226-270` (only manifest-accumulator rollback), all modules (in-place config overwrites, no backups).
- **Problem:** the only rollback is reverting manifest accumulator strings on a module returning non-zero (`:246-258`). There is no cleanup for a mid-module interrupt: half-written `/etc/modprobe.d`, `/etc/tlp.d`, GRUB edits, added DKMS trees, the GPU shim (F-STAB1), and masked services persist with no record.
- **Why it matters:** a Ctrl-C during a long DKMS build or `pacman -Syu` leaves the system in an undefined intermediate state the uninstaller may not fully reverse (uninstall keys off the manifest, which isn't written until the end).
- **Reproduce/verify:** interrupt an install mid-module in a VM; inspect leftover `/etc` files and `dkms status`.
- **Recommended fix:** write the manifest incrementally (append each module as it completes) so uninstall can always reverse what actually ran; add an INT/TERM trap that at minimum warns the user what state was reached and how to clean up. Take `.archer-bak` backups before overwriting GRUB/TLP/modprobe configs.
- **Safe to implement now?** Incremental manifest + warning trap are safe; config-backup changes need testing.
- **Suggested tests:** manifest round-trip test (`lib/manifest.sh` is currently untested); interrupt simulation in VM plan.

---

**F-STAB3 — `gui.sh` uses `error` (exit) instead of `return 1`, killing the whole installer and bypassing per-module rollback** · **Severity: High** · Category: Stability
- **File:** `modules/gui.sh:40-44`
- **Problem:** on a missing GUI source file the module calls `error "…"`, and `error` does `exit 1` (`lib/utils.sh:31`). Because modules are `source`d into the installer, this terminates the entire `install.sh` process, bypassing `run_selected_modules`' rollback/continue logic that every other module relies on (they `return 1`).
- **Why it matters:** one missing/renamed GUI file aborts a multi-module install partway, leaving prior modules installed but the manifest unwritten (uninstall then can't cleanly reverse them) — an inconsistent-state hazard, and inconsistent with the rest of the module contract.
- **Reproduce/verify:** temporarily rename a listed GUI source file, run `./install.sh --modules driver,gui` in a VM; observe the process exits rather than recording driver + skipping gui.
- **Recommended fix:** replace `error` with `warn` + `return 1` in module bodies:
  ```bash
  [[ -f "$_src" ]] || { warn "Required GUI source file missing: $_src"; return 1; }
  ```
- **Safe to implement now?** Yes — small, mechanical, matches the established module contract.
- **Suggested tests:** modules.bats case asserting `module_install` returns non-zero (not exits) when a source file is absent.

---

**F-STAB4 — Dry-run leaks: `makepkg -si` and `mktemp -d` execute for real under `--dry-run`** · **Severity: Medium** · Category: Stability
- **File:** `modules/audio-enhance.sh:30-40` (`mktemp -d` at `:32`, `makepkg -si` at `:35` not wrapped in `run`); also `lib/manifest.sh:65-116` generates the temp manifest for real in dry-run.
- **Problem:** `DRY_RUN` is honored only by the `run`/`run_sudo`/`run_sudo_timeout` wrappers. In the no-AUR-helper branch, `git clone` is wrapped (no-op in dry-run) but the subsequent `(cd … && makepkg -si …)` is not — so on a dry-run without paru/yay it would `cd` into an empty temp dir and actually invoke `makepkg`.
- **Why it matters:** `--dry-run` is a documented safety feature (README). A dry-run that builds packages violates the contract and can partially mutate the system. Verified via container dry-run: the GPU/manifest paths are correctly gated, but audio-enhance's makepkg path is not exercised there (no clone succeeds offline).
- **Reproduce/verify:** in a VM with no AUR helper, `./install.sh --dry-run --modules audio-enhance`; observe `makepkg` runs.
- **Recommended fix:** wrap the build in `run`, or guard the whole no-AUR branch behind `[[ "$DRY_RUN" == 1 ]] && { log "[DRY RUN] would build noise-suppression-for-voice"; return 0; }`.
- **Safe to implement now?** Yes.
- **Suggested tests:** bats: set `DRY_RUN=1`, stub `makepkg` to `touch marker`, assert marker absent.

---

**F-STAB5 — Installer runs `pacman -Syu` (full system upgrade) as an install side effect** · **Severity: Medium** · Category: Stability
- **File:** `install.sh:223` (`run_sudo pacman -Syu --needed --noconfirm "${deps[@]}"`).
- **Problem:** installing Archer’s dependencies triggers a full system upgrade of the user's machine.
- **Why it matters:** on Arch, a surprise `-Syu` can pull in unrelated breaking updates, require reboots, and is a partial-upgrade hazard if it fails midway. Users don't expect a hardware-tweak installer to upgrade their whole system, and it isn't documented.
- **Reproduce/verify:** read the line; `--dry-run` shows the `-Syu` (container output confirms `pacman -Syu` in dry-run for shared deps path via the module deps).
- **Recommended fix:** use `pacman -S --needed --noconfirm "${deps[@]}"`. If sync-db freshness is a concern, `pacman -Sy` is itself a partial-upgrade footgun; prefer documenting "run `pacman -Syu` yourself first" and just `-S --needed`.
- **Safe to implement now?** Yes, and recommended; note it changes behavior (no longer upgrades), so mention in CHANGELOG.
- **Suggested tests:** grep test that install uses `-S` not `-Syu` for deps.

---

**F-STAB6 — Daemon D-Bus methods run synchronously on the GLib loop; slow tools block all IPC** · **Severity: Medium** · Category: Stability/Performance
- **File:** `gui/archer_daemon.py` (all `@dbus.service.method` handlers run on the main loop); `SetDisplayMode` runs `envycontrol` (up to 30 s) at `:1056`; telemetry emit every 2 s calls `get_monitoring_data` which may spawn `nvidia-smi`.
- **Problem:** a slow `envycontrol`/`fwupdmgr`/`nvidia-smi` blocks the single GLib loop, freezing telemetry and every other client call for the duration.
- **Why it matters:** the GUI appears hung (mitigated by client-side long timeouts + a 5 s probe cache, but a 30 s envycontrol still stalls telemetry). It's a self-DoS, not a security issue.
- **Reproduce/verify:** call `SetDisplayMode` and observe telemetry stalls for its duration.
- **Recommended fix:** offload long-running shell calls to worker threads and marshal results back (mirror the GUI's `async_set` pattern on the daemon side), or run them via `systemd-run --no-block` where a result isn't needed.
- **Safe to implement now?** Needs careful threading review; defer to Phase 3.
- **Suggested tests:** timing test asserting telemetry continues during a stubbed-slow method.

---

**F-STAB7 — Legacy uninstall disables shared services / removes non-owned artifacts** · **Severity: Medium** · Category: Stability
- **File:** `uninstall.sh:79-145` (esp. `:144` `systemctl disable --now fwupd.service`), and per-module: `firmware.sh:38` disables `fwupd.service`, `power.sh` unmasks `systemd-rfkill`, `gamemode.sh` `rmdir /etc/gamemode.d`.
- **Problem:** the legacy path (no manifest) unconditionally disables `fwupd.service` and removes third-party DKMS trees regardless of whether Archer installed/enabled them. `fwupd` is a standard, shared system service a user likely wants.
- **Why it matters:** uninstall should remove only Archer-owned state. Disabling `fwupd` (which many systems rely on for firmware updates) is an over-reach that violates the "remove only what we installed" principle.
- **Reproduce/verify:** run legacy uninstall in a VM with fwupd pre-enabled; observe it gets disabled.
- **Recommended fix:** only disable/remove a shared service if the manifest records that Archer enabled it; otherwise leave it. Record "did Archer enable fwupd?" at install time. Never `rmdir /etc/gamemode.d` unless Archer created it.
- **Safe to implement now?** Requires manifest schema addition (track enabled services); do in Phase 2.
- **Suggested tests:** uninstall test asserting pre-existing fwupd state is preserved.

---

**F-STAB8 — `wifi.sh` removes/rescans a PCI device; `remove_grub_params` uses unanchored non-literal sed; no GRUB backup** · **Severity: Low/Medium** · Category: Stability
- **Files:** `modules/wifi.sh:69-73` (PCI `remove`/`rescan` from `lspci`-derived address), `lib/utils.sh:214` (`sed "s|$p||g"` — `$p` unescaped, `.` acts as regex wildcard, substring-unanchored), `lib/utils.sh:162-228` (no `.bak` before GRUB edits).
- **Problem:** (a) removing/rescanning a live PCI device can drop the Wi-Fi interface mid-operation; errors are suppressed. (b) `remove_grub_params` treats params as regex and removes unanchored substrings; current params are literals so no active bug, but a param containing `.` (e.g. `acer_wmi.predator_v4=1`) is matched as a wildcard and could over-match. (c) GRUB is edited without a backup.
- **Why it matters:** boot-config edits without backups and regex-based param removal are fragile; the PCI reset is a targeted but risky recovery action.
- **Reproduce/verify:** static review; test `remove_grub_params "acer_wmi.predator_v4=1"` against a crafted grub line.
- **Recommended fix:** back up `/etc/default/grub` to `.archer-bak` before edits; make removal literal (`awk`/`grep -F` word-boundary matching, not `sed` regex); gate the PCI reset behind explicit user confirmation.
- **Safe to implement now?** GRUB backup + literal removal are safe; PCI-reset gating is safe.
- **Suggested tests:** utils.bats cases for `add_grub_params`/`remove_grub_params` with dotted params and idempotency.

---

**F-STAB9 — Daemon can restart itself during `__init__` before D-Bus registration** · **Severity: Low** · Category: Stability
- **File:** `gui/archer_daemon.py:322-325` (`_maybe_autoforce_v4` in `HardwareManager.__init__`, which calls `restart_drivers_and_daemon`).
- **Problem:** on a DMI-unmatched gaming Acer, first startup writes a modprobe param and restarts the daemon before it has registered on D-Bus. There is a loop guard (param-already-set check), but the self-restart during construction is subtle.
- **Why it matters:** a restart loop is guarded, but a failed restart or an environment where the param never yields the sense interface could produce confusing startup churn.
- **Reproduce/verify:** simulate `driver_base` set + `sense_base` None + laptop_type nitro; observe restart path.
- **Recommended fix:** move the auto-force out of `__init__` into an explicit post-registration step, or make it a one-shot that logs clearly and never restarts more than once per boot (persist a boot-scoped marker).
- **Safe to implement now?** Needs owner intent (this is a deliberate self-heal); flag as "do not touch yet" pending discussion.
- **Suggested tests:** unit test with fakes asserting single restart + loop-guard.

---

### 4.3 Functionality (confirmed bugs)

---

**F-FUNC1 — `display_mode` type mismatch crashes `load_settings` for all pages when EnvyControl is present** · **Severity: High** · Category: Functionality
- **Files:** producer `gui/archer_daemon.py:969` + `get_display_mode:1033-1043` (returns a **dict** `{"mode","available_modes","reboot_required"}`); consumers `gui/archer/widgets/hero.py:94-95` (`_MODE_LABELS.get(mode, …)`) and `gui/archer/pages/display.py:122-156` (`mode_labels.get(mode, mode.title())`); loop with no isolation `gui/archer/window.py:285-286`.
- **Problem:** `get_all_settings` sets `display_mode` to the dict on machines where `"display_mode"` is a detected feature (EnvyControl installed). The hero and display widgets treat it as a string: `dict.get(dict)` → `TypeError: unhashable type` and dict has no `.title()`.
- **Why it matters:** on an affected machine, `load_settings` raises; because `_on_settings_loaded` iterates pages with no per-page try/except, **the exception aborts the whole loop** — remaining pages never load and the GUI is left partially initialized. On machines *without* EnvyControl the daemon sends `None` and the bug is masked (which is why the construct smoke test, using a stub string `"hybrid"`, passes — the stub doesn't reproduce the daemon's dict shape).
- **Reproduce/verify:** feed `get_all_settings` output shape (dict `display_mode`) into `hero.load_settings`; observe `TypeError`. The GUI construct test at `tests/test_gui_construct.py:58` uses `"display_mode": "hybrid"` (a string), masking the real daemon contract — itself a test gap.
- **Recommended fix:** pick one contract. Simplest: have `get_all_settings` store the string, e.g. `"display_mode": self.get_display_mode()["mode"]`, and expose the extra fields under a separate key if needed. Also make the consumers defensive (`mode = mode.get("mode") if isinstance(mode, dict) else mode`) and wrap the page loop:
  ```python
  for name, page in self._pages.items():
      try:
          page.load_settings(data)
      except Exception as e:
          logger.exception("Page %s failed to load settings: %s", name, e)
  ```
- **Safe to implement now?** Yes — both the contract fix and the loop isolation are safe and high value.
- **Suggested tests:** update the stub in `test_gui_construct.py` to use the **daemon’s actual dict shape** for `display_mode` (would have caught this); add a regression test.

---

**F-FUNC2 — Firmware "Check for Updates" leaks rows on repeated clicks** · **Severity: Low** · Category: Functionality
- **File:** `gui/archer/pages/firmware.py:170-191`
- **Problem:** the comment says "Remove old dynamic rows" but no removal code exists; each check appends fresh `Adw.ActionRow`s to `_updates_group` without clearing prior ones.
- **Why it matters:** repeated "Check for Updates" clicks accumulate duplicate rows unboundedly in that group.
- **Reproduce/verify:** click Check for Updates twice with updates present; rows duplicate.
- **Recommended fix:** track added rows (or iterate `_updates_group` children) and remove them before re-adding:
  ```python
  for row in getattr(self, "_dynamic_rows", []):
      self._updates_group.remove(row)
  self._dynamic_rows = []
  # ... append and record each row into self._dynamic_rows
  ```
- **Safe to implement now?** Yes.
- **Suggested tests:** GUI test calling `_display_updates` twice, asserting stable child count.

---

**F-FUNC3 — `validate_fan_curve_points` accepts an empty list; engine starts with no points** · **Severity: Low** · Category: Functionality
- **File:** `gui/archer_validate.py:121-136`; consumer `gui/archer_daemon.py:286-287` (`_interpolate` returns 30 on empty).
- **Problem:** an empty points list validates OK; an "enabled" curve with zero points starts the `FanCurveEngine`, which then interpolates to a constant 30.
- **Why it matters:** a degenerate but non-crashing state; the fan runs a flat curve the user didn't intend.
- **Reproduce/verify:** `SetFanCurve('{"target":"cpu","points":[]}')` — accepted.
- **Recommended fix:** require ≥2 points (and monotonic temps) in the validator.
- **Safe to implement now?** Yes.
- **Suggested tests:** `test_validate.py` case for empty/one-point lists → error.

---

**F-FUNC4 — `camera-enhance.sh` records a fabricated DKMS version; uninstall never removes the module** · **Severity: Low** · Category: Functionality
- **File:** `modules/camera-enhance.sh:40` (records `v4l2loopback/0.13.2`, a hardcoded guess not derived from the installed package); uninstall only `modprobe -r` + `rm conf`, never `dkms remove`.
- **Problem:** the manifest records a version string that may not match reality, and nothing uses it; the DKMS module isn't dkms-removed on uninstall.
- **Why it matters:** manifest inaccuracy + incomplete uninstall (the v4l2loopback DKMS module lingers).
- **Reproduce/verify:** install then uninstall camera-enhance in a VM; `dkms status` still lists v4l2loopback.
- **Recommended fix:** derive the actual version (`dkms status v4l2loopback`) or don't record one; add the dkms-remove to uninstall.
- **Safe to implement now?** Yes.
- **Suggested tests:** modules.bats behavioral check with stubbed dkms.

---

### 4.4 UX

- **F-UX1 (Medium, UX):** Inconsistent confirmations — battery calibration, display-mode switch, and full driver+daemon restart show confirm dialogs (`battery.py:224`, `display.py:178`, `internals.py:186`), but modprobe-override apply, plain daemon restart, and thermal/fan/keyboard/game-mode/audio/LCD/boot toggles do not. Privileged/impactful actions (modprobe override, daemon restart) should confirm. *Fix:* add confirm dialogs to modprobe apply + daemon restart. Safe now.
- **F-UX2 (Low, UX):** Silent failures — `system.py:215,224,236,240` swallow `FileNotFoundError` when launching a log viewer/editor/browser with no user feedback; add a toast on failure. Safe now.
- **F-UX3 (Low, UX):** `detect_mux` is never called (`daemon:1063-1086`), so `get_all_settings` never includes `mux_switch` and `display.py:137-139` permanently hides the MUX group — a dead feature the UI implies exists. *Fix:* wire it up or remove the group. Needs owner intent (was MUX intended?).
- **F-UX4 (Low, UX):** Client classifies auth/timeout errors by **string-matching** the exception text (`client.py:146-156`), which is locale/message fragile. *Fix:* catch typed `dbus.exceptions.DBusException` and branch on `.get_dbus_name()`.
- **F-UX5 (Nitpick, UX):** No in-GUI first-run/compatibility flow; detection lives only in the installer. A "your hardware/driver status" panel would help non-experts. Enhancement.
- **F-UX6 (Nitpick, UX):** Desktop entry `Categories=System;Settings;HardwareSettings;` triggers a desktop-file-validate hint (multiple main categories → may appear twice in menus). *Fix:* keep one main category. Safe now.

### 4.5 Architecture / Maintainability

- **F-MAINT1 (Low):** Dead code — `detect_mux`, `force_driver_parameter`, `capability_row.set_row_supported`, and several unused client/daemon methods (`ping`, `get_supported_features`, `get_usb_power_policy`, `set_usb_wake`, `get_fan_curve`, `get_game_mode`, `get_display_mode` have no GUI callers). *Fix:* prune or document intent.
- **F-MAINT2 (Low):** Version literals not centralized — `lib/utils.sh:12` (2.1.0), `archer_daemon.py:25` (2.1.0), `gui/archer/__init__.py` (1.1.0), `system.py:89` ("1.0.1"), installer banners say "v2.0". *Fix:* single source of truth (a `VERSION` file read by both layers).
- **F-MAINT3 (Low):** Naming split — desktop/icon/app-id use `io.github.archer(.gui)`; D-Bus/policy/conf use `io.otectus.Archer1`. Confusing but not broken. *Fix:* document the split or unify.
- **F-MAINT4 (Low):** Module conventions vary — `module_detect` semantics (`firmware.sh` always 0, `audio.sh` always 1), private-var naming (`driver.sh` bare vs `_UPPER` elsewhere), `success` vs `log` mid-install, AUR-helper re-probe in `audio-enhance.sh`. *Fix:* a short module authoring convention doc + normalization.
- **F-MAINT5 (Low):** `get_firmware_info` catches `(json.JSONDecodeError, Exception)` (`daemon:1195`) — the broad `Exception` makes the specific clause dead and swallows all errors. *Fix:* catch narrowly.
- **F-MAINT6 (Nitpick):** `SettingsStore` instantiated twice at startup (`daemon:1273-1274`) — no leak, two code paths. `_parse_gpus` imports `shlex` inside the function.

### 4.6 Testing / CI

- **F-TEST1 (Medium):** Two bats tests fail in this working tree — `install.bats:86` "module_index … fails for unknown" and `install.bats:114` "verify_modules returns non-zero". Root cause: `module_index not-a-module` and `verify_modules` return non-zero as expected, but the tests run them via bats `run` while `lib/utils.sh` defines its own `run()` that **shadows the bats `run` helper** (noted in utils.bats), so `$status` isn't populated as the test assumes. This is a **test harness bug**, not a product bug — but it means CI would be red on these. *Fix:* rename the product wrapper (e.g. `arun`) or the tests should call the functions directly and check `$?`. Verify before "fixing."
- **F-TEST2 (Medium):** CI triggers only on `push`/`pull_request` to `master`/`main` (`ci.yml:5-7`); the active development branch gets no CI. *Fix:* run CI on all branches or at least on PRs regardless of base.
- **F-TEST3 (Medium):** No test exercises `module_install`/`module_uninstall`, `lib/manifest.sh` round-trip, real polkit authorization (stubbed to True in `dbus_smoke.py:152`), or install/uninstall/rollback. The GUI stub uses a string `display_mode`, masking F-FUNC1. *Fix:* add manifest round-trip unit tests, a container-based install/uninstall smoke, and correct the stub shape.
- **F-TEST4 (Low):** CI lacks `ruff`, `bandit`, `pip-audit`; `flake8` ignores E501/E402/W503 so line length isn't enforced despite `--max-line-length=120`. `ruff check` reports 66 issues (65 E402 from the mandatory `gi.require_version` before imports — acceptable/expected; 1 genuine unused import `Gtk` in `test_gui_construct.py:23`). `bandit` flags the known `shell=True` (High, F-SEC7) + Low subprocess/try-except-pass items. *Fix:* add ruff/bandit/pip-audit jobs with a curated ignore list; fix the unused import.
- **F-TEST5 (Nitpick):** `tests/__pycache__/*.pyc` (cpython-314) are present in the working tree; `.gitignore` covers them but they shouldn't be staged. Confirm none are committed.

### 4.7 Documentation

- **F-DOC1 (Medium):** No git tags exist despite CHANGELOG releases 2.0.0/2.0.1/2.1.0 (`git tag -l` empty). *Fix:* tag releases; wire compare links.
- **F-DOC2 (Low):** CONTRIBUTING is stale — the local `flake8` command omits the `--ignore` flags CI uses (so a contributor sees spurious failures), the "CI Pipeline" section lists 4 of 8 jobs, and `sudo pacman -S … bash-bats` names a non-existent package (Arch package is `bats`). *Fix:* sync CONTRIBUTING to `ci.yml`.
- **F-DOC3 (Low):** README documents `--dry-run` as a safety feature; F-STAB4 (dry-run leak) contradicts it. Fix the code, keep the doc.
- **F-DOC4 (Low):** Version banners say "v2.0" while `INSTALLER_VERSION=2.1.0`; the README has no single version banner and relies on runtime print. Align with F-MAINT2.
- **F-DOC5 (Nitpick):** Screenshot is an external imgur link (`README.md:5`), not an in-repo asset — link rot risk. MIT `LICENSE` has a generic (unnamed) copyright holder.

### 4.8 Packaging / Release

- **F-PKG1 (Medium):** For an Arch-targeted project there is **no PKGBUILD / AUR package / .deb / Flatpak** — install is a source-tree bash copy into `/opt`, `/etc`, `/usr/share`, `/usr/local/bin`. A PKGBUILD would give pacman-tracked files, clean uninstall, and dependency handling, eliminating much of the custom install/uninstall/manifest machinery. *Fix (larger):* consider a PKGBUILD; at minimum document why not.
- **F-PKG2 (Low):** Desktop entry `Exec=python3 /opt/archer/archer_gui.py` bypasses the installed `/usr/local/bin/archer-gui` launcher — two divergent launch paths. *Fix:* `Exec=archer-gui`.
- **F-PKG3 (Low):** All repo files are mode 0755 (including `.md`, `.py`, `.service`, `.conf`); `systemd-analyze verify` warns the `.service` is executable. *Fix:* normalize to 0644 for non-scripts.
- **F-PKG4 (Low):** Version metadata not centralized (F-MAINT2); releases not reproducible without tags (F-DOC1).

### 4.9 Compatibility

- **F-COMPAT1 (Low):** Correctly Arch-only (guards non-Arch behind `confirm`), model-family aware, kernel-version and clang-build aware, NVIDIA-presence aware, batteryless-aware (GUI shows "No battery"). Wayland/X11 and GNOME/KDE are largely irrelevant (GTK4 app + KDE-SNI tray with graceful fallback). Gaps: bootloader coverage is GRUB + systemd-boot for initramfs but **only GRUB for kernel-param injection** (systemd-boot users get a manual-edit message; Limine kernel params not handled) — document this. EnvyControl/NVIDIA paths are the least portable.

### 4.10 Performance

- **F-PERF1 (Low):** Telemetry push every 2 s calls `get_monitoring_data` (nvidia-smi/hwmon), mitigated by a 5 s probe cache — reasonable. Dashboard history bounded (`deque(maxlen=60)`); logs rotated (5 MB×3). Main concern is F-STAB6 (sync daemon loop) and F-FUNC2 (firmware row leak). No indefinite growth found otherwise.

---

## 5. Prioritized risk table

| ID | Title | Severity | Category | Safe to fix now? |
|---|---|---|---|---|
| F-STAB1 | `mkinitcpio` shim persists on interrupt → unbootable | **Critical** | Stability | Trap: yes (VM-verify) |
| F-SEC1 | `_authorize` fail-opens for unmapped methods | High | Security | Yes |
| F-SEC2 | Unpinned root-built DKMS/PyPI/AUR sources | High | Security | Pinning: yes (VM-verify build) |
| F-STAB2 | No rollback trap; partial install state | High | Stability | Incremental manifest: yes |
| F-STAB3 | `gui.sh` `error`→exit kills installer | High | Stability | Yes |
| F-FUNC1 | `display_mode` dict/string crashes all page loads | High | Functionality | Yes |
| F-SEC3 | `SetUsbWake` unvalidated `/proc/acpi/wakeup` write | Medium | Security | Yes |
| F-STAB4 | Dry-run leaks (`makepkg -si`) | Medium | Stability | Yes |
| F-STAB5 | Installer does `pacman -Syu` | Medium | Stability | Yes |
| F-STAB6 | Daemon methods block GLib loop | Medium | Stability/Perf | Phase 3 |
| F-STAB7 | Uninstall disables shared `fwupd` | Medium | Stability | Phase 2 (needs manifest) |
| F-UX1 | Missing confirmations on impactful actions | Medium | UX | Yes |
| F-TEST1 | Two bats tests red (harness `run` shadow) | Medium | Testing | Yes |
| F-TEST2 | CI doesn't run on feature branches | Medium | Testing | Yes |
| F-TEST3 | No install/uninstall/manifest/polkit tests | Medium | Testing | Phase 4 |
| F-DOC1 | No git tags for releases | Medium | Documentation | Yes |
| F-PKG1 | No PKGBUILD/AUR packaging | Medium | Packaging | Larger |
| F-SEC4/5/6/7 | Dead sysfs writer, world-readable files, systemd/`run_cmd` hardening | Low | Security | Mostly yes |
| F-FUNC2/3/4 | Firmware row leak, empty fan curve, camera manifest | Low | Functionality | Yes |
| F-STAB8/9 | GRUB backup/sed, PCI reset, self-restart in init | Low/Med | Stability | Mixed |
| F-UX2–6, F-MAINT*, F-DOC2–5, F-PKG2–4 | Various | Low/Nitpick | — | Mostly yes |

---

## 6. Recommended next actions

1. **Phase 0 now:** F-STAB1 trap, F-SEC1 fail-closed authorize, F-STAB3 `error`→`return 1`, F-STAB4 dry-run leak, F-SEC2 pin sources. These are small, safe, and remove the worst outcomes.
2. **Phase 1:** F-FUNC1 (display_mode) + per-page load isolation, F-STAB5 (`-Syu`→`-S`), F-FUNC2/3/4.
3. **Fix the two red bats tests (F-TEST1)** and turn on CI for feature branches (F-TEST2) before further change, so the suite is green and gating.
4. Then Phases 2–4 per `IMPLEMENTATION_PLAN.md`.

---

## 7. Test plan

### 7.1 Host-safe commands (no system mutation)
```bash
# Static
shellcheck -x install.sh uninstall.sh lib/*.sh modules/*.sh      # currently: 0 findings
bash -n install.sh uninstall.sh lib/*.sh modules/*.sh            # clean
desktop-file-validate gui/io.github.archer.desktop              # 1 hint (categories)
systemd-analyze verify gui/archer-daemon.service               # ok (exec-bit warning only)

# Python (pure unit, no gi/dbus)
python3 tests/test_validate.py                                  # PASS
python3 tests/test_policy_actions.py                            # PASS
uvx ruff check gui/ tests/                                      # 66 (65 expected E402 + 1 real)
uvx bandit -r gui/                                              # 1 High (shell=True), 13 Low
pipx run pip-audit -r gui/requirements-gui.txt                  # no known vulns

# Bats (DRY_RUN=1 + mocked hardware — safe)
bats tests/*.bats                                               # 65/67 (2 harness-shadow failures, F-TEST1)
```

### 7.2 Container-only (host lacks gi/dbus; dry-run leaks make host unsafe)
```bash
# Disposable Arch container, repo mounted read-only, copied to /work:
docker run --rm -v "$PWD":/archer:ro archlinux:latest bash -c '
  pacman -Syu --noconfirm --needed python python-gobject python-dbus gtk4 \
    libadwaita xorg-server-xvfb dbus jq git sudo which >/dev/null;
  cp -r /archer /work && cd /work;
  ./install.sh --version;
  ./install.sh --dry-run --all --no-confirm;           # verify NO /var/lib/archer or shim leak
  xvfb-run -a python3 tests/test_gui_construct.py;      # PASS (all 10 pages)
'
```
*Observed:* dry-run left no `/var/lib/archer` and no `/usr/local/bin/mkinitcpio` shim (good); GUI construct passed all pages; the `dbus_smoke.sh` harness did not complete under python-3.14/dbus-python in the container (autolaunch/NoReply — environment artifact, re-run on a real session bus / systemd VM).

### 7.3 Disposable Ubuntu/Arch **VM** validation (real install/uninstall)
> Archer is Arch-only; use a disposable **Arch/CachyOS VM**, not Ubuntu. Never run these on a host.
1. Snapshot VM. `./install.sh --dry-run --all` — confirm plan, no mutation.
2. `./install.sh --modules gui` — verify daemon starts, D-Bus name owned, GUI launches, `systemd-analyze security archer-daemon.service`.
3. Interrupt test (F-STAB1): run the GPU module with `envycontrol` stubbed to sleep, Ctrl-C mid-run, confirm `/usr/local/bin/mkinitcpio` restored and `mkinitcpio -P` still real.
4. `./uninstall.sh` — confirm only Archer-owned files removed; pre-existing `fwupd` state preserved (F-STAB7).
5. Manifest round-trip: install 2 modules, inspect `/var/lib/archer/install-manifest.json`, uninstall, confirm clean.
6. Revert snapshot.

### 7.4 Manual GUI QA (in VM with GUI)
- Each page loads without traceback on a machine **with** EnvyControl installed (targets F-FUNC1).
- Daemon-offline behavior: stop `archer-daemon.service`, confirm GUI shows offline toast + reconnect backoff, no hang.
- Firmware "Check for Updates" twice — confirm no duplicate rows (F-FUNC2).
- Trigger a setter failure (e.g., write-protected sysfs) — confirm control reverts + toast, no traceback.
- Confirm dialogs present for calibration/display/driver-restart; note absent ones (F-UX1).
- Tray: minimize-to-tray, restore, exit.
