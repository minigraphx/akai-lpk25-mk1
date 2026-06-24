# Interactive TUI Editor (lpk25 tui) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `lpk25 tui`, a stdlib-curses interactive editor for the four LPK25 programs with in-place editing, per-slot write (backup + verify), activate, library load/save, and a toggleable decoded-MIDI monitor pane.

**Architecture:** A pure, curses-free `EditorController` holds all edit state and logic; a pure `dispatch()` maps key codes to controller/ui actions through an injected `io` (prompt/choose/confirm); a thin `view`/`app` curses layer only draws and reads keys. Everything except the raw curses drawing is unit-tested offline against `Device(MockTransport())`.

**Tech Stack:** Python ≥3.9, stdlib `curses`, `pytest`, `ruff`. Reuses `device`, `codec`, `model`, `library`, `render`, `mididecode`.

## Global Constraints

- Python ≥ 3.9 (`from __future__ import annotations` in every module; no 3.10+ syntax).
- No new runtime dependencies — `curses` is stdlib; import it lazily in `cli.cmd_tui` so other commands never import it.
- `ruff check .` must pass; line length and style match the existing `src/lpk25/` code.
- Every device write goes through `Device.send_program` (auto-backup + read-back verify) — never bypass it.
- Value stepping/validation derives from `codec.LPK25_MK1_FIELDS` — do not hard-code field ranges or enum tables.
- Editable column order = `render._COLUMNS` minus the synthetic `"slot"` (reuse, don't duplicate).
- Commit messages end with the repo's two trailer lines (Co-Authored-By + Claude-Session), as in recent commits.

---

### Task 1: TUI package + read-only controller model

**Files:**
- Create: `src/lpk25/tui/__init__.py`
- Create: `src/lpk25/tui/controller.py`
- Test: `tests/test_tui_controller.py`

**Interfaces:**
- Consumes: `codec.LPK25_MK1_FIELDS`, `render._COLUMNS`, `model.Program`/`Preset`, `device.Device`, `transport.MockTransport`.
- Produces:
  - `tui.controller.FIELD_ORDER: list[codec.Field]`
  - `tui.controller.RowView(slot:int, values:dict, dirty:bool, active:bool)`
  - `EditorController(dev, preset: Preset, active_slot: int|None)` with `.slot_idx`, `.field_idx`, `.rows() -> list[RowView]`, `.focused_field() -> codec.Field`, `.header() -> str`, `.any_dirty() -> bool`, `.move(d_slot:int, d_field:int)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_tui_controller.py
import pytest

from lpk25.device import Device
from lpk25.transport import MockTransport
from lpk25.tui.controller import EditorController, FIELD_ORDER, RowView


def make_controller() -> EditorController:
    dev = Device(MockTransport(model=0x76), model=0x76)
    return EditorController(dev, dev.dump(), dev.get_active_program())


def test_rows_describe_four_programs():
    c = make_controller()
    rows = c.rows()
    assert [r.slot for r in rows] == [1, 2, 3, 4]
    assert all(isinstance(r, RowView) for r in rows)
    assert all(r.dirty is False for r in rows)        # nothing edited yet
    assert [r.active for r in rows] == [True, False, False, False]  # mock active = 1
    assert rows[0].values["midi_channel"] == 1        # decoded display value


def test_field_order_is_render_columns_without_slot():
    names = [f.name for f in FIELD_ORDER]
    assert "midi_channel" in names
    assert "slot" not in names
    assert len(names) == 11                            # all mapped editable fields


def test_move_clamps_to_grid():
    c = make_controller()
    c.move(-1, -1)                                     # already top-left
    assert (c.slot_idx, c.field_idx) == (0, 0)
    c.move(99, 99)                                     # past bottom-right
    assert c.slot_idx == 3
    assert c.field_idx == len(FIELD_ORDER) - 1


def test_header_names_focused_field_and_slot():
    c = make_controller()
    assert c.header().startswith("slot 1 · ")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_tui_controller.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'lpk25.tui'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/lpk25/tui/__init__.py
"""Interactive curses editor for the LPK25 mk1 (the `lpk25 tui` command)."""
```

```python
# src/lpk25/tui/controller.py
"""Pure (curses-free) state + logic for the TUI editor.

Holds an edited copy and an original copy of all four programs, a grid cursor,
and every edit/device/library action. The curses layer talks only to this
class, so the whole editor is exercised offline with Device(MockTransport()).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .. import codec, library, render
from ..model import Preset, Program

# Editable columns, in the same left-to-right order `show` prints them.
_BY_NAME = {f.name: f for f in codec.LPK25_MK1_FIELDS}
FIELD_ORDER: list[codec.Field] = [
    _BY_NAME[name] for name, _ in render._COLUMNS if name != "slot"
]


@dataclass
class RowView:
    slot: int
    values: dict[str, Any]
    dirty: bool
    active: bool


def _copy(programs: list[Program]) -> list[Program]:
    return [Program.from_payload(p.slot, p.raw) for p in programs]


class EditorController:
    def __init__(self, dev, preset: Preset, active_slot: int | None):
        self.dev = dev
        self._original: list[Program] = _copy(preset.programs)
        self._edited: list[Program] = _copy(preset.programs)
        self.active_slot = active_slot
        self.slot_idx = 0
        self.field_idx = 0

    # --- queries ---------------------------------------------------------
    def _slot_dirty(self, i: int) -> bool:
        return self._edited[i].to_payload() != self._original[i].to_payload()

    def any_dirty(self) -> bool:
        return any(self._slot_dirty(i) for i in range(len(self._edited)))

    def rows(self) -> list[RowView]:
        return [
            RowView(
                slot=p.slot,
                values=dict(p.values),
                dirty=self._slot_dirty(i),
                active=(p.slot == self.active_slot),
            )
            for i, p in enumerate(self._edited)
        ]

    def focused_field(self) -> codec.Field:
        return FIELD_ORDER[self.field_idx]

    def header(self) -> str:
        dirty = [self._edited[i].slot for i in range(len(self._edited)) if self._slot_dirty(i)]
        tag = f"  [* unsaved: {','.join(map(str, dirty))}]" if dirty else ""
        return f"slot {self._edited[self.slot_idx].slot} · {self.focused_field().name}{tag}"

    # --- navigation ------------------------------------------------------
    def move(self, d_slot: int, d_field: int) -> None:
        self.slot_idx = max(0, min(len(self._edited) - 1, self.slot_idx + d_slot))
        self.field_idx = max(0, min(len(FIELD_ORDER) - 1, self.field_idx + d_field))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_tui_controller.py -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/lpk25/tui/__init__.py src/lpk25/tui/controller.py tests/test_tui_controller.py
git commit -m "Add TUI EditorController read model (grid rows, cursor, header)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_018PaHHGKo9tFhdQSNWBxJk6"
```

---

### Task 2: Value editing — step, type-in, undo, dirty tracking

**Files:**
- Modify: `src/lpk25/tui/controller.py`
- Test: `tests/test_tui_controller.py`

**Interfaces:**
- Consumes: Task 1's `EditorController`, `codec.CodecError`.
- Produces: `EditorController.step(delta:int)`, `.set_value(text:str)` (raises `codec.CodecError`), `.undo_slot()`.

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_tui_controller.py
from lpk25 import codec


def _focus(c, field_name):
    c.field_idx = [f.name for f in FIELD_ORDER].index(field_name)


def test_step_int_clamps_within_bounds():
    c = make_controller()
    _focus(c, "keybed_octave")                 # lo=-4, hi=4, starts 0
    for _ in range(10):
        c.step(1)
    assert c.rows()[0].values["keybed_octave"] == 4
    for _ in range(20):
        c.step(-1)
    assert c.rows()[0].values["keybed_octave"] == -4


def test_step_enum_cycles():
    c = make_controller()
    _focus(c, "arp_mode")                       # up,down,inclusive,exclusive,order,random
    assert c.rows()[0].values["arp_mode"] == "up"
    c.step(1)
    assert c.rows()[0].values["arp_mode"] == "down"
    c.step(-1)
    assert c.rows()[0].values["arp_mode"] == "up"
    c.step(-1)                                  # wraps to last
    assert c.rows()[0].values["arp_mode"] == "random"


def test_step_bool_toggles_and_marks_dirty():
    c = make_controller()
    _focus(c, "arp_enabled")
    before = c.rows()[0].values["arp_enabled"]
    c.step(1)
    assert c.rows()[0].values["arp_enabled"] is (not before)
    assert c.rows()[0].dirty is True
    assert c.any_dirty() is True


def test_step_tempo_u14_clamps():
    c = make_controller()
    _focus(c, "tempo")                          # lo=30, hi=240
    for _ in range(500):
        c.step(1)
    assert c.rows()[0].values["tempo"] == 240


def test_set_value_numeric_and_validation():
    c = make_controller()
    _focus(c, "tempo")
    c.set_value("140")
    assert c.rows()[0].values["tempo"] == 140
    with pytest.raises(codec.CodecError):
        c.set_value("999")                      # out of range
    with pytest.raises(codec.CodecError):
        c.set_value("abc")                      # not a number
    _focus(c, "arp_mode")
    with pytest.raises(codec.CodecError):
        c.set_value("2")                        # enum is not type-in editable


def test_undo_slot_reverts():
    c = make_controller()
    _focus(c, "keybed_octave")
    c.step(1)
    assert c.rows()[0].dirty is True
    c.undo_slot()
    assert c.rows()[0].dirty is False
    assert c.rows()[0].values["keybed_octave"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_tui_controller.py -q`
Expected: FAIL — `AttributeError: 'EditorController' object has no attribute 'step'`.

- [ ] **Step 3: Write minimal implementation**

Append to `EditorController` in `src/lpk25/tui/controller.py`:

```python
    # --- editing ---------------------------------------------------------
    @staticmethod
    def _stepped(f: codec.Field, cur: Any, delta: int) -> Any:
        if f.kind == "bool":
            return not bool(cur)
        if f.kind == "enum":
            assert f.enum is not None
            codes = sorted(f.enum)
            rev = {v: k for k, v in f.enum.items()}
            code = rev.get(cur, cur if isinstance(cur, int) else codes[0])
            i = codes.index(code) if code in codes else 0
            return f.enum[codes[(i + delta) % len(codes)]]
        v = int(cur) + delta
        lo = f.lo if f.lo is not None else v
        hi = f.hi if f.hi is not None else v
        return max(lo, min(hi, v))

    def step(self, delta: int) -> None:
        f = self.focused_field()
        self._edited[self.slot_idx].values[f.name] = self._stepped(
            f, self._edited[self.slot_idx].values.get(f.name), delta
        )

    def set_value(self, text: str) -> None:
        f = self.focused_field()
        if f.kind in ("bool", "enum"):
            raise codec.CodecError(f"{f.name} is not a numeric field (use -/+)")
        try:
            v = int(text)
        except ValueError:
            raise codec.CodecError(f"{f.name}: not a number: {text!r}")
        prog = self._edited[self.slot_idx]
        codec.encode_program({f.name: v}, prog.raw)   # validates range; raises CodecError
        prog.values[f.name] = v

    def undo_slot(self) -> None:
        i = self.slot_idx
        self._edited[i] = Program.from_payload(self._original[i].slot, self._original[i].raw)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_tui_controller.py -q`
Expected: PASS (all Task 1 + Task 2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/lpk25/tui/controller.py tests/test_tui_controller.py
git commit -m "Add TUI value editing: step, type-in, undo, dirty tracking

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_018PaHHGKo9tFhdQSNWBxJk6"
```

---

### Task 3: Device actions — write, write-all, activate, reload

**Files:**
- Modify: `src/lpk25/tui/controller.py`
- Test: `tests/test_tui_controller.py`

**Interfaces:**
- Consumes: `Device.send_program`, `Device.activate`, `Device.dump`, `Device.get_active_program`, `device.WriteResult`.
- Produces: `EditorController.write_current() -> WriteResult`, `.write_all_dirty() -> list[WriteResult]`, `.activate_current() -> int|None`, `.reload()`.

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_tui_controller.py
def test_write_current_persists_and_clears_dirty():
    c = make_controller()
    _focus(c, "keybed_octave")
    c.step(1)
    assert c.rows()[0].dirty is True
    result = c.write_current()
    assert result.slot == 1 and result.verified is True
    assert c.rows()[0].dirty is False
    # the mock device now holds the new value
    assert c.dev.get_program(1).values["keybed_octave"] == 1


def test_write_all_dirty_writes_only_changed_slots():
    c = make_controller()
    _focus(c, "keybed_octave")
    c.step(1)                                   # slot 1 dirty
    c.move(2, 0)                                # to slot 3
    c.step(-1)                                  # slot 3 dirty
    results = c.write_all_dirty()
    assert sorted(r.slot for r in results) == [1, 3]
    assert c.any_dirty() is False


def test_activate_current_changes_active():
    c = make_controller()
    c.move(2, 0)                                # slot 3
    assert c.activate_current() == 3
    assert c.active_slot == 3
    assert c.rows()[2].active is True


def test_reload_discards_edits():
    c = make_controller()
    _focus(c, "keybed_octave")
    c.step(1)
    c.reload()
    assert c.any_dirty() is False
    assert c.rows()[0].values["keybed_octave"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_tui_controller.py -k "write or activate or reload" -q`
Expected: FAIL — `AttributeError: ... 'write_current'`.

- [ ] **Step 3: Write minimal implementation**

Append to `EditorController`:

```python
    # --- device actions --------------------------------------------------
    def write_current(self):
        i = self.slot_idx
        prog = self._edited[i]
        result = self.dev.send_program(prog)
        self._original[i] = Program.from_payload(prog.slot, prog.to_payload())
        return result

    def write_all_dirty(self):
        results = []
        for i, prog in enumerate(self._edited):
            if self._slot_dirty(i):
                results.append(self.dev.send_program(prog))
                self._original[i] = Program.from_payload(prog.slot, prog.to_payload())
        return results

    def activate_current(self) -> int | None:
        slot = self._edited[self.slot_idx].slot
        active = self.dev.activate(slot)
        self.active_slot = active if active is not None else slot
        return self.active_slot

    def reload(self) -> None:
        preset = self.dev.dump()
        self.active_slot = self.dev.get_active_program()
        self._original = _copy(preset.programs)
        self._edited = _copy(preset.programs)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_tui_controller.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/lpk25/tui/controller.py tests/test_tui_controller.py
git commit -m "Add TUI device actions: write, write-all, activate, reload

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_018PaHHGKo9tFhdQSNWBxJk6"
```

---

### Task 4: Library actions — preset and bank load/save

**Files:**
- Modify: `src/lpk25/tui/controller.py`
- Test: `tests/test_tui_controller.py`

**Interfaces:**
- Consumes: `library.save_preset/load_preset/save_bank/load_bank`, `model.Preset`, `Program.reslot`.
- Produces: `EditorController.save_preset(name, force=False) -> str`, `.load_preset_into_current(name)`, `.save_bank(name, force=False) -> str`, `.load_bank(name)`.

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_tui_controller.py
def test_preset_save_and_load_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("LPK25_PRESET_DIR", str(tmp_path))
    c = make_controller()
    _focus(c, "keybed_octave")
    c.step(1)                                   # slot 1 octave = 1
    c.save_preset("mylead")
    # change slot 2 to a different value, then load the preset onto it
    c.move(1, 0)
    c.load_preset_into_current("mylead")
    assert c.rows()[1].values["keybed_octave"] == 1
    assert c.rows()[1].slot == 2                # slot echo rewritten to target
    assert c.rows()[1].dirty is True


def test_bank_save_and_load_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("LPK25_BANK_DIR", str(tmp_path))
    c = make_controller()
    _focus(c, "tempo")
    c.set_value("150")                          # slot 1 tempo
    c.save_bank("set-a")
    c.reload()                                  # discard edits
    c.load_bank("set-a")
    assert c.rows()[0].values["tempo"] == 150
    assert [r.slot for r in c.rows()] == [1, 2, 3, 4]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_tui_controller.py -k "preset or bank" -q`
Expected: FAIL — `AttributeError: ... 'save_preset'`.

- [ ] **Step 3: Write minimal implementation**

Append to `EditorController`:

```python
    # --- library ---------------------------------------------------------
    def save_preset(self, name: str, force: bool = False) -> str:
        return library.save_preset(name, self._edited[self.slot_idx], force=force)

    def load_preset_into_current(self, name: str) -> None:
        prog = library.load_preset(name)
        i = self.slot_idx
        self._edited[i] = prog.reslot(self._edited[i].slot)

    def save_bank(self, name: str, force: bool = False) -> str:
        preset = Preset(programs=_copy(self._edited),
                        device_model=getattr(self.dev.config, "model", None))
        return library.save_bank(name, preset, force=force)

    def load_bank(self, name: str) -> None:
        preset = library.load_bank(name)
        for i, prog in enumerate(preset.programs[: len(self._edited)]):
            self._edited[i] = prog.reslot(self._edited[i].slot)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_tui_controller.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/lpk25/tui/controller.py tests/test_tui_controller.py
git commit -m "Add TUI library actions: preset and bank load/save

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_018PaHHGKo9tFhdQSNWBxJk6"
```

---

### Task 5: MIDI monitor reader

**Files:**
- Create: `src/lpk25/tui/monitor.py`
- Test: `tests/test_tui_monitor.py`

**Interfaces:**
- Consumes: `mididecode.decode_message`.
- Produces: `tui.monitor.MidiMonitor(transport, maxlen=200)` with `.available -> bool`, `._consume(frame: bytes)`, `.lines(n: int) -> list[str]`, `.start()`, `.stop()`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_tui_monitor.py
from lpk25.tui.monitor import MidiMonitor


class _FakeInput:
    """Transport-like object that yields queued frames from receive()."""
    def __init__(self, frames):
        self._frames = list(frames)

    def receive(self, timeout=0.1):
        return self._frames.pop(0) if self._frames else None


def test_consume_decodes_frames_into_lines():
    m = MidiMonitor(_FakeInput([]))
    m._consume(bytes([0x90, 60, 100]))          # Note On C4
    m._consume(bytes([0x80, 60, 0]))            # Note Off C4
    lines = m.lines(10)
    assert len(lines) == 2
    assert "Note On" in lines[0]
    assert "C4" in lines[0]


def test_ring_buffer_caps_at_maxlen():
    m = MidiMonitor(_FakeInput([]), maxlen=5)
    for n in range(20):
        m._consume(bytes([0x90, 60 + (n % 5), 100]))
    assert len(m.lines(100)) == 5               # only newest 5 kept


def test_available_false_without_receive():
    class NoInput:
        pass
    assert MidiMonitor(NoInput()).available is False
    assert MidiMonitor(_FakeInput([])).available is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_tui_monitor.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'lpk25.tui.monitor'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/lpk25/tui/monitor.py
"""Background MIDI input reader for the TUI monitor pane.

Runs a daemon thread that reads input frames from the transport, decodes each
with mididecode, and keeps the newest lines in a bounded ring buffer. Inert
when the transport exposes no input (offline / no [midi] extra)."""

from __future__ import annotations

import threading
from collections import deque

from .. import mididecode


class MidiMonitor:
    def __init__(self, transport, maxlen: int = 200):
        self._transport = transport
        self._lines: deque[str] = deque(maxlen=maxlen)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def available(self) -> bool:
        return callable(getattr(self._transport, "receive", None))

    def _consume(self, frame: bytes) -> None:
        if frame:
            self._lines.append(mididecode.decode_message(frame))

    def lines(self, n: int) -> list[str]:
        return list(self._lines)[-n:]

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                frame = self._transport.receive(timeout=0.1)
            except Exception:
                return
            self._consume(frame)

    def start(self) -> None:
        if not self.available or self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=0.5)
            self._thread = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_tui_monitor.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/lpk25/tui/monitor.py tests/test_tui_monitor.py
git commit -m "Add TUI MIDI monitor reader (decode + ring buffer + thread)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_018PaHHGKo9tFhdQSNWBxJk6"
```

---

### Task 6: Key dispatch (pure) + UI state + IO protocol

**Files:**
- Create: `src/lpk25/tui/app.py` (dispatch + UIState only in this task; curses loop added in Task 7)
- Test: `tests/test_tui_dispatch.py`

**Interfaces:**
- Consumes: `EditorController`, `library.list_preset_names/list_bank_names`, `library.LibraryError`, `curses` (constants only).
- Produces:
  - `tui.app.UIState(show_monitor=False, show_help=False, running=True)`
  - `tui.app.dispatch(key:int, controller, ui, io) -> str|None` where `io` has `.prompt(label)->str|None`, `.choose(title, options)->str|None`, `.confirm(msg)->bool`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_tui_dispatch.py
import curses

from lpk25.device import Device
from lpk25.transport import MockTransport
from lpk25.tui.controller import EditorController, FIELD_ORDER
from lpk25.tui.app import UIState, dispatch


def make():
    dev = Device(MockTransport(model=0x76), model=0x76)
    return EditorController(dev, dev.dump(), dev.get_active_program())


class FakeIO:
    """Scripted prompt/choose/confirm for dispatch tests."""
    def __init__(self, prompt=None, choose=None, confirm=True):
        self._prompt, self._choose, self._confirm = prompt, choose, confirm
        self.calls = []

    def prompt(self, label):
        self.calls.append(("prompt", label))
        return self._prompt

    def choose(self, title, options):
        self.calls.append(("choose", title, tuple(options)))
        return self._choose

    def confirm(self, msg):
        self.calls.append(("confirm", msg))
        return self._confirm


def test_arrows_move_cursor():
    c = make()
    ui = UIState()
    dispatch(curses.KEY_DOWN, c, ui, FakeIO())
    dispatch(curses.KEY_RIGHT, c, ui, FakeIO())
    assert (c.slot_idx, c.field_idx) == (1, 1)


def test_minus_plus_step_value():
    c = make()
    c.field_idx = [f.name for f in FIELD_ORDER].index("keybed_octave")
    dispatch(ord("+"), c, make_ui := UIState(), FakeIO())
    assert c.rows()[0].values["keybed_octave"] == 1
    dispatch(ord("-"), c, make_ui, FakeIO())
    assert c.rows()[0].values["keybed_octave"] == 0


def test_w_writes_current_slot():
    c = make()
    c.field_idx = [f.name for f in FIELD_ORDER].index("keybed_octave")
    dispatch(ord("+"), c, UIState(), FakeIO())
    msg = dispatch(ord("w"), c, UIState(), FakeIO())
    assert "slot 1" in msg
    assert c.any_dirty() is False


def test_a_activates_current_slot():
    c = make()
    dispatch(curses.KEY_DOWN, c, UIState(), FakeIO())     # slot 2
    msg = dispatch(ord("a"), c, UIState(), FakeIO())
    assert "2" in msg
    assert c.active_slot == 2


def test_enter_type_in_sets_value():
    c = make()
    c.field_idx = [f.name for f in FIELD_ORDER].index("tempo")
    io = FakeIO(prompt="140")
    dispatch(ord("\n"), c, UIState(), io)
    assert c.rows()[0].values["tempo"] == 140


def test_enter_type_in_invalid_reports_message():
    c = make()
    c.field_idx = [f.name for f in FIELD_ORDER].index("tempo")
    msg = dispatch(ord("\n"), c, UIState(), FakeIO(prompt="999"))
    assert "invalid" in msg.lower()


def test_m_toggles_monitor_and_q_quits_when_clean():
    c = make()
    ui = UIState()
    dispatch(ord("m"), c, ui, FakeIO())
    assert ui.show_monitor is True
    dispatch(ord("q"), c, ui, FakeIO())
    assert ui.running is False


def test_q_with_unsaved_edits_confirms():
    c = make()
    c.field_idx = [f.name for f in FIELD_ORDER].index("keybed_octave")
    dispatch(ord("+"), c, UIState(), FakeIO())
    ui = UIState()
    dispatch(ord("q"), c, ui, FakeIO(confirm=False))     # declines
    assert ui.running is True
    dispatch(ord("q"), c, ui, FakeIO(confirm=True))      # accepts
    assert ui.running is False


def test_l_loads_chosen_preset(tmp_path, monkeypatch):
    monkeypatch.setenv("LPK25_PRESET_DIR", str(tmp_path))
    c = make()
    c.field_idx = [f.name for f in FIELD_ORDER].index("keybed_octave")
    dispatch(ord("+"), c, UIState(), FakeIO())
    c.save_preset("p1")
    dispatch(curses.KEY_DOWN, c, UIState(), FakeIO())    # slot 2
    dispatch(ord("l"), c, UIState(), FakeIO(choose="p1"))
    assert c.rows()[1].values["keybed_octave"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_tui_dispatch.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'lpk25.tui.app'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/lpk25/tui/app.py
"""Key dispatch, UI state, and the curses main loop for `lpk25 tui`.

`dispatch` is pure (no curses I/O): it maps a key code to controller/ui changes
through an injected `io` object, so every key path is unit-tested. The curses
loop (`run`/`_loop`, added alongside) only draws and reads keys."""

from __future__ import annotations

import curses
from dataclasses import dataclass

from .. import library


@dataclass
class UIState:
    show_monitor: bool = False
    show_help: bool = False
    running: bool = True


def _save(controller, io, kind: str) -> str | None:
    saver = controller.save_preset if kind == "preset" else controller.save_bank
    name = io.prompt(f"save {kind} name: ")
    if not name:
        return None
    try:
        saver(name)
        return f"saved {kind} {name}"
    except library.LibraryError:
        if io.confirm(f"{kind} {name!r} exists — overwrite?"):
            saver(name, force=True)
            return f"saved {kind} {name}"
    return "cancelled"


def _load(controller, io, kind: str) -> str | None:
    names = (library.list_preset_names if kind == "preset" else library.list_bank_names)()
    if not names:
        return f"no {kind}s saved"
    choice = io.choose(f"load {kind}", names)
    if not choice:
        return None
    try:
        if kind == "preset":
            controller.load_preset_into_current(choice)
        else:
            controller.load_bank(choice)
        return f"loaded {kind} {choice}"
    except Exception as exc:                      # noqa: BLE001 - surfaced to status line
        return f"load failed: {exc}"


def dispatch(key: int, controller, ui: UIState, io) -> str | None:
    if key in (curses.KEY_UP, ord("k")):
        controller.move(-1, 0)
    elif key in (curses.KEY_DOWN, ord("j")):
        controller.move(1, 0)
    elif key in (curses.KEY_LEFT, ord("h")):
        controller.move(0, -1)
    elif key in (curses.KEY_RIGHT, ord("l")):
        controller.move(0, 1)
    elif key in (ord("-"), ord("_")):
        controller.step(-1)
    elif key in (ord("+"), ord("=")):
        controller.step(1)
    elif key == ord("["):
        controller.step(-10)
    elif key == ord("]"):
        controller.step(10)
    elif key == ord("u"):
        controller.undo_slot()
        return "reverted slot"
    elif key == ord("\n"):
        text = io.prompt(f"{controller.focused_field().name} = ")
        if text:
            try:
                controller.set_value(text)
                return "set"
            except Exception as exc:              # noqa: BLE001
                return f"invalid: {exc}"
    elif key == ord("w"):
        try:
            r = controller.write_current()
            return f"wrote slot {r.slot}" + (" ✓" if r.verified else "")
        except Exception as exc:                  # noqa: BLE001
            return f"write failed: {exc}"
    elif key == ord("W"):
        try:
            rs = controller.write_all_dirty()
            return f"wrote {len(rs)} slot(s)"
        except Exception as exc:                  # noqa: BLE001
            return f"write failed: {exc}"
    elif key == ord("a"):
        try:
            return f"activated slot {controller.activate_current()}"
        except Exception as exc:                  # noqa: BLE001
            return f"activate failed: {exc}"
    elif key == ord("r"):
        if io.confirm("reload from device — discard edits?"):
            controller.reload()
            return "reloaded"
    elif key == ord("s"):
        return _save(controller, io, "preset")
    elif key == ord("l"):
        return _load(controller, io, "preset")
    elif key == ord("b"):
        return _save(controller, io, "bank")
    elif key == ord("B"):
        return _load(controller, io, "bank")
    elif key == ord("m"):
        ui.show_monitor = not ui.show_monitor
        return "monitor on" if ui.show_monitor else "monitor off"
    elif key == ord("?"):
        ui.show_help = not ui.show_help
    elif key == ord("q"):
        if not controller.any_dirty() or io.confirm("unsaved edits — quit anyway?"):
            ui.running = False
    return None
```

> Note: `l` is both "move right" and "load preset". Resolve by removing `ord("l")` from the move-right branch (keep `curses.KEY_RIGHT` only) so `l` means load. (The test `test_arrows_move_cursor` uses `KEY_RIGHT`, and `test_l_loads_chosen_preset` expects load.) Apply this when writing the code.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_tui_dispatch.py -q`
Expected: PASS (9 tests). If `test_arrows_move_cursor` and `test_l_loads_chosen_preset` conflict, ensure `l` is load-only as noted.

- [ ] **Step 5: Commit**

```bash
git add src/lpk25/tui/app.py tests/test_tui_dispatch.py
git commit -m "Add pure TUI key dispatch + UI state + IO protocol

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_018PaHHGKo9tFhdQSNWBxJk6"
```

---

### Task 7: curses view + main loop (thin layer)

**Files:**
- Create: `src/lpk25/tui/view.py`
- Modify: `src/lpk25/tui/app.py` (add `run` + `_loop` + `_CursesIO`)
- Test: `tests/test_tui_smoke.py`

**Interfaces:**
- Consumes: `EditorController`, `MidiMonitor`, `UIState`, `dispatch`, `render._COLUMNS`, `curses`.
- Produces: `view.draw(stdscr, controller, monitor, ui, mock, message)`, `view.prompt(stdscr, label)`, `view.choose(stdscr, title, options)`, `view.confirm(stdscr, msg)`, `app.run(transport, mock) -> int`.

This is the only layer that touches the terminal, so it is verified by an
import/smoke test plus manual run, not unit tests of drawing.

- [ ] **Step 1: Write the failing smoke test**

```python
# tests/test_tui_smoke.py
import importlib


def test_tui_modules_import():
    for name in ("controller", "monitor", "app", "view"):
        importlib.import_module(f"lpk25.tui.{name}")


def test_app_exposes_run_and_dispatch():
    from lpk25.tui import app
    assert callable(app.run)
    assert callable(app.dispatch)


def test_view_exposes_draw_and_overlays():
    from lpk25.tui import view
    for fn in ("draw", "prompt", "choose", "confirm"):
        assert callable(getattr(view, fn))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_tui_smoke.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'lpk25.tui.view'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/lpk25/tui/view.py
"""curses drawing + input overlays for the TUI. Thin: no edit logic here."""

from __future__ import annotations

import curses

from .. import render
from .controller import FIELD_ORDER

_HEADERS = ["slot"] + [h for name, h in render._COLUMNS if name != "slot"]
_KEYS_1 = "up/dn slot   l/r field   -/+ change   ⏎ type   w write   a activate"
_KEYS_2 = "s/l preset   b/B bank   r reload   m monitor   ? help   q quit"


def _fmt_value(name: str, value: object) -> str:
    return render._disp(name, value)


def _grid_lines(controller) -> list[tuple[str, bool]]:
    """Return (text, is_active) per row; the focused cell is wrapped in [..]."""
    rows = controller.rows()
    field_names = [f.name for f in FIELD_ORDER]
    cells = [_HEADERS]
    for r in rows:
        line = [str(r.slot) + ("*" if r.dirty else "")]
        line += [_fmt_value(n, r.values.get(n)) for n in field_names]
        cells.append(line)
    widths = [max(len(row[i]) for row in cells) for i in range(len(_HEADERS))]

    def render_row(cols, prefix):
        return prefix + "  ".join(c.rjust(widths[i]) for i, c in enumerate(cols))

    out = [(render_row(cells[0], "  "), False)]
    for ri, r in enumerate(rows):
        prefix = "▶ " if r.active else "  "
        out.append((render_row(cells[ri + 1], prefix), r.active))
    return out


def draw(stdscr, controller, monitor, ui, mock: bool, message: str) -> None:
    stdscr.erase()
    maxy, maxx = stdscr.getmaxyx()
    tag = "  [MOCK]" if mock else ""
    stdscr.addnstr(0, 0, f"lpk25 tui — {controller.header()}{tag}", maxx - 1, curses.A_BOLD)

    grid = _grid_lines(controller)
    focus_col = controller.field_idx
    for i, (line, _active) in enumerate(grid):
        y = 2 + i
        if y >= maxy - 4:
            break
        attr = curses.A_REVERSE if (i - 1) == controller.slot_idx else curses.A_NORMAL
        stdscr.addnstr(y, 0, line, maxx - 1, attr)

    legend_y = 2 + len(grid) + 1
    if legend_y < maxy - 1:
        stdscr.addnstr(legend_y, 0, _KEYS_1, maxx - 1, curses.A_DIM)
    if legend_y + 1 < maxy - 1:
        stdscr.addnstr(legend_y + 1, 0, _KEYS_2, maxx - 1, curses.A_DIM)

    if ui.show_monitor:
        my = legend_y + 3
        if my < maxy - 1:
            stdscr.addnstr(my, 0, "── monitor (m) " + "─" * max(0, maxx - 16), maxx - 1)
            if monitor.available and not mock:
                for j, mln in enumerate(monitor.lines(maxy - my - 2)):
                    if my + 1 + j < maxy - 1:
                        stdscr.addnstr(my + 1 + j, 0, mln, maxx - 1)
            elif my + 1 < maxy - 1:
                stdscr.addnstr(my + 1, 0, "no MIDI input (offline)", maxx - 1, curses.A_DIM)

    stdscr.addnstr(maxy - 1, 0, (message or "")[: maxx - 1], maxx - 1, curses.A_REVERSE)
    stdscr.refresh()


def _read_line(stdscr, label: str) -> str | None:
    maxy, maxx = stdscr.getmaxyx()
    curses.echo()
    curses.curs_set(1)
    stdscr.addnstr(maxy - 1, 0, " " * (maxx - 1), maxx - 1)
    stdscr.addnstr(maxy - 1, 0, label, maxx - 1)
    try:
        raw = stdscr.getstr(maxy - 1, len(label), 64)
    finally:
        curses.noecho()
        curses.curs_set(0)
    if raw is None:
        return None
    text = raw.decode("utf-8", "replace").strip()
    return text or None


def prompt(stdscr, label: str) -> str | None:
    return _read_line(stdscr, label)


def choose(stdscr, title: str, options: list[str]) -> str | None:
    # Minimal picker: list options with indices, read a number.
    maxy, maxx = stdscr.getmaxyx()
    stdscr.erase()
    stdscr.addnstr(0, 0, title, maxx - 1, curses.A_BOLD)
    for i, opt in enumerate(options):
        stdscr.addnstr(2 + i, 0, f"{i + 1}. {opt}", maxx - 1)
    stdscr.refresh()
    text = _read_line(stdscr, "pick number (Enter to cancel): ")
    if not text or not text.isdigit():
        return None
    idx = int(text) - 1
    return options[idx] if 0 <= idx < len(options) else None


def confirm(stdscr, msg: str) -> bool:
    text = _read_line(stdscr, f"{msg} [y/N]: ")
    return bool(text) and text.lower().startswith("y")
```

Now append the curses loop to `src/lpk25/tui/app.py`:

```python
# append to src/lpk25/tui/app.py
from . import view as _view                       # noqa: E402
from .controller import EditorController          # noqa: E402
from .monitor import MidiMonitor                  # noqa: E402


class _CursesIO:
    def __init__(self, stdscr):
        self._stdscr = stdscr

    def prompt(self, label):
        return _view.prompt(self._stdscr, label)

    def choose(self, title, options):
        return _view.choose(self._stdscr, title, list(options))

    def confirm(self, msg):
        return _view.confirm(self._stdscr, msg)


def _loop(stdscr, controller, monitor, mock):
    curses.curs_set(0)
    stdscr.keypad(True)
    ui = UIState()
    io = _CursesIO(stdscr)
    message = "ready"
    while ui.running:
        _view.draw(stdscr, controller, monitor, ui, mock, message)
        key = stdscr.getch()
        message = dispatch(key, controller, ui, io) or message


def run(transport, mock: bool) -> int:
    from ..device import Device

    dev = Device(transport)
    controller = EditorController(dev, dev.dump(), dev.get_active_program())
    monitor = MidiMonitor(transport)
    if not mock:
        monitor.start()
    try:
        curses.wrapper(_loop, controller, monitor, mock)
    finally:
        monitor.stop()
    return 0
```

> `render._disp` already formats bool/enum/clock for display (reused here). If a
> referenced render helper is private, importing it within the same package is
> acceptable and keeps formatting DRY.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_tui_smoke.py -q`
Expected: PASS (3 tests). Then `python -m ruff check src/lpk25/tui` → clean.

Manual check (in a real terminal, not CI):
Run: `python -m lpk25.cli --mock tui` (after Task 8 wires the command) — navigate with arrows, `+`/`-` to change a value, `w` to write, `m` to toggle the monitor, `q` to quit.

- [ ] **Step 5: Commit**

```bash
git add src/lpk25/tui/view.py src/lpk25/tui/app.py tests/test_tui_smoke.py
git commit -m "Add curses view + main loop for the TUI editor

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_018PaHHGKo9tFhdQSNWBxJk6"
```

---

### Task 8: CLI command `lpk25 tui`

**Files:**
- Modify: `src/lpk25/cli.py` (add `cmd_tui`; register the `tui` subparser in `build_parser`)
- Test: `tests/test_tui_cli.py`

**Interfaces:**
- Consumes: `_make_transport`, `tui.app.run`, `sys.stdout.isatty`.
- Produces: `cli.cmd_tui(args) -> int`; subparser `tui` with `set_defaults(func=cmd_tui)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_tui_cli.py
from lpk25 import cli
from lpk25.transport import MockTransport


def test_tui_requires_a_tty(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdout.isatty", lambda: False)
    rc = cli.main(["--mock", "tui"])
    assert rc == 2
    assert "terminal" in capsys.readouterr().err.lower()


def test_tui_invokes_app_run_when_tty(monkeypatch):
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    called = {}

    def fake_run(transport, mock):
        called["mock"] = mock
        return 0

    monkeypatch.setattr("lpk25.tui.app.run", fake_run)
    monkeypatch.setattr(cli, "_make_transport", lambda args: MockTransport())
    rc = cli.main(["--mock", "tui"])
    assert rc == 0
    assert called["mock"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_tui_cli.py -q`
Expected: FAIL — `argument command: invalid choice: 'tui'`.

- [ ] **Step 3: Write minimal implementation**

Add `cmd_tui` to `src/lpk25/cli.py` (near `cmd_show`):

```python
def cmd_tui(args: argparse.Namespace) -> int:
    """Open the interactive curses editor."""
    if not sys.stdout.isatty():
        _eprint("error: tui requires an interactive terminal")
        return 2
    from .tui import app  # lazy: keep curses out of the other commands

    return app.run(_make_transport(args), mock=getattr(args, "mock", False))
```

Register the subparser in `build_parser` (after the `show` parser block):

```python
    tu = sub.add_parser("tui", help="interactive curses editor for all 4 programs")
    tu.set_defaults(func=cmd_tui)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_tui_cli.py -q`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/lpk25/cli.py tests/test_tui_cli.py
git commit -m "Wire `lpk25 tui` CLI command (TTY-guarded, lazy curses import)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_018PaHHGKo9tFhdQSNWBxJk6"
```

---

### Task 9: Documentation + full verification

**Files:**
- Modify: `README.md` (usage list)
- Modify: `docs/feature-list.md` (mark the TUI editor ✅)

**Interfaces:** none (docs only).

- [ ] **Step 1: Update the README usage list**

Add under the existing command list (near the `show`/`activate` lines):

```
lpk25 tui                                               interactive curses editor (all 4 programs)
```

And a short keybinding note below the list:

```
`lpk25 tui` keys: ↑↓ slot · ←→ field · -/+ change · ⏎ type-in · w write · a activate ·
s/l preset · b/B bank · r reload · m monitor · q quit
```

- [ ] **Step 2: Update docs/feature-list.md**

Find the interactive-editor / TUI row (the GUI/editor line) and set its status to
`✅ (`tui`)`. If no such row exists, add one under the editing section:

```
| Interactive multi-field editor | full editor screen | ✅ (`tui`) |
```

- [ ] **Step 3: Run the full suite + lint**

Run:
```bash
python -m pytest -q
python -m ruff check .
```
Expected: all tests pass (existing + the new `test_tui_*` files); ruff clean.

- [ ] **Step 4: Manual smoke (real terminal)**

Run: `python -m lpk25.cli --mock tui`
Confirm: grid shows 4 programs with `▶` on slot 1; arrows move the reverse-video
cursor; `+`/`-` change the focused value and add `*`; `w` clears `*`; `a` moves
`▶`; `m` toggles the monitor pane ("no MIDI input (offline)"); `q` exits cleanly
and the terminal is restored.

- [ ] **Step 5: Commit**

```bash
git add README.md docs/feature-list.md
git commit -m "Document the lpk25 tui interactive editor (#15)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_018PaHHGKo9tFhdQSNWBxJk6"
```

---

## Self-Review

**1. Spec coverage:**
- Toolkit curses + pure controller/thin view → Tasks 1–7. ✅
- Grid layout, all 4 visible, cursor → Tasks 1, 7. ✅
- Explicit per-slot write + dirty markers + backup/verify → Tasks 2, 3, 7. ✅
- Activate current slot → Task 3, 6. ✅
- Library preset/bank load/save → Tasks 4, 6. ✅
- Toggleable monitor pane + reader thread + mididecode reuse → Tasks 5, 7. ✅
- Offline (`--mock`) editable, monitor "no input"; non-TTY rc 2 → Tasks 7, 8. ✅
- Field schema from `codec.LPK25_MK1_FIELDS`; columns from `render._COLUMNS` → Task 1. ✅
- Error handling (VerificationError/CodecError/Library overwrite/quit confirm) → Tasks 6, 7. ✅
- Testing strategy (controller, monitor, dispatch, cli; curses untested) → Tasks 1–8. ✅
- Docs (README, feature-list, close #15) → Task 9. ✅

**2. Placeholder scan:** No TBD/TODO; every code step shows complete code. The one
behavioural note (remove `ord("l")` from move-right so `l` = load) is explicit. ✅

**3. Type consistency:** `EditorController` method names/signatures are identical
across Tasks 1–4 and their consumers in Task 6 (`move`, `step`, `set_value`,
`undo_slot`, `write_current`, `write_all_dirty`, `activate_current`, `reload`,
`save_preset`, `load_preset_into_current`, `save_bank`, `load_bank`, `any_dirty`,
`focused_field`, `rows`, `header`). `dispatch(key, controller, ui, io)` and the
`io` protocol (`prompt`/`choose`/`confirm`) match between Task 6 and the
`_CursesIO` adapter in Task 7. `MidiMonitor` API (`available`/`_consume`/`lines`/
`start`/`stop`) matches between Tasks 5 and 7. `FIELD_ORDER`/`RowView` defined in
Task 1 and used throughout. ✅
