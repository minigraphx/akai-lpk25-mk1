# `lpk25 copy` Command Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `lpk25 copy <src> <dst...>` to duplicate a device program from one slot onto one or more others, with a confirmation prompt and the existing auto-backup + read-back verification.

**Architecture:** A new `Program.reslot(dst)` homes the slot-echo correction (the device echoes the target slot in payload byte 0, so a cross-slot write must rewrite it). `cmd_copy` reads the source program, builds one `reslot` copy per destination, and hands them to the existing `device.load()` (which already backs up once, rate-limits, and verifies each write). `preset apply` is refactored to use `reslot` too, removing the inline duplicate.

**Tech Stack:** Python 3.9+, stdlib `argparse`; existing `lpk25` package (`model`, `device`, `codec`, `transport.MockTransport`); `pytest` + `ruff`.

## Global Constraints

- Python **3.9+** — no 3.10+-only syntax. `from __future__ import annotations` is already used in `model.py` and `cli.py`.
- `ruff` clean, **line length ≤ 100**. No unused imports (F401).
- **No new dependencies.** Stdlib only.
- **No changes to `device.py`** — reuse `Device.load(preset, verify=…)` and `Device.get_program(slot)` as-is.
- All new tests run via `MockTransport` or pure model calls — **no hardware**.
- Run the suite with `.venv/bin/python -m pytest -q` and lint with `.venv/bin/python -m ruff check src/ tests/`.

---

### Task 1: `Program.reslot()` + refactor `preset apply`

**Files:**
- Modify: `src/lpk25/model.py` (add `Program.reslot`)
- Modify: `src/lpk25/cli.py` (`cmd_preset` apply branch uses `reslot`; drop now-unused local `Program` import)
- Test: `tests/test_model.py` (new)

**Interfaces:**
- Consumes: existing `Program.from_payload(slot: int, payload: bytes) -> Program`; `Program` fields `.slot: int`, `.raw: bytes`, `.values: dict`.
- Produces: `Program.reslot(dst: int) -> Program` — a copy addressed to `dst` with payload byte 0 set to `dst` and values re-decoded.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_model.py`:

```python
import pytest

from lpk25.model import Program


def make(slot=1):
    # slot, ch10(byte9), oct+4, transpose+12, arp on, excl, 1/8, clock int,
    # latch on, taps4, tempo226, arp_oct3
    return Program.from_payload(slot, bytes([slot, 9, 8, 24, 1, 3, 2, 0, 1, 4, 1, 98, 3]))


def test_reslot_sets_echo_and_slot_preserves_rest():
    p = make(1)
    q = p.reslot(3)
    assert q.slot == 3
    assert q.raw[0] == 3                    # slot-echo byte corrected
    assert q.raw[1:] == p.raw[1:]           # every other byte preserved
    assert q.values["midi_channel"] == 10   # values re-decoded from new payload
    assert p.raw[0] == 1                     # original program untouched


def test_reslot_empty_raw_raises():
    with pytest.raises(ValueError):
        Program(slot=1, raw=b"").reslot(2)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_model.py -q`
Expected: FAIL with `AttributeError: 'Program' object has no attribute 'reslot'`

- [ ] **Step 3: Add `reslot` to `Program`**

In `src/lpk25/model.py`, add this method to the `Program` class (e.g. right after `to_payload`):

```python
    def reslot(self, dst: int) -> Program:
        """Return a copy of this program addressed to slot ``dst``.

        Rewrites the slot-echo byte (payload[0]) to ``dst`` so a cross-slot write
        reads back identically — the device echoes the target slot in byte 0."""
        if not self.raw:
            raise ValueError("cannot reslot a program with no raw payload")
        return Program.from_payload(dst, bytes([dst]) + self.raw[1:])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_model.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Refactor `cmd_preset` apply to use `reslot`**

In `src/lpk25/cli.py`, the `cmd_preset` function currently starts with `from .model import Program` and the apply branch reads:

```python
        if args.preset_action == "apply":
            prog = library.load_preset(args.name)
            # correct the slot-echo byte so read-back verify matches the target slot
            fixed = Program.from_payload(args.slot, bytes([args.slot]) + prog.raw[1:])
            dev = _make_device(args)
            result = dev.send_program(fixed, verify=not args.no_verify)
            print(f"Applied preset {args.name} to slot {result.slot}; "
                  f"verified={result.verified}")
            return 0
```

Replace the apply branch body with:

```python
        if args.preset_action == "apply":
            prog = library.load_preset(args.name)
            dev = _make_device(args)
            result = dev.send_program(prog.reslot(args.slot), verify=not args.no_verify)
            print(f"Applied preset {args.name} to slot {result.slot}; "
                  f"verified={result.verified}")
            return 0
```

Then **delete the now-unused `from .model import Program` line** at the top of `cmd_preset` (nothing else in `cmd_preset` uses `Program`). Leaving it triggers a ruff F401.

- [ ] **Step 6: Run the full suite + lint**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS (existing `preset apply` tests, incl. `test_preset_save_and_apply_cross_slot` asserting `tr.programs[3][0] == 3`, still pass — they now exercise `reslot`).

Run: `.venv/bin/python -m ruff check src/ tests/`
Expected: All checks passed.

- [ ] **Step 7: Commit**

```bash
cd /home/andreas-schmidt/dev/akai-lpk25-mk1
git add src/lpk25/model.py src/lpk25/cli.py tests/test_model.py
git commit -m "Add Program.reslot(); use it in preset apply (DRY slot-echo fix)"
```

---

### Task 2: `lpk25 copy` command + docs

**Files:**
- Modify: `src/lpk25/cli.py` (add `_confirm`, `cmd_copy`, and the `copy` subparser)
- Modify: `README.md` (usage block), `docs/feature-list.md` (copy row)
- Test: `tests/test_cli_daily_driver.py` (append)

**Interfaces:**
- Consumes: `_make_device(args)` → `Device`; `Device.get_program(slot) -> Program`; `Program.reslot(dst) -> Program` (Task 1); `Device.load(preset, verify=…) -> list[WriteResult]` where `WriteResult` has `.slot`, `.verified`, `.backup_path`; `model.Preset(programs=[...])` (already imported as `Preset` at the top of `cli.py`).
- Produces: `cmd_copy(args) -> int`; `_confirm(prompt) -> bool`; a `copy` subcommand.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cli_daily_driver.py` (it already has the `run(argv, transport)` helper and imports `cli`, `codec`, `MockTransport`):

```python
def test_copy_single_dst():
    tr = MockTransport()
    run(["--mock", "edit", "1", "--channel", "7"], tr)       # make slot 1 distinctive
    rc = run(["--mock", "copy", "1", "3", "--yes"], tr)
    assert rc == 0
    assert tr.programs[3][0] == 3                              # slot-echo corrected
    assert codec.decode_program(tr.programs[3])["midi_channel"] == 7


def test_copy_mirror_to_many_leaves_source():
    tr = MockTransport()
    run(["--mock", "edit", "1", "--channel", "9"], tr)
    rc = run(["--mock", "copy", "1", "2", "3", "4", "--yes"], tr)
    assert rc == 0
    for d in (2, 3, 4):
        assert codec.decode_program(tr.programs[d])["midi_channel"] == 9
        assert tr.programs[d][0] == d
    assert tr.programs[1][0] == 1                              # source slot echo intact


def test_copy_confirm_yes(monkeypatch):
    tr = MockTransport()
    run(["--mock", "edit", "1", "--channel", "5"], tr)
    monkeypatch.setattr("builtins.input", lambda *a: "y")
    rc = run(["--mock", "copy", "1", "2"], tr)                # no --yes -> prompts
    assert rc == 0
    assert codec.decode_program(tr.programs[2])["midi_channel"] == 5


def test_copy_confirm_no_aborts(monkeypatch):
    tr = MockTransport()
    before = bytes(tr.programs[2])
    monkeypatch.setattr("builtins.input", lambda *a: "n")
    rc = run(["--mock", "copy", "1", "2"], tr)
    assert rc == 1
    assert tr.programs[2] == before                           # nothing written


def test_copy_self_is_nothing():
    tr = MockTransport()
    rc = run(["--mock", "copy", "1", "1", "--yes"], tr)
    assert rc == 2


def test_copy_dedupes_dsts():
    tr = MockTransport()
    run(["--mock", "edit", "1", "--channel", "8"], tr)
    rc = run(["--mock", "copy", "1", "2", "2", "--yes"], tr)
    assert rc == 0
    assert codec.decode_program(tr.programs[2])["midi_channel"] == 8
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_cli_daily_driver.py -k copy -q`
Expected: FAIL (argparse error: invalid choice 'copy')

- [ ] **Step 3: Add `_confirm` and `cmd_copy` to `cli.py`**

In `src/lpk25/cli.py`, add near the other command functions (e.g. after `cmd_copy`'s neighbours — place it right after `cmd_diff` or `cmd_edit`):

```python
def _confirm(prompt: str) -> bool:
    """Ask a yes/no question on stdin. True only for 'y'/'yes' (case-insensitive)."""
    return input(prompt).strip().lower() in ("y", "yes")


def cmd_copy(args: argparse.Namespace) -> int:
    src = args.src
    dsts = sorted(set(args.dst))
    if src in dsts:
        dsts.remove(src)
        _eprint(f"skipping slot {src} (same as source)")
    if not dsts:
        _eprint("nothing to copy (destination is the source)")
        return 2
    dev = _make_device(args)
    src_prog = dev.get_program(src)
    if not args.yes:
        slots = ", ".join(str(d) for d in dsts)
        prompt = f"About to overwrite slot(s) {slots} with a copy of slot {src}. Proceed? [y/N] "
        if not _confirm(prompt):
            _eprint("aborted; nothing written")
            return 1
    preset = Preset(programs=[src_prog.reslot(d) for d in dsts])
    results = dev.load(preset, verify=not args.no_verify)
    for r in results:
        print(f"  slot {r.slot}: verified={r.verified}")
    if results:
        print(f"backup: {results[0].backup_path}")
    return 0
```

- [ ] **Step 4: Register the `copy` subparser**

In `build_parser()`, add after the `preset` subparser block (the `pr_list.set_defaults(func=cmd_preset)` line) and before the `set` parser:

```python
    cp = sub.add_parser("copy", help="copy a program from one slot onto others")
    cp.add_argument("src", type=int, choices=(1, 2, 3, 4))
    cp.add_argument("dst", type=int, nargs="+", choices=(1, 2, 3, 4))
    cp.add_argument("-y", "--yes", action="store_true", help="skip the confirmation prompt")
    cp.add_argument("--no-verify", action="store_true")
    cp.set_defaults(func=cmd_copy)
```

- [ ] **Step 5: Run the copy tests, then the full suite + lint**

Run: `.venv/bin/python -m pytest tests/test_cli_daily_driver.py -k copy -q`
Expected: PASS (6 passed)

Run: `.venv/bin/python -m pytest -q` then `.venv/bin/python -m ruff check src/ tests/`
Expected: all tests pass, ruff clean.

- [ ] **Step 6: Update docs**

In `README.md`, add to the usage code block (after the `preset` lines):

```
lpk25 copy <src> <dst...> [--yes]                       copy a slot onto others
```

In `docs/feature-list.md`, the "Device operations" table has the row:

```
| Copy preset (read slot A → write slot B) | copy workflow | ⬜ (compose get + set) |
```

Change its status cell to:

```
| Copy preset (read slot A → write slot B) | copy workflow | ✅ (`copy`, one or more dsts) |
```

- [ ] **Step 7: Final suite + lint, then commit**

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check src/ tests/
git add src/lpk25/cli.py tests/test_cli_daily_driver.py README.md docs/feature-list.md
git commit -m "Add 'lpk25 copy': duplicate a program across slots (confirm + backup)"
```

---

## Self-Review

**Spec coverage:**
- `copy <src> <dst...>`, one or more dsts → Task 2 (`cmd_copy`, `nargs="+"`). ✅
- Confirm, then auto-backup; `--yes` bypass → Task 2 (`_confirm`, `args.yes`). ✅
- Reuse `device.load()` for backup-once + per-slot verify → Task 2. ✅
- `Program.reslot()` homes the slot-echo fix; `preset apply` refactored → Task 1. ✅
- Drop `src` from dsts (no-op self-copy), empty → rc 2 → Task 2 (`test_copy_self_is_nothing`). ✅
- dedupe dsts → Task 2 (`test_copy_dedupes_dsts`). ✅
- abort → rc 1, no write → Task 2 (`test_copy_confirm_no_aborts`). ✅
- `--no-verify` → Task 2 (subparser + passed to `load`). ✅
- Docs (README + feature-list) → Task 2 Step 6. ✅

**Placeholder scan:** No TBD/TODO; every code step shows complete code. ✅

**Type consistency:** `Program.reslot(dst) -> Program` defined in Task 1, used in Task 2's `cmd_copy` and in the refactored `cmd_preset`. `Device.load(preset, verify=…) -> list[WriteResult]` (`.slot`/`.verified`/`.backup_path`) used consistently with `cmd_load`'s existing usage. `Preset` is already imported at the top of `cli.py`. `args.yes` matches the `-y/--yes` dest. ✅
