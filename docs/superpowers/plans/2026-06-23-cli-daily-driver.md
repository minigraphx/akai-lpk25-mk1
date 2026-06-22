# CLI Daily-Driver Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the `lpk25` CLI a comfortable daily driver: quick single-parameter edits, a glanceable state readout, and a named single-program preset library.

**Architecture:** Thin new subcommands (`edit`, `show`, `preset`) over the existing `device.py` (which already auto-backs-up + read-back-verifies). Two new pure modules — `library.py` (preset files) and `render.py` (formatting) — keep logic testable without hardware. No changes to the validated codec/device core.

**Tech Stack:** Python 3.9+, stdlib `argparse`/`os`; existing `lpk25` package (`codec`, `device`, `model`, `transport.MockTransport`); `pytest` + `ruff`.

## Global Constraints

- Python **3.9+** (CI runs 3.9 and 3.12) — no 3.10+-only syntax (no `match`, no `X | Y` in runtime isinstance; `from __future__ import annotations` is already used for type hints).
- `ruff` clean, **line length ≤ 100**.
- **No new dependencies.** Stdlib only.
- All new tests run via `MockTransport` or pure functions — **no hardware** in the test suite.
- Run the whole suite with `.venv/bin/python -m pytest -q` and lint with `.venv/bin/python -m ruff check src/ tests/`.
- Reuse codec enum label sets (`codec.ARP_MODES`, `codec.TIME_DIVISIONS`, `codec.CLOCK_SOURCES`) for flag choices so the CLI and device codes cannot drift.

---

### Task 1: `library.py` — named single-program preset storage

**Files:**
- Create: `src/lpk25/library.py`
- Test: `tests/test_library.py`

**Interfaces:**
- Consumes: `model.Preset`, `model.Program` (existing: `Preset(programs=[...]).save(path)`, `Preset.load(path) -> Preset` with `.programs: list[Program]`).
- Produces:
  - `preset_dir() -> str`
  - `save_preset(name: str, program: Program, force: bool = False, directory: str | None = None) -> str`
  - `load_preset(name: str, directory: str | None = None) -> Program`
  - `list_preset_names(directory: str | None = None) -> list[str]`
  - `list_presets(directory: str | None = None) -> list[tuple[str, Program]]`
  - `class LibraryError(RuntimeError)`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_library.py`:

```python
import os

import pytest

from lpk25 import library
from lpk25.model import Program


def prog(slot=1):
    return Program.from_payload(slot, bytes([slot, 0, 4, 12, 0, 0, 5, 0, 0, 3, 0, 120, 0]))


def test_preset_dir_env_override(monkeypatch):
    monkeypatch.setenv("LPK25_PRESET_DIR", "/tmp/lpk25-presets-xyz")
    assert library.preset_dir() == "/tmp/lpk25-presets-xyz"


def test_preset_dir_xdg(monkeypatch):
    monkeypatch.delenv("LPK25_PRESET_DIR", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", "/tmp/xdg")
    assert library.preset_dir() == "/tmp/xdg/lpk25/presets"


def test_preset_dir_default(monkeypatch):
    monkeypatch.delenv("LPK25_PRESET_DIR", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    assert library.preset_dir().endswith("/.config/lpk25/presets")


def test_save_and_load_round_trip(tmp_path):
    d = str(tmp_path)
    path = library.save_preset("bass", prog(1), directory=d)
    assert os.path.isfile(path)
    loaded = library.load_preset("bass", directory=d)
    assert loaded.raw == prog(1).raw


def test_save_refuses_overwrite_without_force(tmp_path):
    d = str(tmp_path)
    library.save_preset("bass", prog(1), directory=d)
    with pytest.raises(library.LibraryError):
        library.save_preset("bass", prog(2), directory=d)
    # force overwrites
    library.save_preset("bass", prog(3), force=True, directory=d)
    assert library.load_preset("bass", directory=d).raw[0] == 3


def test_load_missing_raises_with_available(tmp_path):
    d = str(tmp_path)
    library.save_preset("one", prog(1), directory=d)
    with pytest.raises(library.LibraryError) as exc:
        library.load_preset("nope", directory=d)
    assert "one" in str(exc.value)


def test_list_presets(tmp_path):
    d = str(tmp_path)
    library.save_preset("b", prog(1), directory=d)
    library.save_preset("a", prog(2), directory=d)
    assert library.list_preset_names(directory=d) == ["a", "b"]
    rows = library.list_presets(directory=d)
    assert [n for n, _ in rows] == ["a", "b"]


def test_list_names_missing_dir_is_empty(tmp_path):
    assert library.list_preset_names(directory=str(tmp_path / "nope")) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_library.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'lpk25.library'`

- [ ] **Step 3: Write the implementation**

Create `src/lpk25/library.py`:

```python
"""Named single-program preset library.

Presets are stored as the existing single-program ``Preset`` JSON, so they
interoperate with ``lpk25 get -o`` / ``lpk25 set``. All functions are pure file
operations with no device dependency.
"""

from __future__ import annotations

import os

from .model import Preset, Program


class LibraryError(RuntimeError):
    """Raised for preset-library problems (missing preset, overwrite guard)."""


def preset_dir() -> str:
    """Resolve the presets directory (does NOT create it).

    Precedence: ``$LPK25_PRESET_DIR`` > ``$XDG_CONFIG_HOME/lpk25/presets`` >
    ``~/.config/lpk25/presets``.
    """
    env = os.environ.get("LPK25_PRESET_DIR")
    if env:
        return env
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(
        os.path.expanduser("~"), ".config"
    )
    return os.path.join(base, "lpk25", "presets")


def _path(name: str, directory: str | None) -> str:
    return os.path.join(directory or preset_dir(), f"{name}.json")


def save_preset(
    name: str, program: Program, force: bool = False, directory: str | None = None
) -> str:
    """Save ``program`` as a single-program preset named ``name``. Returns the path.

    Refuses to overwrite an existing preset unless ``force`` is True."""
    path = _path(name, directory)
    if os.path.exists(path) and not force:
        raise LibraryError(f"preset {name!r} already exists (use --force to overwrite)")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    Preset(programs=[program]).save(path)
    return path


def load_preset(name: str, directory: str | None = None) -> Program:
    """Load the single program from preset ``name``."""
    path = _path(name, directory)
    if not os.path.exists(path):
        avail = ", ".join(list_preset_names(directory)) or "(none)"
        raise LibraryError(f"preset {name!r} not found. Available: {avail}")
    preset = Preset.load(path)
    if not preset.programs:
        raise LibraryError(f"preset {name!r} contains no program")
    return preset.programs[0]


def list_preset_names(directory: str | None = None) -> list[str]:
    """Sorted names of saved presets (empty if the directory does not exist)."""
    directory = directory or preset_dir()
    if not os.path.isdir(directory):
        return []
    return sorted(f[:-5] for f in os.listdir(directory) if f.endswith(".json"))


def list_presets(directory: str | None = None) -> list[tuple[str, Program]]:
    """(name, program) pairs for every readable preset."""
    out: list[tuple[str, Program]] = []
    for name in list_preset_names(directory):
        try:
            out.append((name, load_preset(name, directory)))
        except LibraryError:
            continue
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_library.py -q`
Expected: PASS (8 passed)

- [ ] **Step 5: Lint and commit**

```bash
cd /home/andreas-schmidt/dev/akai-lpk25-mk1
.venv/bin/python -m ruff check src/lpk25/library.py tests/test_library.py
git add src/lpk25/library.py tests/test_library.py
git commit -m "Add library.py: named single-program preset storage"
```

---

### Task 2: `render.py` — human-readable program/preset formatting

**Files:**
- Create: `src/lpk25/render.py`
- Test: `tests/test_render.py`

**Interfaces:**
- Consumes: `codec.decode_program(raw) -> dict`, `model.Preset` (`.programs`), `model.Program` (`.slot`, `.raw`).
- Produces:
  - `format_presets_table(preset: Preset, active_slot: int | None = None) -> str`
  - `format_program(program: Program) -> str`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_render.py`:

```python
from lpk25 import render
from lpk25.model import Preset, Program


def mock_preset():
    # Mirror MockTransport's default programs (ch1, oct0, arp off, up, 1/16T,
    # internal, latch off, tempo 120, taps 3, arp_oct 0).
    raw = lambda s: bytes([s, 0, 4, 12, 0, 0, 5, 0, 0, 3, 0, 120, 0])
    return Preset(programs=[Program.from_payload(s, raw(s)) for s in range(1, 5)])


def test_table_has_headers_and_rows():
    out = render.format_presets_table(mock_preset(), active_slot=1)
    lines = out.splitlines()
    assert "ch" in lines[0] and "tempo" in lines[0] and "aoct" in lines[0]
    assert len(lines) == 5  # header + 4 slots


def test_table_marks_active_slot():
    out = render.format_presets_table(mock_preset(), active_slot=2)
    lines = out.splitlines()
    # exactly one data row carries the active marker
    assert sum(1 for ln in lines if "▶" in ln) == 1
    assert "▶" in lines[2]  # slot 2 is the 2nd data row (index 2 overall)


def test_table_renders_labels_not_raw_bytes():
    out = render.format_presets_table(mock_preset())
    assert "off" in out      # arp_enabled False -> off
    assert "1/16T" in out    # time_division code 5
    assert "int" in out      # clock internal -> int
    assert "120" in out      # tempo


def test_format_program_single():
    prog = Program.from_payload(3, bytes([3, 4, 5, 0, 1, 3, 2, 0, 1, 3, 1, 98, 3]))
    out = render.format_program(prog)
    assert out.splitlines()[0] == "slot 3"
    assert "ch" in out and "5" in out          # channel 5 (byte 4 -> +1)
    assert "exclusive" in out                   # arp_mode code 3
    assert "on" in out                          # arp_enabled
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_render.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'lpk25.render'`

- [ ] **Step 3: Write the implementation**

Create `src/lpk25/render.py`:

```python
"""Human-readable formatting of programs/presets for ``lpk25 show``."""

from __future__ import annotations

from . import codec
from .model import Preset, Program

# (codec field name, column header). "slot" is synthetic (from Program.slot).
_COLUMNS: list[tuple[str, str]] = [
    ("slot", "slot"),
    ("midi_channel", "ch"),
    ("keybed_octave", "oct"),
    ("transpose", "trans"),
    ("arp_enabled", "arp"),
    ("arp_mode", "mode"),
    ("time_division", "div"),
    ("clock", "clock"),
    ("arp_latch", "latch"),
    ("tempo", "tempo"),
    ("tempo_taps", "taps"),
    ("arp_octave", "aoct"),
]

_CLOCK_SHORT = {"internal": "int", "external": "ext"}


def _disp(field: str, value: object) -> str:
    if value is None:
        return "?"
    if field in ("arp_enabled", "arp_latch"):
        return "on" if value else "off"
    if field == "clock":
        return _CLOCK_SHORT.get(str(value), str(value))
    return str(value)


def _cells(program: Program) -> list[str]:
    values = codec.decode_program(program.raw)
    cells = []
    for field, _ in _COLUMNS:
        if field == "slot":
            cells.append(str(program.slot))
        else:
            cells.append(_disp(field, values.get(field)))
    return cells


def format_presets_table(preset: Preset, active_slot: int | None = None) -> str:
    """Render all programs as an aligned table; mark the active slot with ▶."""
    headers = [h for _, h in _COLUMNS]
    rows = [(p.slot, _cells(p)) for p in preset.programs]
    widths = [len(h) for h in headers]
    for _, cells in rows:
        for i, c in enumerate(cells):
            widths[i] = max(widths[i], len(c))

    def line(prefix: str, cells: list[str]) -> str:
        return prefix + "  ".join(c.rjust(widths[i]) for i, c in enumerate(cells))

    out = [line("  ", headers)]
    for slot, cells in rows:
        out.append(line("▶ " if slot == active_slot else "  ", cells))
    return "\n".join(out)


def format_program(program: Program) -> str:
    """Render a single program as a vertical field list."""
    values = codec.decode_program(program.raw)
    lines = [f"slot {program.slot}"]
    for field, header in _COLUMNS[1:]:
        lines.append(f"  {header:<6} {_disp(field, values.get(field))}")
    return "\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_render.py -q`
Expected: PASS (4 passed)

- [ ] **Step 5: Lint and commit**

```bash
.venv/bin/python -m ruff check src/lpk25/render.py tests/test_render.py
git add src/lpk25/render.py tests/test_render.py
git commit -m "Add render.py: human-readable program/preset table"
```

---

### Task 3: `lpk25 edit` — quick single-parameter tweaks

**Files:**
- Modify: `src/lpk25/cli.py` (add `EDIT_FLAGS`, `_collect_edits`, `cmd_edit`; register subparser in `build_parser`)
- Test: `tests/test_cli_daily_driver.py` (new)

**Interfaces:**
- Consumes: `_make_device(args)` → `Device`; `Device.get_program(slot) -> Program`; `Device.send_program(program, verify) -> WriteResult(slot, verified, backup_path)`; `codec.decode_program`, `codec.diff_payloads`, `codec.ARP_MODES/TIME_DIVISIONS/CLOCK_SOURCES`; `model.Program`.
- Produces: `cmd_edit(args) -> int`; an `edit` subcommand. (`cmd_show`/`cmd_preset` added in later tasks.)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_cli_daily_driver.py`:

```python
from lpk25 import cli, codec
from lpk25.transport import MockTransport


def run(argv, transport):
    # Patch _make_transport so the CLI talks to our in-memory device.
    orig = cli._make_transport
    cli._make_transport = lambda args: transport
    try:
        return cli.main(argv)
    finally:
        cli._make_transport = orig


def test_edit_changes_named_fields_only():
    tr = MockTransport()
    rc = run(["--mock", "edit", "1", "--channel", "5", "--octave", "-1"], tr)
    assert rc == 0
    raw = tr.programs[1]
    v = codec.decode_program(raw)
    assert v["midi_channel"] == 5
    assert v["keybed_octave"] == -1
    # untouched fields keep their defaults
    assert v["tempo"] == 120
    assert v["arp_mode"] == "up"


def test_edit_enum_and_bool_flags():
    tr = MockTransport()
    rc = run(["--mock", "edit", "2", "--arp", "on", "--arp-mode", "exclusive",
              "--clock", "external", "--latch", "on"], tr)
    assert rc == 0
    v = codec.decode_program(tr.programs[2])
    assert v["arp_enabled"] is True
    assert v["arp_mode"] == "exclusive"
    assert v["clock"] == "external"
    assert v["arp_latch"] is True


def test_edit_no_flags_errors():
    tr = MockTransport()
    rc = run(["--mock", "edit", "1"], tr)
    assert rc == 2


def test_edit_rejects_out_of_range():
    tr = MockTransport()
    rc = run(["--mock", "edit", "1", "--channel", "99"], tr)
    assert rc != 0
    # nothing written: channel byte unchanged (default 0 -> channel 1)
    assert codec.decode_program(tr.programs[1])["midi_channel"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_cli_daily_driver.py -q`
Expected: FAIL (argparse error: invalid choice 'edit' / `cmd_edit` undefined)

- [ ] **Step 3: Add `cmd_edit` and helpers to `cli.py`**

Add near the other command functions (e.g. after `cmd_diff`) in `src/lpk25/cli.py`:

```python
# Maps each `edit`/`set-field` CLI dest to its codec field name.
EDIT_FLAGS = {
    "channel": "midi_channel",
    "octave": "keybed_octave",
    "transpose": "transpose",
    "arp": "arp_enabled",
    "arp_mode": "arp_mode",
    "time_div": "time_division",
    "clock": "clock",
    "latch": "arp_latch",
    "tempo": "tempo",
    "taps": "tempo_taps",
    "arp_octave": "arp_octave",
}


def _collect_edits(args: argparse.Namespace) -> dict:
    values: dict = {}
    for dest, field in EDIT_FLAGS.items():
        v = getattr(args, dest, None)
        if v is None:
            continue
        if field in ("arp_enabled", "arp_latch"):
            v = v == "on"
        values[field] = v
    return values


def cmd_edit(args: argparse.Namespace) -> int:
    from .model import Program

    values = _collect_edits(args)
    if not values:
        _eprint("nothing to change (pass at least one field flag, e.g. --channel 5)")
        return 2
    dev = _make_device(args)
    before = dev.get_program(args.slot)
    patched = Program(
        slot=args.slot,
        values={**codec.decode_program(before.raw), **values},
        raw=before.raw,
    )
    result = dev.send_program(patched, verify=not args.no_verify)
    after = dev.get_program(args.slot)
    print(f"Wrote program {result.slot}; verified={result.verified}; "
          f"backup={result.backup_path}")
    for c in codec.diff_payloads(before.raw, after.raw):
        label = c.field or f"idx{c.index}"
        print(f"  {label}: {c.old} -> {c.new}")
    if "tempo_taps" in values:
        _eprint("note: --taps writes idx 9 (tempo_taps), confirmed by elimination only")
    return 0
```

- [ ] **Step 4: Register the `edit` subparser**

In `build_parser()` in `src/lpk25/cli.py`, add after the `diff` subparser registration (before `set`):

```python
    ed = sub.add_parser("edit", help="change one or more fields on a slot")
    ed.add_argument("slot", type=int, choices=(1, 2, 3, 4))
    ed.add_argument("--channel", type=int)
    ed.add_argument("--octave", type=int)
    ed.add_argument("--transpose", type=int)
    ed.add_argument("--arp", choices=("on", "off"))
    ed.add_argument("--arp-mode", dest="arp_mode", choices=tuple(codec.ARP_MODES.values()))
    ed.add_argument("--time-div", dest="time_div", choices=tuple(codec.TIME_DIVISIONS.values()))
    ed.add_argument("--clock", choices=tuple(codec.CLOCK_SOURCES.values()))
    ed.add_argument("--latch", choices=("on", "off"))
    ed.add_argument("--tempo", type=int)
    ed.add_argument("--taps", type=int)
    ed.add_argument("--arp-octave", dest="arp_octave", type=int)
    ed.add_argument("--no-verify", action="store_true")
    ed.set_defaults(func=cmd_edit)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_cli_daily_driver.py -q`
Expected: PASS (4 passed)

Note: out-of-range (`--channel 99`) raises `CodecError` inside `encode_program`; `cli.main` catches it in its top-level `except Exception` handler and returns 1, so `test_edit_rejects_out_of_range` sees a non-zero rc and no write (the error happens before `send_program`).

- [ ] **Step 6: Full suite + lint, then commit**

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check src/ tests/
git add src/lpk25/cli.py tests/test_cli_daily_driver.py
git commit -m "Add 'lpk25 edit': quick single-parameter tweaks"
```

---

### Task 4: `lpk25 show` — glanceable device state

**Files:**
- Modify: `src/lpk25/cli.py` (add `cmd_show`; register subparser; import `render`)
- Test: `tests/test_cli_daily_driver.py` (append)

**Interfaces:**
- Consumes: `Device.dump() -> Preset`, `Device.get_active_program() -> int | None`, `Device.get_program(slot) -> Program`, `render.format_presets_table`, `render.format_program`.
- Produces: `cmd_show(args) -> int`; a `show` subcommand.

- [ ] **Step 1: Write the failing tests (append to `tests/test_cli_daily_driver.py`)**

```python
def test_show_table(capsys):
    tr = MockTransport()
    rc = run(["--mock", "show"], tr)
    assert rc == 0
    out = capsys.readouterr().out
    assert "tempo" in out                 # header present
    assert out.count("\n") >= 5           # header + 4 slots
    assert "▶" in out                # active slot marked


def test_show_single_slot(capsys):
    tr = MockTransport()
    rc = run(["--mock", "show", "1"], tr)
    assert rc == 0
    out = capsys.readouterr().out
    assert out.startswith("slot 1")


def test_show_json(capsys):
    tr = MockTransport()
    rc = run(["--mock", "show", "--json"], tr)
    assert rc == 0
    out = capsys.readouterr().out
    assert '"programs"' in out            # falls back to dump JSON
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_cli_daily_driver.py -k show -q`
Expected: FAIL (invalid choice 'show')

- [ ] **Step 3: Add `cmd_show` and the `render` import**

In `src/lpk25/cli.py`, update the import line:

```python
from . import __version__, codec, protocol, render
```

Add the command (e.g. after `cmd_edit`):

```python
def cmd_show(args: argparse.Namespace) -> int:
    dev = _make_device(args)
    if args.json:
        print(dev.dump().to_json())
        return 0
    if args.slot is not None:
        print(render.format_program(dev.get_program(args.slot)))
        return 0
    print(render.format_presets_table(dev.dump(), dev.get_active_program()))
    return 0
```

- [ ] **Step 4: Register the `show` subparser**

In `build_parser()`, after the `edit` subparser:

```python
    sh = sub.add_parser("show", help="human-readable readout of the device state")
    sh.add_argument("slot", type=int, nargs="?", choices=(1, 2, 3, 4))
    sh.add_argument("--json", action="store_true", help="print dump JSON instead")
    sh.set_defaults(func=cmd_show)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_cli_daily_driver.py -k show -q`
Expected: PASS (3 passed)

- [ ] **Step 6: Full suite + lint, then commit**

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check src/ tests/
git add src/lpk25/cli.py tests/test_cli_daily_driver.py
git commit -m "Add 'lpk25 show': human-readable device state table"
```

---

### Task 5: `lpk25 preset save|apply|list` — named library

**Files:**
- Modify: `src/lpk25/cli.py` (add `cmd_preset`; register nested subparsers; import `library`)
- Test: `tests/test_cli_daily_driver.py` (append)

**Interfaces:**
- Consumes: `library.save_preset/load_preset/list_presets/list_preset_names/LibraryError`, `Device.get_program/send_program`, `model.Program.from_payload`, `codec.decode_program`.
- Produces: `cmd_preset(args) -> int`; a `preset` subcommand with `save`/`apply`/`list`.

**Note (correctness):** a preset saved from slot A has its slot-echo byte (`raw[0]`) = A. Applying it to slot B must rewrite `raw[0]` to B, or `send_program`'s read-back verify fails (the device echoes the target slot in byte 0). The plan rebuilds the payload with the corrected echo via `Program.from_payload(slot, bytes([slot]) + raw[1:])`.

- [ ] **Step 1: Write the failing tests (append to `tests/test_cli_daily_driver.py`)**

```python
def test_preset_save_and_apply_cross_slot(tmp_path, monkeypatch):
    monkeypatch.setenv("LPK25_PRESET_DIR", str(tmp_path))
    tr = MockTransport()
    # make slot 1 distinctive, then save it as a preset
    run(["--mock", "edit", "1", "--channel", "7", "--tempo", "150"], tr)
    assert run(["--mock", "preset", "save", "myset", "--from-slot", "1"], tr) == 0
    # apply onto slot 3
    assert run(["--mock", "preset", "apply", "myset", "3"], tr) == 0
    v = codec.decode_program(tr.programs[3])
    assert v["midi_channel"] == 7 and v["tempo"] == 150
    # slot-echo byte was corrected to the target slot (read-back verify passed)
    assert tr.programs[3][0] == 3


def test_preset_save_refuses_overwrite(tmp_path, monkeypatch):
    monkeypatch.setenv("LPK25_PRESET_DIR", str(tmp_path))
    tr = MockTransport()
    assert run(["--mock", "preset", "save", "dup", "--from-slot", "1"], tr) == 0
    assert run(["--mock", "preset", "save", "dup", "--from-slot", "1"], tr) != 0
    assert run(["--mock", "preset", "save", "dup", "--from-slot", "1", "--force"], tr) == 0


def test_preset_apply_missing_errors(tmp_path, monkeypatch):
    monkeypatch.setenv("LPK25_PRESET_DIR", str(tmp_path))
    tr = MockTransport()
    assert run(["--mock", "preset", "apply", "ghost", "1"], tr) != 0


def test_preset_list(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LPK25_PRESET_DIR", str(tmp_path))
    tr = MockTransport()
    run(["--mock", "preset", "save", "alpha", "--from-slot", "1"], tr)
    capsys.readouterr()  # clear
    assert run(["--mock", "preset", "list"], tr) == 0
    assert "alpha" in capsys.readouterr().out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_cli_daily_driver.py -k preset -q`
Expected: FAIL (invalid choice 'preset')

- [ ] **Step 3: Add `cmd_preset` and the `library` import**

In `src/lpk25/cli.py`, update the import:

```python
from . import __version__, codec, library, protocol, render
```

Add the command (e.g. after `cmd_show`):

```python
def cmd_preset(args: argparse.Namespace) -> int:
    from .model import Program

    if args.preset_action == "list":
        rows = library.list_presets()
        if not rows:
            print("(no presets)")
            return 0
        for name, prog in rows:
            v = codec.decode_program(prog.raw)
            print(f"{name}: ch{v['midi_channel']} oct{v['keybed_octave']:+d} "
                  f"arp={'on' if v['arp_enabled'] else 'off'} tempo{v['tempo']}")
        return 0

    if args.preset_action == "save":
        dev = _make_device(args)
        prog = dev.get_program(args.from_slot)
        path = library.save_preset(args.name, prog, force=args.force)
        print(f"Saved preset {args.name} to {path}")
        return 0

    if args.preset_action == "apply":
        prog = library.load_preset(args.name)
        # correct the slot-echo byte so read-back verify matches the target slot
        fixed = Program.from_payload(args.slot, bytes([args.slot]) + prog.raw[1:])
        dev = _make_device(args)
        result = dev.send_program(fixed, verify=not args.no_verify)
        print(f"Applied preset {args.name} to slot {result.slot}; "
              f"verified={result.verified}")
        return 0

    _eprint("unknown preset action")
    return 2
```

- [ ] **Step 4: Register the `preset` subparser with nested actions**

In `build_parser()`, after the `show` subparser:

```python
    pr = sub.add_parser("preset", help="named single-program preset library")
    pr_sub = pr.add_subparsers(dest="preset_action", required=True)

    pr_save = pr_sub.add_parser("save", help="save a slot as a named preset")
    pr_save.add_argument("name")
    pr_save.add_argument("--from-slot", dest="from_slot", type=int,
                         choices=(1, 2, 3, 4), default=1)
    pr_save.add_argument("--force", action="store_true")
    pr_save.set_defaults(func=cmd_preset)

    pr_apply = pr_sub.add_parser("apply", help="write a named preset onto a slot")
    pr_apply.add_argument("name")
    pr_apply.add_argument("slot", type=int, choices=(1, 2, 3, 4))
    pr_apply.add_argument("--no-verify", action="store_true")
    pr_apply.set_defaults(func=cmd_preset)

    pr_list = pr_sub.add_parser("list", help="list saved presets")
    pr_list.set_defaults(func=cmd_preset)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_cli_daily_driver.py -k preset -q`
Expected: PASS (4 passed)

- [ ] **Step 6: Full suite + lint, then commit**

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check src/ tests/
git add src/lpk25/cli.py tests/test_cli_daily_driver.py
git commit -m "Add 'lpk25 preset save/apply/list': named preset library"
```

---

### Task 6: Documentation — CLI surface tables

**Files:**
- Modify: `README.md` (CLI command list/usage)
- Modify: `docs/feature-list.md` (device-ops / file-ops status rows)

**Interfaces:** none (docs only).

- [ ] **Step 1: Update `README.md`**

Find the CLI usage/command section and add rows for the new commands (match the existing table/list style already in the file):

```
lpk25 edit <slot> [--channel N --octave N --transpose N --arp on/off
                   --arp-mode M --time-div D --clock int/ext --latch on/off
                   --tempo N --taps N --arp-octave N]   change fields on a slot
lpk25 show [slot] [--json]                              human-readable state
lpk25 preset save <name> [--from-slot N] [--force]      save a slot as a preset
lpk25 preset apply <name> <slot>                        write a preset onto a slot
lpk25 preset list                                       list saved presets
```

Add a one-line note: "Presets live in `$LPK25_PRESET_DIR` (default `~/.config/lpk25/presets`)."

- [ ] **Step 2: Update `docs/feature-list.md`**

In the "Device operations" table, mark the copy-preset and recall rows, and add the new ergonomics. Change the copy row note and add:

```
| Edit single fields on a slot | (inline, no editor) | ✅ (`edit`) |
| Human-readable state readout | — | ✅ (`show`) |
| Named single-program preset library | SAVE/LOAD PRESET | ✅ (`preset save/apply/list`) |
```

Leave `.syx` structured export and copy-slot as the remaining ⬜ items.

- [ ] **Step 3: Verify the docs render and the whole suite still passes**

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check src/ tests/
```
Expected: all tests pass, ruff clean.

- [ ] **Step 4: Commit**

```bash
git add README.md docs/feature-list.md
git commit -m "Document edit/show/preset CLI commands"
```

---

## Self-Review

**Spec coverage:**
- Quick single tweaks → Task 3 (`edit`). ✅
- Glanceable state → Task 4 (`show`). ✅
- Named single-program library → Tasks 1 + 5 (`library.py`, `preset`). ✅
- Storage location / XDG → Task 1 (`preset_dir`). ✅
- Overwrite guard → Tasks 1 + 5. ✅
- Reuse device safety path (backup + verify) → Tasks 3, 5 use `send_program`. ✅
- Error handling (bad value, no flags, missing preset, overwrite, taps note) → Tasks 3, 5. ✅
- Testing via MockTransport / pure → all tasks. ✅
- Docs → Task 6. ✅

**Placeholder scan:** No TBD/TODO; every code step shows complete code. ✅

**Type consistency:** `save_preset`/`load_preset`/`list_presets`/`preset_dir` signatures match between Task 1 (definition) and Task 5 (use). `render.format_presets_table(preset, active_slot)` / `format_program(program)` match between Task 2 and Task 4. `EDIT_FLAGS`/`_collect_edits` defined and used in Task 3. The slot-echo correctness note in Task 5 matches the device read-back-verify behavior. ✅
