# LPK25 mk1 — Structured `.syx` Import/Export — Design

- **Date:** 2026-06-23
- **Status:** Approved (decided autonomously while the user was offline; user to
  review). Ready for implementation plan.
- **Author:** drafted via the brainstorming method; design decisions made and
  documented by the assistant per the user's delegation.
- **Builds on:** the confirmed protocol (`build_send_program`, model `0x76`),
  the `Preset`/`Program` model, and the existing `raw-send`/`raw-recv` commands.

## Problem

Presets can be saved/loaded as the project's JSON format, but not as a standard
`.syx` (System Exclusive) file. `.syx` is the lingua franca of MIDI librarians:
a structured `.syx` export makes LPK25 presets interoperable with other tools
and replayable onto any LPK25 mk1, and a `.syx` import lets a file produced
elsewhere be inspected/edited as JSON. The low-level `raw-send`/`raw-recv` move
opaque bytes; this feature adds a *typed* `.syx` that maps to/from the program
model.

## Goal

Make `.syx` a peer file format of JSON for presets:
- Export a `Preset` to `.syx` (send-program frames, one per program).
- Import a `.syx` back into a `Preset`.
- Wire it into the existing read/write commands by file extension, plus a
  hardware-free offline `convert` command.

## Non-goals (YAGNI)

- A new on-wire protocol — reuses the confirmed send-program frame.
- Globals in `.syx` (the device has none confirmed; `globals_raw` stays
  JSON-only).
- `.syx` to stdout (binary); `dump`/`get` without `-o` stay JSON-on-stdout.
- New `export`/`import` device commands (extension detection covers it).

## Decisions (locked)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Frame type in `.syx` | **send-program** (`OP_SEND_PROGRAM` = `0x61`), one per program | it's the write payload — replayable to a device by any tool; "load these presets" is the use case. |
| CLI surface | extension detection in `Preset.save()/load()` + offline `convert` | single change point; `.syx` works everywhere JSON does; `convert` covers offline interop with no device. |
| Import leniency | collect `0x61` Akai frames, ignore others, error if none | tolerant of files from other tools; still fails loudly on a non-LPK25 file. |
| Model byte on export | `preset.device_model` or default `0x76` | matches the confirmed model; round-trips. |
| Cleanup | move `_split_syx` → `protocol.split_sysex()`; `cmd_dump`/`cmd_get` use `Preset.save()` | the splitter belongs in `protocol`; DRY + enables `.syx` output. |

## The `.syx` format

For each `Program` in the preset, one send-program frame:

```
F0 47 7F 76 61 <len_hi> <len_lo> <slot> <raw[1:] …> F7
```

- `47`=Akai, `7F`=broadcast, `76`=model, `61`=send-program; `<len>` is the
  16-bit payload length as two 7-bit bytes; payload = `[slot] + raw[1:]` (i.e.
  the full 13-byte program payload with byte 0 = the slot).
- A 4-program bank is four such frames concatenated; a single-program export is
  one frame. The file is a faithful "write this onto the device" stream.

## Architecture / components

```
src/lpk25/
  protocol.py  + split_sysex(blob) -> list[bytes]   (moved from cli._split_syx)
  model.py     + Preset.to_syx() / Preset.from_syx();
               Preset.save()/load() detect the .syx extension
  cli.py       _split_syx -> protocol.split_sysex (raw-send);
               cmd_dump/cmd_get use Preset.save(); + cmd_convert + subparser
  device.py    unchanged
```

### `protocol.split_sysex(blob: bytes) -> list[bytes]`

Splits a byte blob into complete `F0 … F7` frames (the current `cli._split_syx`
logic, verbatim), so both `raw-send` and the model layer share one splitter.
`cli._split_syx` is removed and its one caller (`cmd_raw_send`) updated.

### `model.Preset.to_syx()` / `from_syx()`

```python
def to_syx(self) -> bytes:
    cfg = protocol.ProtocolConfig(model=self.device_model or protocol.MODEL_LPK25_MK1)
    out = bytearray()
    for p in self.programs:
        out += protocol.build_send_program(p.slot, p.raw[1:], cfg)
    return bytes(out)

@classmethod
def from_syx(cls, blob: bytes) -> Preset:
    programs, model = [], None
    for frame in protocol.split_sysex(blob):
        try:
            f = protocol.parse_frame(frame)
        except protocol.ProtocolError:
            continue
        if f.manufacturer != protocol.MANUFACTURER_AKAI or f.opcode != protocol.OP_SEND_PROGRAM:
            continue
        model = f.model
        slot = f.data[0]
        programs.append(Program.from_payload(slot, bytes(f.data)))
    if not programs:
        raise ValueError("no LPK25 send-program frames found in .syx data")
    return cls(programs=programs, device_model=model)
```

(`f.data` for a send-program frame is `[slot] + raw[1:]`, which equals the full
program payload with byte 0 = slot — so `Program.from_payload(slot, f.data)`
reconstructs the program exactly.)

### `Preset.save()/load()` extension detection

```python
def save(self, path: str) -> None:
    if path.lower().endswith(".syx"):
        with open(path, "wb") as fh:
            fh.write(self.to_syx())
    else:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(self.to_json())

@classmethod
def load(cls, path: str) -> Preset:
    if path.lower().endswith(".syx"):
        with open(path, "rb") as fh:
            return cls.from_syx(fh.read())
    with open(path, encoding="utf-8") as fh:
        return cls.from_json(fh.read())
```

### CLI

- `cmd_dump` / `cmd_get`: when `-o` is given, call `preset.save(args.output)`
  (which now picks JSON or `.syx` by extension) instead of manually writing
  `to_json()`. Without `-o`, unchanged (JSON to stdout).
- `cmd_set` / `cmd_load`: already call `Preset.load(...)` → `.syx` input works
  automatically.
- New **`cmd_convert`**: `lpk25 convert <in> <out>` — `Preset.load(in)` then
  `preset.save(out)`. Pure, no device. Refuses if `in` and `out` resolve to the
  same path. Prints `Converted N program(s): <in> -> <out>`.

## Data flow

- export: `dev.dump()`/`get` → `Preset` → `Preset.save("x.syx")` → `to_syx()` →
  send-program frames.
- import: `Preset.load("x.syx")` → `from_syx()` → `Preset` → `set`/`load` writes
  it to the device.
- convert: `Preset.load(in)` → `Preset.save(out)`, no device.

## Error handling

| Case | Behavior |
|------|----------|
| `.syx` with no LPK25 send-program frames | `from_syx` raises `ValueError`; CLI prints `error: …`, rc 1 |
| malformed frame inside a `.syx` | skipped (only well-formed `0x61` Akai frames are used) |
| `convert` with `in` == `out` (same path) | error `in and out are the same file`, rc 2 |
| unreadable/missing input file | `OSError` → CLI `error: …`, rc 1 |
| non-`.syx` extension | treated as JSON (current behavior) |

## Testing (no hardware)

- **protocol:** `split_sysex` splits multi-frame blobs, ignores stray bytes
  between frames, returns `[]` for empty; a `raw-send` regression still passes.
- **model:** `to_syx` emits one `0x61` frame per program with correct
  manufacturer/model/slot/payload; `from_syx` round-trips
  (`from_syx(to_syx(preset))` equals the original raw payloads and slots);
  `from_syx` on a blob with no program frames raises `ValueError`; `from_syx`
  skips a stray non-program SysEx frame mixed in; `save`/`load` round-trip a
  preset through a `.syx` temp file and through a `.json` temp file (extension
  detection).
- **cli (MockTransport):** `dump -o bank.syx` then `load bank.syx` round-trips
  onto the mock; `get 1 -o p1.syx` then `set 1 p1.syx`; `convert` JSON→syx→JSON
  preserves program bytes; `convert` same-path → rc 2.

## Documentation

- README usage: note `.syx` works wherever a file is read/written, and add
  `lpk25 convert <in> <out>`.
- `docs/feature-list.md`: flip the `.syx` import/export row to ✅.
