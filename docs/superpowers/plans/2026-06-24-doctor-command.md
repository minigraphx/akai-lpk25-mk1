# `lpk25 doctor` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `lpk25 doctor` command that runs an ordered MIDI-setup/connectivity checklist, prints ✅/❌ per check with actionable hints, and exits non-zero when a required check fails.

**Architecture:** A new `src/lpk25/diagnostics.py` holds pure check logic — each check returns a `CheckResult` dataclass; `run_diagnostics()` runs them in dependency order and short-circuits downstream checks (marking them `skip`) when a prerequisite is not ok. The module never prints and never imports `MidoTransport` directly (the CLI injects a `device_factory`), so every check is unit-testable against `MockTransport`/fakes with no hardware. `cli.cmd_doctor` formats the results and maps overall status to the exit code.

**Tech Stack:** Python 3.9+, argparse, pytest. Reuses existing `transport.list_ports`/`transport._match_port`, `discovery.detect_model`, `device.Device`, `protocol.MODEL_LPK25_MK1`.

## Global Constraints

- Python 3.9+; every module starts with `from __future__ import annotations`.
- Line length ≤ 100 (ruff); run `.venv/bin/ruff check src/ tests/` clean.
- Tests run with no hardware: `.venv/bin/python -m pytest -q`.
- `diagnostics.py` must not call `print()` and must not import `MidoTransport` (the CLI injects a `device_factory`); hardware backends are reached only through injected callables / lazy imports.
- Exit code rule: `1` if any `CheckResult.status == "fail"`, else `0`. `warn` and `skip` never fail the run.
- Status marks: `ok`=✅ `warn`=⚠️ `fail`=❌ `skip`=⏭.
- Model mismatch (a different model byte answers) is a `warn`, not a `fail`. A silent device is the `fail`.
- `--roundtrip` writes **slot 1 only**, byte-identical, behind a mandatory full backup.
- Install hint string (use verbatim): `pip install 'lpk25[midi]'  (Linux: sudo apt-get install libasound2-dev first)`

## File Structure

- `src/lpk25/diagnostics.py` (new) — `Status`, `CheckResult`, `INSTALL_HINT`, `_module_present`, `_skip`, `check_backend`, `check_ports`, `check_device`, `check_roundtrip`, `run_diagnostics`.
- `src/lpk25/cli.py` (modify) — add `cmd_doctor`; register the `doctor` subparser.
- `tests/test_diagnostics.py` (new) — unit tests for every check + orchestrator.
- `tests/test_cli_doctor.py` (new) — CLI integration tests via `--mock`.
- `README.md`, `docs/feature-list.md` (modify) — document the command.

---

### Task 1: diagnostics module — `CheckResult`, `check_backend`, `check_ports`

**Files:**
- Create: `src/lpk25/diagnostics.py`
- Test: `tests/test_diagnostics.py`

**Interfaces:**
- Consumes: `lpk25.transport.list_ports() -> dict` (`{"inputs": [...], "outputs": [...]}`), `lpk25.transport._match_port(names: list[str], match: str) -> str | None`.
- Produces:
  - `Status = Literal["ok", "warn", "fail", "skip"]`
  - `@dataclass CheckResult(name: str, status: Status, detail: str, hint: str | None = None)`
  - `INSTALL_HINT: str`
  - `_module_present(name: str) -> bool`
  - `_skip(name: str, prereq: str) -> CheckResult`
  - `check_backend(mock: bool = False) -> CheckResult`
  - `check_ports(mock: bool, port_match: str, in_port: str | None, out_port: str | None, list_ports_fn: Callable[[], dict] | None = None) -> CheckResult`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_diagnostics.py`:

```python
from lpk25 import diagnostics as dg


def test_check_backend_mock_is_ok():
    r = dg.check_backend(mock=True)
    assert r.status == "ok"
    assert "mock" in r.detail.lower()


def test_check_backend_present(monkeypatch):
    monkeypatch.setattr(dg, "_module_present", lambda name: True)
    r = dg.check_backend(mock=False)
    assert r.status == "ok"
    assert "mido" in r.detail


def test_check_backend_missing_gives_install_hint(monkeypatch):
    monkeypatch.setattr(dg, "_module_present", lambda name: False)
    r = dg.check_backend(mock=False)
    assert r.status == "fail"
    assert r.hint == dg.INSTALL_HINT


def test_check_ports_mock_is_ok():
    assert dg.check_ports(True, "LPK25", None, None).status == "ok"


def test_check_ports_matched():
    fake = lambda: {"inputs": ["LPK25:LPK25 MIDI 1 24:0"], "outputs": ["LPK25:LPK25 MIDI 1 24:0"]}
    r = dg.check_ports(False, "LPK25", None, None, list_ports_fn=fake)
    assert r.status == "ok"
    assert "LPK25" in r.detail


def test_check_ports_no_match_fails_with_hint():
    fake = lambda: {"inputs": ["Some Synth"], "outputs": ["Some Synth"]}
    r = dg.check_ports(False, "LPK25", None, None, list_ports_fn=fake)
    assert r.status == "fail"
    assert r.hint and "--port" in r.hint


def test_check_ports_none_present_fails():
    fake = lambda: {"inputs": [], "outputs": []}
    r = dg.check_ports(False, "LPK25", None, None, list_ports_fn=fake)
    assert r.status == "fail"


def test_check_ports_explicit_names_bypass_match():
    fake = lambda: {"inputs": ["weird-in"], "outputs": ["weird-out"]}
    r = dg.check_ports(False, "LPK25", "weird-in", "weird-out", list_ports_fn=fake)
    assert r.status == "ok"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_diagnostics.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'lpk25.diagnostics'`.

- [ ] **Step 3: Write the module**

Create `src/lpk25/diagnostics.py`:

```python
"""Diagnostics for `lpk25 doctor`: ordered, hardware-free check logic.

Each check returns a :class:`CheckResult`; :func:`run_diagnostics` runs them in
dependency order and marks downstream checks ``skip`` when a prerequisite is not
ok. This module never prints and never imports the real MIDI backend directly —
the CLI injects a ``device_factory`` — so every check is unit-testable.
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from typing import Callable, Literal, Optional

from . import protocol

Status = Literal["ok", "warn", "fail", "skip"]

INSTALL_HINT = "pip install 'lpk25[midi]'  (Linux: sudo apt-get install libasound2-dev first)"


@dataclass
class CheckResult:
    name: str
    status: Status
    detail: str
    hint: Optional[str] = None


def _module_present(name: str) -> bool:
    """True if an importable module of this name exists, without importing it."""
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):  # pragma: no cover - exotic import states
        return False


def _skip(name: str, prereq: str) -> CheckResult:
    return CheckResult(name, "skip", f"skipped: {prereq} not ok")


def check_backend(mock: bool = False) -> CheckResult:
    name = "MIDI backend"
    if mock:
        return CheckResult(name, "ok", "mock mode (no MIDI backend needed)")
    if not _module_present("mido"):
        return CheckResult(name, "fail", "mido not installed", INSTALL_HINT)
    if not _module_present("rtmidi"):
        return CheckResult(name, "fail", "python-rtmidi not installed", INSTALL_HINT)
    import mido

    ver = getattr(mido, "__version__", "?")
    return CheckResult(name, "ok", f"mido {ver}, python-rtmidi present")


def check_ports(
    mock: bool,
    port_match: str,
    in_port: str | None,
    out_port: str | None,
    list_ports_fn: Callable[[], dict] | None = None,
) -> CheckResult:
    name = "MIDI ports"
    if mock:
        return CheckResult(name, "ok", "mock mode")
    if list_ports_fn is None:
        from .transport import list_ports as list_ports_fn  # lazy: needs the backend
    from .transport import _match_port

    ports = list_ports_fn()
    ins, outs = ports["inputs"], ports["outputs"]
    if not ins or not outs:
        return CheckResult(
            name, "fail",
            f"inputs={ins or 'none'}, outputs={outs or 'none'}",
            "No MIDI ports — check the USB cable/hub and that the device is on.",
        )
    in_name = in_port or _match_port(ins, port_match)
    out_name = out_port or _match_port(outs, port_match)
    if in_name is None or out_name is None:
        return CheckResult(
            name, "fail",
            f"no port matching {port_match!r}; inputs={ins}, outputs={outs}",
            "Pass --port SUBSTR (or --in-port/--out-port) to choose a port.",
        )
    return CheckResult(name, "ok", f"matched in/out: {in_name} / {out_name}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_diagnostics.py -q`
Expected: PASS (8 passed).

- [ ] **Step 5: Lint**

Run: `.venv/bin/ruff check src/lpk25/diagnostics.py tests/test_diagnostics.py`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add src/lpk25/diagnostics.py tests/test_diagnostics.py
git commit -m "feat(doctor): diagnostics core — backend & ports checks"
```

---

### Task 2: device checks + orchestrator — `check_device`, `check_roundtrip`, `run_diagnostics`

**Files:**
- Modify: `src/lpk25/diagnostics.py`
- Test: `tests/test_diagnostics.py`

**Interfaces:**
- Consumes: `lpk25.discovery.detect_model(transport) -> int | None`; `lpk25.protocol` (`MODEL_LPK25_MK1`, `build_get_active_program`, `parse_frame`, `ProtocolConfig`, `ProtocolError`); `lpk25.device.Device` (`.transport`, `.backup() -> str`, `.get_program(slot) -> Program`, `.send_program(program, verify=True, backup_dir=None) -> WriteResult`).
- Produces:
  - `check_device(transport, expected_model: int = protocol.MODEL_LPK25_MK1) -> CheckResult`
  - `check_roundtrip(device, slot: int = 1) -> CheckResult`
  - `run_diagnostics(*, mock, port_match, in_port, out_port, model, roundtrip, device_factory, list_ports_fn=None) -> list[CheckResult]`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_diagnostics.py`:

```python
from lpk25.device import Device
from lpk25.transport import MockTransport


class _SilentTransport:
    def send(self, frame): pass
    def receive(self, timeout=1.0): return None
    def request(self, frame, timeout=1.0): return None
    def close(self): pass


def test_check_device_responds_default_model_ok():
    r = dg.check_device(MockTransport(model=0x76))
    assert r.status == "ok"
    assert "0x76" in r.detail


def test_check_device_wrong_model_warns():
    r = dg.check_device(MockTransport(model=0x77), expected_model=0x76)
    assert r.status == "warn"
    assert "--model" in (r.hint or "")


def test_check_device_silent_fails():
    r = dg.check_device(_SilentTransport())
    assert r.status == "fail"
    assert "asleep" in (r.hint or "")


def test_check_roundtrip_ok(tmp_path):
    dev = Device(MockTransport())
    dev.backup_dir = str(tmp_path)
    r = dg.check_roundtrip(dev)
    assert r.status == "ok"
    assert "verified" in r.detail


def test_run_diagnostics_all_ok_mock(tmp_path):
    def factory():
        dev = Device(MockTransport())
        dev.backup_dir = str(tmp_path)
        return dev

    results = dg.run_diagnostics(
        mock=True, port_match="LPK25", in_port=None, out_port=None,
        model=None, roundtrip=True, device_factory=factory,
    )
    assert [r.status for r in results] == ["ok", "ok", "ok", "ok"]


def test_run_diagnostics_backend_fail_skips_downstream(monkeypatch):
    monkeypatch.setattr(dg, "_module_present", lambda name: False)
    calls = []
    results = dg.run_diagnostics(
        mock=False, port_match="LPK25", in_port=None, out_port=None,
        model=None, roundtrip=True,
        device_factory=lambda: calls.append(1),  # must never be called
    )
    assert results[0].status == "fail"
    assert [r.status for r in results[1:]] == ["skip", "skip", "skip"]
    assert calls == []


def test_run_diagnostics_roundtrip_off_is_skip(tmp_path):
    def factory():
        dev = Device(MockTransport())
        dev.backup_dir = str(tmp_path)
        return dev

    results = dg.run_diagnostics(
        mock=True, port_match="LPK25", in_port=None, out_port=None,
        model=None, roundtrip=False, device_factory=factory,
    )
    assert results[3].status == "skip"
    assert "--roundtrip" in results[3].detail
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_diagnostics.py -q`
Expected: FAIL — `AttributeError: module 'lpk25.diagnostics' has no attribute 'check_device'`.

- [ ] **Step 3: Implement the device checks + orchestrator**

Append to `src/lpk25/diagnostics.py`:

```python
def _active_program(transport, model: int) -> int | None:
    """Best-effort, read-only get-active-program. None if unsupported/no reply."""
    try:
        cfg = protocol.ProtocolConfig(model=model)
        reply = transport.request(protocol.build_get_active_program(cfg))
        if reply is None:
            return None
        return protocol.parse_frame(reply).slot
    except (protocol.ProtocolError, OSError):
        return None


def check_device(transport, expected_model: int = protocol.MODEL_LPK25_MK1) -> CheckResult:
    name = "Device responds"
    from .discovery import detect_model

    model = detect_model(transport)
    if model is None:
        return CheckResult(
            name, "fail", "no reply to device inquiry or model probe",
            "Device may be asleep or disconnected — press a key to wake it, "
            "re-seat the USB cable, or check --port.",
        )
    if model != expected_model:
        return CheckResult(
            name, "warn",
            f"model 0x{model:02X} answered (expected 0x{expected_model:02X})",
            f"Pass --model 0x{model:02X} if this is the device you mean to use.",
        )
    detail = f"model 0x{model:02X} (LPK25 mk1)"
    active = _active_program(transport, model)
    if active is not None:
        detail += f", active program {active}"
    return CheckResult(name, "ok", detail)


def check_roundtrip(device, slot: int = 1) -> CheckResult:
    name = "Write round-trip"
    try:
        backup_path = device.backup()
    except Exception as exc:  # noqa: BLE001 - reported as a failed check, not a crash
        return CheckResult(name, "fail", f"backup failed: {exc}",
                           "Check that the backup directory is writable.")
    try:
        prog = device.get_program(slot)
        device.send_program(prog, verify=True, backup_dir=None)
    except Exception as exc:  # noqa: BLE001 - DeviceError/VerificationError -> failed check
        return CheckResult(name, "fail", f"slot {slot}: {exc}")
    return CheckResult(
        name, "ok",
        f"slot {slot} write verified, no net change; backup at {backup_path}",
    )


def run_diagnostics(
    *,
    mock: bool,
    port_match: str,
    in_port: str | None,
    out_port: str | None,
    model: int | None,
    roundtrip: bool,
    device_factory: Callable[[], object],
    list_ports_fn: Callable[[], dict] | None = None,
) -> list[CheckResult]:
    results: list[CheckResult] = []

    backend = check_backend(mock)
    results.append(backend)

    if backend.status == "ok":
        ports = check_ports(mock, port_match, in_port, out_port, list_ports_fn)
    else:
        ports = _skip("MIDI ports", backend.name)
    results.append(ports)

    expected = model if model is not None else protocol.MODEL_LPK25_MK1
    device = None
    if ports.status == "ok":
        try:
            device = device_factory()
            dev_result = check_device(device.transport, expected)
        except Exception as exc:  # noqa: BLE001 - opening the port can fail
            dev_result = CheckResult(
                "Device responds", "fail", f"could not open device: {exc}",
                "Check --port and that no other application holds the MIDI port.",
            )
    else:
        dev_result = _skip("Device responds", ports.name)
    results.append(dev_result)

    if not roundtrip:
        rt = CheckResult("Write round-trip", "skip", "pass --roundtrip to test the write path")
    elif dev_result.status in ("ok", "warn") and device is not None:
        rt = check_roundtrip(device)
    else:
        rt = _skip("Write round-trip", "Device responds")
    results.append(rt)

    if device is not None:
        try:
            device.transport.close()
        except Exception:  # noqa: BLE001 - best-effort cleanup
            pass

    return results
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_diagnostics.py -q`
Expected: PASS (15 passed).

- [ ] **Step 5: Lint**

Run: `.venv/bin/ruff check src/lpk25/diagnostics.py tests/test_diagnostics.py`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add src/lpk25/diagnostics.py tests/test_diagnostics.py
git commit -m "feat(doctor): device + round-trip checks and orchestrator"
```

---

### Task 3: CLI wiring + docs — `cmd_doctor`, `doctor` subparser, README/feature-list

**Files:**
- Modify: `src/lpk25/cli.py` (add `cmd_doctor` near the other commands; register the subparser in `build_parser`)
- Create: `tests/test_cli_doctor.py`
- Modify: `README.md`, `docs/feature-list.md`

**Interfaces:**
- Consumes: `lpk25.diagnostics.run_diagnostics(...)`, `cli._make_device(args)`, global args `args.mock/port/in_port/out_port/model` and the new `args.roundtrip`.
- Produces: `cmd_doctor(args: argparse.Namespace) -> int`; CLI command `lpk25 doctor [--roundtrip]`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_cli_doctor.py`:

```python
from lpk25 import cli, diagnostics
from lpk25.device import Device
from lpk25.transport import MockTransport


def test_doctor_mock_all_green(capsys):
    rc = cli.main(["--mock", "doctor"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "All checks passed." in out
    assert "✅" in out
    assert "Device responds" in out


def test_doctor_mock_roundtrip(capsys, monkeypatch, tmp_path):
    def fake_make_device(args):
        dev = Device(MockTransport())
        dev.backup_dir = str(tmp_path)
        return dev

    monkeypatch.setattr(cli, "_make_device", fake_make_device)
    rc = cli.main(["--mock", "doctor", "--roundtrip"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Write round-trip" in out
    assert "verified" in out


def test_doctor_backend_missing_exits_nonzero(capsys, monkeypatch):
    monkeypatch.setattr(diagnostics, "_module_present", lambda name: False)
    rc = cli.main(["doctor"])  # not --mock: real backend path, simulated missing
    out = capsys.readouterr().out
    assert rc == 1
    assert "❌" in out
    assert "pip install 'lpk25[midi]'" in out
    assert "issue" in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_cli_doctor.py -q`
Expected: FAIL — argparse exits with "invalid choice: 'doctor'".

- [ ] **Step 3: Add `cmd_doctor` to `cli.py`**

Insert this function in `src/lpk25/cli.py` immediately before `def cmd_ports` (after `_preview`, around line 70):

```python
_DOCTOR_MARKS = {"ok": "✅", "warn": "⚠️", "fail": "❌", "skip": "⏭"}


def cmd_doctor(args: argparse.Namespace) -> int:
    """Run the MIDI-setup / connectivity checklist and exit non-zero on failure."""
    from . import diagnostics

    results = diagnostics.run_diagnostics(
        mock=getattr(args, "mock", False),
        port_match=args.port,
        in_port=args.in_port,
        out_port=args.out_port,
        model=args.model,
        roundtrip=getattr(args, "roundtrip", False),
        device_factory=lambda: _make_device(args),
    )
    print("lpk25 doctor — MIDI setup & device connectivity\n")
    fails = 0
    for r in results:
        print(f"{_DOCTOR_MARKS[r.status]} {r.name:<16} {r.detail}")
        if r.hint and r.status in ("warn", "fail"):
            print(f"   → {r.hint}")
        if r.status == "fail":
            fails += 1
    print()
    if fails:
        print(f"{fails} issue{'s' if fails != 1 else ''} found.")
        return 1
    print("All checks passed.")
    return 0
```

- [ ] **Step 4: Register the subparser**

In `build_parser`, immediately after the `config` subparser block (after line 635, before the `completion` block), add:

```python
    doc = sub.add_parser("doctor", help="diagnose MIDI setup and device connectivity")
    doc.add_argument(
        "--roundtrip", action="store_true",
        help="also test the write path (safe: backs up, writes identical bytes back, verifies)",
    )
    doc.set_defaults(func=cmd_doctor)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_cli_doctor.py -q`
Expected: PASS (3 passed).

- [ ] **Step 6: Run the whole suite + lint**

Run: `.venv/bin/python -m pytest -q && .venv/bin/ruff check src/ tests/`
Expected: all tests pass, no lint errors.

- [ ] **Step 7: Document the command**

In `README.md`, add this line to the `## Usage` code block (after the `lpk25 config` line near line 51):

```bash
lpk25 doctor [--roundtrip]  # diagnose MIDI setup + connectivity (✅/❌ checklist)
```

And add a bullet to the `## Features` list (after the "Discovery tools" bullet):

```markdown
- **`doctor` self-diagnostic** — one ordered checklist (backend → ports → device →
  optional write round-trip) with ✅/❌ and a fix hint per step; non-zero exit on failure.
```

In `docs/feature-list.md`, add a row/bullet consistent with the existing format describing `lpk25 doctor` (ordered checks; `--roundtrip` opt-in write test; non-zero exit on required failure). Match whatever table/list style that file already uses.

- [ ] **Step 8: Commit**

```bash
git add src/lpk25/cli.py tests/test_cli_doctor.py README.md docs/feature-list.md
git commit -m "feat(doctor): wire up `lpk25 doctor` CLI command + docs"
```

---

## Self-Review

**Spec coverage:**
- Ordered checks backend → ports → device → roundtrip — Tasks 1 & 2 (`run_diagnostics`). ✅
- ✅/❌ per step + hints — Task 3 (`cmd_doctor` formatting). ✅
- Non-zero exit on required failure — Task 3 (`fails` → `return 1`); exit rule in Global Constraints. ✅
- `--roundtrip` only after a backup, byte-identical, never leaves device changed — Task 2 (`check_roundtrip`: `device.backup()` then identical `send_program(..., backup_dir=None)` with read-back verify). ✅
- Model mismatch = warn; silent = fail — Task 2 (`check_device`). ✅
- Hardware-free testability — `diagnostics.py` injects `device_factory`/`list_ports_fn`; tests use `MockTransport`. ✅
- `--mock doctor` runnable end-to-end — Task 3 test `test_doctor_mock_all_green`. ✅

**Placeholder scan:** none — all steps carry full code and exact commands. The only prose-only step is the `docs/feature-list.md` edit (Step 7), intentionally deferred to that file's existing format.

**Type consistency:** `CheckResult(name, status, detail, hint)` used identically in all tasks; `run_diagnostics` keyword signature matches both its tests and the `cmd_doctor` call site; `check_device(transport, expected_model)` and `check_roundtrip(device, slot)` signatures match their call sites in `run_diagnostics`.
