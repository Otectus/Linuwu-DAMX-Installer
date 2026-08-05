# ENE K5130 keyboard lighting protocol — Acer Predator Helios Neo 16S AI (PHN16S-71)

Reverse-engineered notes for the LED controller that actually drives the
keyboard backlight on this model. Everything below was verified on real
hardware against a fully dark baseline.

> **AI assistance.** This protocol was reverse-engineered in a session assisted
> by an AI agent (Claude). The agent proposed the experiments, wrote the probing
> tools and the code; a human operator ran them on the affected machine and
> reported what the keyboard actually did. **Every behavioural claim here rests
> on a human observing the hardware, not on model inference.** Several early
> conclusions were wrong and were corrected by that operator; the notes below
> reflect the corrected state.

---

## 1. Why this exists

The ACPI-WMI lighting path on this model is **partially implemented in
firmware**. Within a single `SET_GAMING_KB_BACKLIGHT` call:

| Field | Result |
|---|---|
| brightness | **applied** |
| RGB | **discarded** |
| effect mode | **discarded** |

And the per-zone call (`SET_GAMING_RGB_KB`) stores the colours, returns them
faithfully on read-back, and never applies them to the LEDs.

That combination is what makes the bug so quiet: every layer above reports
success. **On this model a sysfs read-back is not evidence that anything
happened.** Confirmed by writing red/green/blue/white at full brightness with
all competing writers stopped: read-back exact, keyboard unchanged.

## 2. Transport

| Item | Value |
|---|---|
| Chip | ENE K5130, HID id `0018:0CF2:5130` |
| Bus | I²C-1, address `0x50`, 400 kHz, GpioInt with wake |
| Protocol | standard HID-over-I2C, **feature reports only** (no Input, no Output) |
| Access | `HIDIOCSFEATURE` on the ENE's hidraw node |
| Readable | only `0xA1`. `0xA2`/`0xA3`/`0xA4` are **write-only** — a GET returns an echo of the command, not data |

**Resolve the node by HID identity, never by hidraw number.** The numbering is
not stable here: the ENE's reset times out during probe so it enumerates last,
and the touchpad can rebind and reclaim `hidraw0`.

## 3. Devices

`0xA1` (4 bytes, read-only) returns `03 65 21 83` — a device count followed by
the device ids.

| Device id | Physical element | How it was verified |
|---|---|---|
| `0x65` | performance-mode button LED | mode 1 → took the exact red requested |
| `0x21` | **keyboard**, 4 zones | mode 2 → bright static green from a dark baseline |
| `0x83` | lid logo | responds, but does not interpret RGB like the keyboard (see §8) |

## 4. Required sequence

```
1)  0xA2 = <device_id>        select device      (1 byte)
2)  0xA4 = <configuration>    apply             (10 bytes)
```

**Step 1 is mandatory.** Without a prior selection using a *valid* device id,
`0xA4` has no effect. Writing an arbitrary value such as `1` is not a
selection — `1` is not one of the enumerated ids — and the handshake silently
fails.

## 5. Report `0xA4` — 10 bytes

| Byte | Usage | Field | Range | Notes |
|---|---|---|---|---|
| 0 | `0x21` | device id | — | same id selected in `0xA2` |
| 1 | `0x41` | **mode** | 0–31 | see §6. **Semantics are per device** |
| 2 | `0x43` | **brightness** | 0–100 | |
| 3 | `0x42` | **speed** | 0–9 | monotonically faster; see §6.1 |
| 4 | `0x44` | **direction** | 1–2 | see §6.1 |
| 5 | `0x45` | **R** | 0–255 | |
| 6 | `0x46` | **G** | 0–255 | |
| 7 | `0x47` | **B** | 0–255 | |
| 8–9 | `0x48` | **zone bitmask**, 16-bit LE | — | see §7 |

## 6. Modes

⚠️ **Mode semantics do not carry over between devices.** On the keyboard mode 1
turns it off; on the button LED mode 1 is static colour. Generalising from one
device to another produces silent no-ops, and this cost a lot of time to find.
Each device id needs its own catalogue.

### Keyboard (`0x21`) — verified

Numbering is the ENE's own and does **not** match the WMI mode numbers other
Acer tools document (0 Static, 1 Breath, 2 Neon, 3 Wave, 4 Shifting, 5 Zoom).
Names below are matched to the effects PredatorSense advertises, **by observed
behaviour**; there is no documented mapping, and `Shifting` is the least
certain of them.

| Mode | Observed | Name |
|---|---|---|
| 1 | off | — |
| **2** | **static colour** | Static |
| 4 | smooth fade through pure colours | Breathing |
| 5 | whole board shifts colour at once, no lateral sweep | Neon |
| 6 | as 5, faster | Neon (fast) |
| 7 | lateral rainbow (factory default) | Wave |
| 8 | one segment lit dim, then a full-board flash, then another segment at random | Shifting *(tentative)* |
| 9 | circular, outside inward, darkening, colour drifting each cycle | Zoom |
| 10 | streak crossing left-to-right then back, board dark behind it | Meteor |
| 11 | two of the four segments lit at random, then off | Twinkling |
| 12 | static | variant of Static |
| 13–31 | nothing visible | — |

### 6.1 Speed and direction

| Byte | Field | Values |
|---|---|---|
| 3 | speed | `0`–`9`, rising monotonically |
| 4 | direction | `1` left→right · `2` right→left |

⚠️ **The direction encoding is the reverse of the convention used by Archer and
the Linuwu-Sense docs**, where `2` means left-to-right. Anything bridging the
two must translate, or the UI label ends up inverted.

Value `3` in byte 4 produced a trailing-comet variant rather than a third
direction. Not characterised.

### Performance-mode button (`0x65`) — partial

| Mode | Effect |
|---|---|
| 1 | static colour |
| 4 | breathing, then rainbow |
| 6 | off |
| **≥ 8** | ⚠️ coincided with fans starting and stopping. Probably reaches the performance profile, not just the LED. **Do not sweep this range blindly.** |

## 7. Zone bitmask (bytes 8–9) — verified exhaustively

**A bitmask of the low four bits.** Zones combine in a single write.

| Value | Observed |
|---|---|
| `0x0001` | first quarter (leftmost) |
| `0x0002` | second quarter |
| `0x0004` | third quarter |
| `0x0008` | fourth quarter (rightmost) |
| `0x0003` | **left half** — the test that proves it is a mask, not an index |
| `0x000F` | whole keyboard |
| `0xFFFF` | whole keyboard |
| `0x0100` | **no effect** — the high byte is ignored |

## 8. What does not work

| Path | Result |
|---|---|
| Per-zone colour over **WMI** (`SET_GAMING_RGB_KB`) | stored, read back faithfully, **not applied** |
| Effect mode over **WMI** (`set_kb_status`) | ignored |
| Brightness over **WMI** | ✅ genuinely applied |
| Per-zone buffer via report `0xA3` | ignored — `0xA4` wins. Loading four distinct colours and applying blue produced an all-blue keyboard |

The lid logo (`0x83`) lights up, but three consecutive writes of the *same*
colour produced green, then yellow, then red. It does not read the RGB bytes
the way the keyboard does. Undecoded.

## 9. Worked example — four zones, four colours

```
# select the keyboard, then paint each zone with its own mask
0xA2 = 21
0xA4 = 21 02 64 00 00 FF 00 00 01 00     # zone 1 red
0xA4 = 21 02 64 00 00 00 FF 00 02 00     # zone 2 green
0xA4 = 21 02 64 00 00 00 00 FF 04 00     # zone 3 blue
0xA4 = 21 02 64 00 00 FF FF FF 08 00     # zone 4 white
```

## 10. Competing writers

Three independent actors impose keyboard state on every boot. Any experiment
must silence them or the results are uninterpretable.

| Actor | When | What |
|---|---|---|
| EC / firmware | always | animates over a private channel; can reassert itself |
| `linuwu_sense` | at module load | restores `/etc/four_zone_kb_state` |
| `archer-daemon` | ~2 s after the login screen | restores `/etc/archer/settings.json` |

## 11. Method note

Two conclusions in this work were initially wrong, both for the same reason:
**no baseline was recorded before the first write.** A finding about the lid
logo had to be withdrawn entirely, and a mode value verified on the button LED
was wrongly assumed to hold for the keyboard, invalidating a whole round of
zone testing.

Everything above was re-derived with the keyboard, button LED and lid logo all
dark before each experiment, and with each observation labelled by the exact
parameter that produced it. If you extend this work, keep that discipline: the
failure mode of this hardware is *silent* no-ops, so "nothing changed" carries
almost no information unless the starting state is known.

## 12. Open questions

- `0x83` (lid logo) colour encoding.
- Byte 4 value `3`: a trailing-comet variant, not characterised.
- Reapplying lighting after suspend/resume — `acer_suspend`/`acer_resume` do
  not touch RGB.
