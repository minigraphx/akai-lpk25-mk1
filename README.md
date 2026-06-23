# lpk25 — Akai LPK25 mk1 editor (macOS / Linux)

![Akai LPK25 mk1](docs/images/lpk25-mk1-front.jpg)

A cross-platform program editor and SysEx library for the **Akai LPK25 mk1**.
The official editor only runs on Windows and legacy macOS; this project brings
program editing to modern macOS and Linux.

> **Project status: protocol confirmed against real hardware.** The mk1's SysEx
> protocol isn't publicly documented, so it was reverse-engineered directly
> against a real LPK25 mk1. The model byte (`0x76`), framing, opcodes, and **all
> 13 program bytes are verified**. The CLI can read, edit, back up, and write
> programs safely — every write
> auto-backs-up and read-back-verifies. See `docs/protocol.md` for the full byte map.

## Features

- **Read & display** all 4 programs — `show` prints a human-readable table, or
  dump to JSON.
- **Edit from the command line** — `edit <slot> --channel 5 --octave -1 …` patches
  individual parameters, with automatic backup and read-back verification.
- **Named preset library** — save a config under a name and apply it to any slot.
- **Back up / restore** the whole device (JSON, plus raw `.syx` replay).
- **Discovery tools** — device inquiry, model-byte probing, raw MIDI capture, and a
  live MIDI monitor (the behavioural oracle used to map the protocol).
- A clean, fully unit-tested Python library (`lpk25`) that a future GUI can build on.

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
lpk25 edit <slot> [--channel N --octave N --transpose N --arp on/off
                   --arp-mode M --time-div D --clock int/ext --latch on/off
                   --tempo N --taps N --arp-octave N]   change fields on a slot
lpk25 show [slot] [--json]                              human-readable state
lpk25 preset save <name> [--from-slot N] [--force]      save a slot as a preset
lpk25 preset apply <name> <slot>                        write a preset onto a slot
lpk25 preset list                                       list saved presets
lpk25 copy <src> <dst...> [--yes]                       copy a slot onto others
```

Presets live in `$LPK25_PRESET_DIR` (default `~/.config/lpk25/presets`).

Try the CLI with no hardware using the built-in fake device:

```bash
lpk25 --mock dump
```

The model byte is confirmed as `0x76` (the default). If a future firmware
revision ever differs, override it explicitly:

```bash
lpk25 --model 0x77 dump
```

## Protocol status

The mk1 protocol was reverse-engineered against a real LPK25 mk1 and is fully
documented in [`docs/protocol.md`](docs/protocol.md): the model byte, frame
structure, opcodes, and the complete 13-byte program map — **all 13 program
bytes are hardware-confirmed**. The mapping was done with the `diff` tool (change
one setting on the device, dump, and see which byte moved) and the `monitor`
behavioural oracle (write a value, play a key, observe the note channel/number).

If you have an LPK25 mk1 and want to verify on your own unit, `lpk25 identify`,
`lpk25 diff`, and `lpk25 monitor` are the tools that drove the mapping. See
`docs/discovery-checklist.md` for the method and `docs/superpowers/specs/` for
the design.

## Development

```bash
pip install -e '.[dev]'
pytest          # unit tests run without hardware (codec/protocol/model + mock device)
ruff check .
```

## License

MIT — see `LICENSE`. Built on clean-room protocol notes; not affiliated with Akai.
