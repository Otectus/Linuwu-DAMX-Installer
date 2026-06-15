---
name: GUI not updating / daemon unreachable
about: Use this when the Archer GUI shows stale data, says "Daemon Offline" / "Stale", or won't open at all.
title: "[GUI] "
labels: [gui]
assignees: []
---

<!--
Please paste the output of every command in the template below. Even if
something looks irrelevant, leaving it out usually means we have to ask
for it in a follow-up. The faster we have all of this, the faster the
fix lands.
-->

## What you saw

<!-- Describe the symptom. A screenshot of the GUI window helps a lot. -->

## What you expected

<!-- e.g. "Dashboard should show live CPU/GPU temperatures." -->

## Environment

- **Distro and version**: <!-- e.g. CachyOS 2026.04, EndeavourOS 2026.04 -->
- **Kernel** (`uname -r`):
- **Archer commit**: <!-- run `git -C /path/to/Archer rev-parse --short HEAD` -->
- **Hardware**: <!-- e.g. Acer Nitro 5 AN515-58 -->

## Daemon status

<details>
<summary><code>systemctl status archer-daemon</code></summary>

```
PASTE OUTPUT HERE
```

</details>

<details>
<summary><code>journalctl -u archer-daemon -n 100 --no-pager</code></summary>

```
PASTE OUTPUT HERE
```

</details>

## D-Bus visibility

<details>
<summary><code>busctl list | grep -i archer</code></summary>

```
PASTE OUTPUT HERE
```

</details>

<details>
<summary><code>busctl introspect io.otectus.Archer1 /io/otectus/Archer1 2>&1 | head -50</code></summary>

```
PASTE OUTPUT HERE
```

</details>

## GUI logs

<details>
<summary><code>journalctl --user -t archer-gui -n 100 --no-pager</code></summary>

```
PASTE OUTPUT HERE (if empty, paste any error printed to the terminal when you ran `archer-gui`)
```

</details>

## Did you try

- [ ] `sudo systemctl reload dbus.service && sudo systemctl restart archer-daemon`
- [ ] Re-running the installer (`./install.sh --modules gui --no-confirm`)
- [ ] Reading [README → Troubleshooting](https://github.com/otectus/Archer#troubleshooting)
