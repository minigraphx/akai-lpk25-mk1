# Structured `.syx` Import/Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `.syx` a peer file format of JSON for presets: export a `Preset` to send-program SysEx frames, import them back, wire it into the existing read/write commands by file extension, and add an offline `convert` command.

**Architecture:** A shared `protocol.split_sysex()` (moved from `cli._split_syx`) splits a blob into frames. `Preset.to_syx()/from_syx()` build/parse one `OP_SEND_PROGRAM` (`0x61`) frame per program. `Preset.save()/load()` pick `.syx` vs JSON by extension, so every command that reads/writes a preset file gains `.syx` for free. A new offline `convert` command runs `load`→`save` with no device.

**Tech Stack:** Python 3.9+, stdlib; existing `lpk25` package (`protocol`, `model`, `codec`, `transport.MockTransport`); `pytest` + `ruff`.

## Global Constraints

- Python **3.9+** — no 3.10+-only syntax. `from __future__ import annotations` is already in `model.py`, `protocol.py`, `cli.py`.
- `ruff` clean, **line length ≤ 100**. No unused imports (F401).
- **No new dependencies.** Stdlib only.
- **No changes to `device.py`.** No hardware in tests — use `MockTransport` or pure calls.
- `model.py` may `from . import protocol` — this introduces **no import cycle** (`protocol` imports only stdlib).
- The `.syx` frame for a program is `protocol.build_send_program(slot, raw[1:], cfg)` → `F0 47 7F 76 61 <len> <slot> <raw[1:]> F7`; its parsed `frame.data` equals the full 13-byte program payload (byte 0 = slot).
- Run the suite with `.venv/bin/python -m pytest -q` and lint with `.venv/bin/python -m ruff check src/ tests/`.

---

### Task 1: `protocol.split_sysex()` (move from `cli._split_syx`)

**Files:**
- Modify: `src/lpk25/protocol.py` (add `split_sysex`)
- Modify: `src/lpk25/cli.py` (remove `_split_syx`; `cmd_raw_send` uses `protocol.split_sysex`)
- Test: `tests/test_protocol.py`

**Interfaces:**
- Produces: `protocol.split_sysex(blob: bytes) -> list[bytes]` — list of complete `F0…F7` frames; bytes outside any `F0…F7` run are dropped.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_protocol.py` (it already imports the package; if `protocol` is not imported there, add `from lpk25 import protocol` at the top):

```python
def test_split_sysex_multiple_frames():
    f1 = bytes([0xF0, 0x47, 0x01, 0xF7])
    f2 = bytes([0xF0, 0x47, 0x02, 0x03, 0xF7])
    assert protocol.split_sysex(f1 + f2) == [f1, f2]


def test_split_sysex_drops_bytes_between_frames():
    f1 = bytes([0xF0, 0x01, 0xF7])
    f2 = bytes([0xF0, 0x02, 0xF7])
    assert protocol.split_sysex(f1 + bytes([0xAA, 0xAA]) + f2) == [f1, f2]


def test_split_sysex_empty():
    assert protocol.split_sysex(b"") == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_protocol.py -k split_sysex -q`
Expected: FAIL with `AttributeError: module 'lpk25.protocol' has no attribute 'split_sysex'`

- [ ] **Step 3: Add `split_sysex` to `protocol.py`**

Add to `src/lpk25/protocol.py` (e.g. near the end, after `parse_frame`):

```python
def split_sysex(blob: bytes) -> list[bytes]:
    """Split a byte blob into complete ``F0 … F7`` SysEx frames.

    Bytes that fall outside an ``F0``-started, ``F7``-terminated run are dropped."""
    frames: list[bytes] = []
    cur = bytearray()
    for b in blob:
        if b == SYSEX_START:
            cur = bytearray([b])
        elif b == SYSEX_END and cur:
            cur.append(b)
            frames.append(bytes(cur))
            cur = bytearray()
        elif cur:
            cur.append(b)
    return frames
```

- [ ] **Step 4: Update `cli.py` to use it; remove the old helper**

In `src/lpk25/cli.py`:
1. Delete the entire `_split_syx` function (the `def _split_syx(blob: bytes) -> list[bytes]:` block).
2. In `cmd_raw_send`, change `frames = _split_syx(blob)` to `frames = protocol.split_sysex(blob)`. (`cli.py` already imports `protocol` via `from . import __version__, codec, library, protocol, render`.)

- [ ] **Step 5: Run the tests + full suite + lint**

Run: `.venv/bin/python -m pytest tests/test_protocol.py -k split_sysex -q` → PASS (3 passed)
Run: `.venv/bin/python -m pytest -q` → all pass (raw-send still works; `_split_syx` had no test but is now `protocol.split_sysex`)
Run: `.venv/bin/python -m ruff check src/ tests/` → clean (no F401 from the removed helper)

- [ ] **Step 6: Commit**

```bash
cd /home/andreas-schmidt/dev/akai-lpk25-mk1
git add src/lpk25/protocol.py src/lpk25/cli.py tests/test_protocol.py
git commit -m "Move SysEx frame splitter to protocol.split_sysex()"
```

---

### Task 2: `Preset.to_syx()` / `from_syx()` + extension-aware `save`/`load`

**Files:**
- Modify: `src/lpk25/model.py` (import `protocol`; add `to_syx`/`from_syx`; extension detection in `save`/`load`)
- Test: `tests/test_model.py`

**Interfaces:**
- Consumes: `protocol.split_sysex`, `protocol.parse_frame`, `protocol.build_send_program`, `protocol.ProtocolConfig`, `protocol.MODEL_LPK25_MK1`, `protocol.MANUFACTURER_AKAI`, `protocol.OP_SEND_PROGRAM`, `protocol.ProtocolError`; `Program.from_payload`.
- Produces: `Preset.to_syx() -> bytes`; `Preset.from_syx(blob: bytes) -> Preset` (classmethod); `Preset.save(path)`/`Preset.load(path)` now write/read `.syx` when the path ends in `.syx`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_model.py`. Ensure the top of the file imports what these need — add `import pytest`, `from lpk25 import protocol`, and `from lpk25.model import Preset, Program` if not already present:

```python
def _bank():
    return Preset(
        programs=[
            Program.from_payload(s, bytes([s, s, 4, 12, 0, 0, 5, 0, 0, 3, 0, 120, 0]))
            for s in (1, 2, 3, 4)
        ],
        device_model=0x76,
    )


def test_to_syx_one_frame_per_program():
    frames = protocol.split_sysex(_bank().to_syx())
    assert len(frames) == 4
    f = protocol.parse_frame(frames[0])
    assert f.manufacturer == 0x47 and f.model == 0x76
    assert f.opcode == protocol.OP_SEND_PROGRAM
    assert f.data[0] == 1 and len(f.data) == 13   # slot echo + full 13-byte payload


def test_syx_round_trips():
    p = _bank()
    q = Preset.from_syx(p.to_syx())
    assert [x.slot for x in q.programs] == [1, 2, 3, 4]
    assert [x.raw for x in q.programs] == [x.raw for x in p.programs]


def test_from_syx_skips_non_program_frames():
    stray = bytes([0xF0, 0x7E, 0x7F, 0x06, 0x02, 0xF7])   # a device-inquiry-style frame
    q = Preset.from_syx(stray + _bank().to_syx())
    assert len(q.programs) == 4


def test_from_syx_no_frames_raises():
    with pytest.raises(ValueError):
        Preset.from_syx(bytes([0xF0, 0x7E, 0x7F, 0x06, 0x02, 0xF7]))


def test_save_load_syx_round_trip(tmp_path):
    p = _bank()
    path = str(tmp_path / "bank.syx")
    p.save(path)
    q = Preset.load(path)
    assert [x.raw for x in q.programs] == [x.raw for x in p.programs]


def test_save_load_json_still_works(tmp_path):
    p = _bank()
    path = str(tmp_path / "bank.json")
    p.save(path)
    q = Preset.load(path)
    assert [x.raw for x in q.programs] == [x.raw for x in p.programs]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_model.py -k "syx" -q`
Expected: FAIL with `AttributeError: 'Preset' object has no attribute 'to_syx'` (or `from_syx`)

- [ ] **Step 3: Import `protocol` in `model.py`**

In `src/lpk25/model.py`, change the import line `from . import codec` to:

```python
from . import codec, protocol
```

- [ ] **Step 4: Add `to_syx`/`from_syx` to `Preset`**

In `src/lpk25/model.py`, add these two methods to the `Preset` class (e.g. after `from_json`):

```python
    def to_syx(self) -> bytes:
        """Serialise the preset as send-program SysEx frames (one per program)."""
        cfg = protocol.ProtocolConfig(model=self.device_model or protocol.MODEL_LPK25_MK1)
        out = bytearray()
        for p in self.programs:
            out += protocol.build_send_program(p.slot, p.raw[1:], cfg)
        return bytes(out)

    @classmethod
    def from_syx(cls, blob: bytes) -> Preset:
        """Parse send-program SysEx frames back into a preset.

        Ignores frames that are not Akai LPK25 send-program frames; raises
        ValueError if no program frames are found."""
        programs: list[Program] = []
        model = None
        for frame in protocol.split_sysex(blob):
            try:
                f = protocol.parse_frame(frame)
            except protocol.ProtocolError:
                continue
            if f.manufacturer != protocol.MANUFACTURER_AKAI:
                continue
            if f.opcode != protocol.OP_SEND_PROGRAM:
                continue
            model = f.model
            programs.append(Program.from_payload(f.data[0], bytes(f.data)))
        if not programs:
            raise ValueError("no LPK25 send-program frames found in .syx data")
        return cls(programs=programs, device_model=model)
```

- [ ] **Step 5: Make `save`/`load` detect the `.syx` extension**

Replace the existing `Preset.save` and `Preset.load` in `src/lpk25/model.py` with:

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

- [ ] **Step 6: Run tests + full suite + lint**

Run: `.venv/bin/python -m pytest tests/test_model.py -k "syx or save_load" -q` → PASS (6 passed)
Run: `.venv/bin/python -m pytest -q` → all pass (existing JSON save/load callers — `set`/`load`/`backup`/`preset` — still work)
Run: `.venv/bin/python -m ruff check src/ tests/` → clean

- [ ] **Step 7: Commit**

```bash
git add src/lpk25/model.py tests/test_model.py
git commit -m "Add Preset.to_syx/from_syx and .syx extension detection in save/load"
```

---

### Task 3: CLI — `.syx` output for `dump`/`get`, `convert` command, docs

**Files:**
- Modify: `src/lpk25/cli.py` (`cmd_dump`/`cmd_get` use `Preset.save`; add `cmd_convert` + subparser)
- Modify: `README.md`, `docs/feature-list.md`
- Test: `tests/test_cli_daily_driver.py` (append)

**Interfaces:**
- Consumes: `Preset.load`/`Preset.save` (Task 2, extension-aware); `_make_device`; `dev.dump()`, `dev.get_program(slot)`, `dev.load(preset)`.
- Produces: `cmd_convert(args) -> int`; a `convert` subcommand; `dump`/`get` write `.syx` when `-o` ends in `.syx`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cli_daily_driver.py` (reuse the existing `run(argv, transport)` helper and `codec`/`MockTransport` imports; add `from lpk25.model import Preset` if not already imported):

```python
def test_dump_syx_round_trips_to_device(tmp_path):
    tr = MockTransport()
    run(["--mock", "edit", "1", "--channel", "6"], tr)
    syx = str(tmp_path / "bank.syx")
    assert run(["--mock", "dump", "-o", syx], tr) == 0
    run(["--mock", "edit", "1", "--channel", "1"], tr)        # change it
    assert run(["--mock", "load", syx], tr) == 0              # load the .syx back
    assert codec.decode_program(tr.programs[1])["midi_channel"] == 6


def test_get_set_syx(tmp_path):
    tr = MockTransport()
    run(["--mock", "edit", "2", "--tempo", "150"], tr)
    syx = str(tmp_path / "p2.syx")
    assert run(["--mock", "get", "2", "-o", syx], tr) == 0
    run(["--mock", "edit", "2", "--tempo", "120"], tr)
    assert run(["--mock", "set", "2", syx], tr) == 0
    assert codec.decode_program(tr.programs[2])["tempo"] == 150


def test_convert_json_syx_json(tmp_path):
    tr = MockTransport()
    run(["--mock", "edit", "1", "--channel", "9"], tr)
    j = str(tmp_path / "b.json")
    s = str(tmp_path / "b.syx")
    j2 = str(tmp_path / "b2.json")
    run(["--mock", "dump", "-o", j], tr)
    assert run(["--mock", "convert", j, s], tr) == 0
    assert run(["--mock", "convert", s, j2], tr) == 0
    a = Preset.load(j)
    b = Preset.load(j2)
    assert [p.raw for p in a.programs] == [p.raw for p in b.programs]


def test_convert_same_path_errors(tmp_path):
    tr = MockTransport()
    f = str(tmp_path / "x.json")
    run(["--mock", "dump", "-o", f], tr)
    assert run(["--mock", "convert", f, f], tr) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_cli_daily_driver.py -k "syx or convert" -q`
Expected: FAIL — `convert` is an invalid choice; the `dump -o *.syx` test fails only if Task 2 isn't applied (it is), so the convert tests are the primary RED.

- [ ] **Step 3: Refactor `cmd_dump` and `cmd_get` to use `Preset.save`**

In `src/lpk25/cli.py`, replace `cmd_dump` with:

```python
def cmd_dump(args: argparse.Namespace) -> int:
    dev = _make_device(args)
    preset = dev.dump()
    if args.output:
        preset.save(args.output)
        print(f"Wrote {len(preset.programs)} program(s) to {args.output}")
    else:
        print(preset.to_json())
    _warn_unverified()
    return 0
```

and replace `cmd_get` with:

```python
def cmd_get(args: argparse.Namespace) -> int:
    dev = _make_device(args)
    program = dev.get_program(args.slot)
    preset = Preset(programs=[program], device_model=dev.config.model)
    if args.output:
        preset.save(args.output)
        print(f"Wrote program {args.slot} to {args.output}")
    else:
        print(preset.to_json())
    _warn_unverified()
    return 0
```

- [ ] **Step 4: Add `cmd_convert`**

In `src/lpk25/cli.py`, add near the other command functions (e.g. after `cmd_load`):

```python
def cmd_convert(args: argparse.Namespace) -> int:
    import os

    if os.path.abspath(args.src) == os.path.abspath(args.dst):
        _eprint("in and out are the same file")
        return 2
    preset = Preset.load(args.src)
    preset.save(args.dst)
    print(f"Converted {len(preset.programs)} program(s): {args.src} -> {args.dst}")
    return 0
```

- [ ] **Step 5: Register the `convert` subparser**

In `build_parser()`, add after the `load` subparser block (`ld.set_defaults(func=cmd_load)`):

```python
    cv = sub.add_parser("convert", help="convert a preset between .json and .syx (offline, no device)")
    cv.add_argument("src", help="input file (.json or .syx)")
    cv.add_argument("dst", help="output file (.json or .syx)")
    cv.set_defaults(func=cmd_convert)
```

- [ ] **Step 6: Run the new tests + full suite + lint**

Run: `.venv/bin/python -m pytest tests/test_cli_daily_driver.py -k "syx or convert" -q` → PASS (4 passed)
Run: `.venv/bin/python -m pytest -q` → all pass
Run: `.venv/bin/python -m ruff check src/ tests/` → clean

- [ ] **Step 7: Update docs**

In `README.md`, add to the usage code block (after the `copy` line):

```
lpk25 convert <in> <out>                                .json <-> .syx (offline)
```

and add a sentence under the usage block:

> Any command that reads or writes a preset file accepts `.syx` as well as
> `.json` — the format is chosen by the file extension (e.g. `dump -o bank.syx`,
> `load bank.syx`). `.syx` files are standard send-program SysEx, replayable by
> any MIDI tool.

In `docs/feature-list.md`, change the `.syx` row in the "File operations" table:

```
| `.syx` import/export (raw, interoperable) | — | ⬜ (`raw-send` exists; structured `.syx` export ⬜) |
```

to:

```
| `.syx` import/export (structured, interoperable) | — | ✅ (`convert`; `.syx` extension in get/dump/set/load) |
```

- [ ] **Step 8: Final suite + lint, then commit**

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check src/ tests/
git add src/lpk25/cli.py tests/test_cli_daily_driver.py README.md docs/feature-list.md
git commit -m "Add 'lpk25 convert' and .syx output for dump/get; document .syx format"
```

---

## Self-Review

**Spec coverage:**
- `Preset.to_syx()`/`from_syx()` (send-program frames, one per program) → Task 2. ✅
- `.syx` extension detection in `Preset.save()/load()` → Task 2. ✅
- `dump`/`get` write `.syx`; `set`/`load` read `.syx` → Task 3 (dump/get refactor) + Task 2 (set/load already use `Preset.load`). ✅
- Offline `convert <in> <out>`, same-path → rc 2 → Task 3. ✅
- Import leniency (skip non-program frames; error if none) → Task 2 (`from_syx`, `test_from_syx_skips_non_program_frames`, `test_from_syx_no_frames_raises`). ✅
- Move `_split_syx` → `protocol.split_sysex` → Task 1. ✅
- Docs (README + feature-list) → Task 3 Step 7. ✅

**Placeholder scan:** No TBD/TODO; every code step shows complete code. ✅

**Type consistency:** `protocol.split_sysex(blob) -> list[bytes]` defined in Task 1 and used by `from_syx` in Task 2. `Preset.to_syx() -> bytes` / `from_syx(blob) -> Preset` defined in Task 2 and used by `save`/`load` and (via `Preset.save`/`Preset.load`) by Task 3's `cmd_dump`/`cmd_get`/`cmd_convert`. `frame.data` (from `protocol.parse_frame`) is the full program payload; `Program.from_payload(f.data[0], bytes(f.data))` matches `Program.from_payload(slot, payload)`. `Preset` is already imported at the top of `cli.py`. ✅
