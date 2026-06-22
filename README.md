# lpk25 — Akai LPK25 mk1 editor (macOS / Linux)

A cross-platform program editor and SysEx library for the **Akai LPK25 mk1**.
The official editor only runs on Windows and legacy macOS; this project brings
program editing to modern macOS and Linux.

> **Project status: early / Phase 0.** The mk1's SysEx protocol is not publicly
> documented. This release ships the library, CLI, and a *provisional* protocol
> derived from the closely-related Akai LPD8 mk1. The next step is confirming it
> against real hardware — see **Help reverse-engineer** below. Until then,
> decoded program *values* may be wrong, but raw bytes and round-trip backups
> are exact and safe.

## Features

- Read all 4 programs from the device and save as JSON.
- Edit programs as JSON and write them back, with automatic backup and
  read-back verification.
- Back up / restore the whole device.
- Discovery tools: device inquiry, model-byte probing, raw MIDI capture, and a
  live MIDI monitor.
- A clean Python library (`lpk25`) that a future GUI can build on.

## Install

Requires Python 3.9+.

```bash
# Linux: install ALSA dev headers first so python-rtmidi can build
sudo apt-get install -y libasound2-dev   # Debian/Ubuntu

pip install -e '.[midi]'        # editable install with the MIDI backend
```

The pure-Python core (`protocol`, `codec`, `model`) imports without the `[midi]`
extra, which is handy for tests and offline use.

## Usage

```bash
lpk25 ports                 # list MIDI ports (auto-detects "LPK25")
lpk25 identify              # device inquiry + probe for the model byte
lpk25 dump -o my-presets.json
lpk25 get 1 -o prog1.json
lpk25 set 1 prog1.json      # auto-backup + verify
lpk25 load my-presets.json  # write all programs
lpk25 backup                # timestamped backup into ./backups/
lpk25 restore backups/lpk25-backup-XX…json
lpk25 monitor               # print live MIDI as you play (behavioural oracle)
```

Try the CLI with no hardware using the built-in fake device:

```bash
lpk25 --mock dump
```

If the model byte differs from the default guess, pass it explicitly once
`identify` finds it:

```bash
lpk25 --model 0x77 dump
```

## Help reverse-engineer the mk1 protocol

Because there's no editor to capture from, we verify the protocol directly
against the device. If you have an LPK25 mk1, this is the most valuable thing you
can contribute:

1. `lpk25 identify` — note which model byte (if any) responds, and the device
   inquiry output.
2. `lpk25 raw-recv -o capture.syx --seconds 20` while pressing the device's
   buttons (octave up/down, arp on/off, latch, tap tempo) — share the printed
   bytes.
3. Once a model responds, `lpk25 --model 0xNN dump -o dump.json` and share it.

These let us confirm the framing, the model byte, the program length, and then
map each field. See `docs/protocol.md` for current status and method, and
`docs/superpowers/specs/` for the full design.

## Development

```bash
pip install -e '.[dev]'
pytest          # unit tests run without hardware (codec/protocol/model + mock device)
ruff check .
```

## License

MIT — see `LICENSE`. Built on clean-room protocol notes; not affiliated with Akai.
