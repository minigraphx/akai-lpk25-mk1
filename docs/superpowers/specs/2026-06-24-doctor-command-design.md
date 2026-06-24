# `lpk25 doctor` — Design Spec

**Issue:** [#6](https://github.com/minigraphx/akai-lpk25-mk1/issues/6) — Add `lpk25 doctor`
to diagnose MIDI setup and device connectivity.

**Status:** designed autonomously (user away from hardware). Decisions are marked
**[DECISION]** for review; deviations from the issue are called out at the end.

## Goal

One guided diagnostic command that checks the MIDI setup and device connectivity
for the LPK25 mk1 in order, prints a clear ✅/❌ line per check with an actionable
remediation hint, and exits non-zero when a *required* check fails. It replaces the
current "piece it together from errors across `ports`, `identify`, …" onboarding
experience and produces a copy-pasteable summary for bug reports.

## Motivation

First-run setup has several independent failure points, each surfacing as a
different error today:

- the MIDI backend (`mido` + `python-rtmidi`) isn't installed, or ALSA headers were
  missing when `python-rtmidi` tried to build;
- no MIDI ports, or none matching `LPK25` (wrong cable/hub, custom port name);
- the device is asleep or disconnected, so nothing answers;
- a different model byte answers (future firmware / wrong device).

`doctor` runs these as an ordered checklist so the *first* broken link is obvious.

## Architecture

Two layers, so the check logic is fully testable without hardware and without
terminal I/O:

### 1. `src/lpk25/diagnostics.py` — check logic (no printing)

Each check returns a `CheckResult`; an orchestrator runs them in dependency order.
The module never calls `print()` and never imports `MidoTransport` directly — the
CLI injects a transport/device factory. Pure data in, pure data out.

```python
Status = Literal["ok", "warn", "fail", "skip"]

@dataclass
class CheckResult:
    name: str                 # short label, e.g. "MIDI backend"
    status: Status
    detail: str               # one-line specifics, e.g. "model 0x76 (LPK25 mk1)"
    hint: str | None = None   # remediation, shown on warn/fail
```

**[DECISION] Exit code is derived from statuses, not a per-check `required` flag:**
`exit 1 if any result.status == "fail" else 0`. `warn` and `skip` never fail the
run. This keeps the model trivial: we only emit `fail` for genuinely required
breakage, an opt-out check (`--roundtrip` not requested) is `skip`, and a
prerequisite failure downstream is also `skip` (it was already reported once).

#### Checks, in order

1. **MIDI backend** — `check_backend(mock)`
   - `mock=True` → `ok`, detail "mock mode (no MIDI backend needed)".
   - else try to import `mido` and confirm a usable rtmidi backend. On
     `ImportError`/backend error → `fail`, hint:
     `pip install 'lpk25[midi]'  (Linux: sudo apt-get install libasound2-dev first)`.
     On success → `ok`, detail with the `mido` version when available.

2. **MIDI ports** — `check_ports(mock, port_match, in_port, out_port)`
   - `mock=True` → `ok`, "mock mode".
   - else list ports; require ≥1 input and ≥1 output; resolve the matched in/out
     (explicit `--in-port`/`--out-port`, else substring match of `port_match`).
     No match → `fail`, hint lists the available ports and suggests
     `--port`/`--in-port`/`--out-port`. Match → `ok`, detail names the matched ports.

3. **Device responds** — `check_device(transport, expected_model)`
   - read-only `identify()` + `probe_models()`.
   - a model answers and it is `0x76` → `ok`, detail
     "model 0x76 (LPK25 mk1)" plus the active program when readable.
   - a *different* model answers → **[DECISION] `warn`** (not fail): the device is
     reachable but not the expected model; hint suggests `--model 0x{m:02X}`.
   - nothing answers → `fail`, hint: device may be asleep or disconnected —
     press a key to wake it, re-seat USB, or check `--port`.

4. **Write round-trip** — `check_roundtrip(device)`, only with `--roundtrip`
   - back up all slots, read **[DECISION] slot 1**, write the *identical* payload
     back through the guarded write path (auto-verify reads it back), and confirm
     `verified` with zero net change.
   - `ok` → "slot 1 write verified, no net change; backup at <path>".
     verification mismatch / no reply → `fail` with the byte diff.
   - not requested → `skip`, "pass --roundtrip to test the write path".

#### Orchestrator — `run_diagnostics`

Runs backend → ports → device → roundtrip and **short-circuits**: when a
prerequisite is not `ok`, each downstream check is recorded as `skip`
("skipped: <prerequisite> not ok") rather than re-failing. It opens the
device/transport once (via the injected factory) only after backend+ports pass,
and always closes it. Returns `list[CheckResult]`.

The CLI injects: the port settings, and a `device_factory` that builds a real
`Device(MidoTransport(...))`. `check_device` uses `device.transport` for its
read-only probes; `check_roundtrip` uses the `Device`. Tests inject a `Device`
wrapping `MockTransport` and fakes for the backend/port probes — no hardware.

### 2. `src/lpk25/cli.py` — `cmd_doctor`

Builds the inputs from `args`, calls `run_diagnostics`, formats each result, and
maps the overall status to the process exit code. Registered as a top-level
command (`sub.add_parser("doctor", …)`) like `ports`/`identify`, inheriting the
global `--port`/`--in-port`/`--out-port`/`--model`/`--mock`. Adds one flag:
`--roundtrip`.

#### Output

Marks: `ok`=✅ `warn`=⚠️ `fail`=❌ `skip`=⏭. One line per check, an indented
`   → <hint>` under any warn/fail, then a footer.

```
lpk25 doctor — MIDI setup & device connectivity

✅ MIDI backend     mido 1.3.2, python-rtmidi present
✅ MIDI ports       matched in/out: LPK25:LPK25 MIDI 1 24:0
✅ Device responds  model 0x76 (LPK25 mk1), active program 1
⏭  Write round-trip  skipped (pass --roundtrip to test the write path)

All checks passed.
```

A failure run:

```
❌ MIDI backend     not installed
   → pip install 'lpk25[midi]'  (Linux: sudo apt-get install libasound2-dev first)
⏭  MIDI ports       skipped (MIDI backend not ok)
⏭  Device responds  skipped (MIDI backend not ok)
⏭  Write round-trip  skipped (Device responds not ok)

1 issue found.
```

Exit `1` (a required check failed).

## Error handling

- Every check catches its own expected exceptions (`TransportError`,
  `ProtocolError`, `DeviceError`, `ImportError`) and turns them into a
  `fail`/`warn` `CheckResult` — `doctor` never crashes with a traceback; that is
  the whole point of the command.
- The orchestrator guarantees the transport is closed even if a check raises an
  unexpected error.

## Testing

- `tests/test_diagnostics.py` — each check with injected fakes:
  backend present/absent; ports matched/unmatched/none; device answers `0x76` /
  answers a different model (warn) / silent (fail); roundtrip verified / mismatch.
  Orchestrator short-circuit (backend fail → all downstream `skip`). Exit mapping
  (any `fail` → nonzero) via a small helper.
- `tests/test_cli_doctor.py` — `lpk25 --mock doctor` → all green, rc 0;
  `--mock doctor --roundtrip` → roundtrip ok, rc 0; backend-missing simulated
  (monkeypatch) → rc 1 and the install hint present in output.

## Out of scope (YAGNI)

- `--json` machine-readable output (not in the acceptance criteria; easy to add
  later for bug reports if asked).
- Configurable round-trip slot — fixed to slot 1.
- Any auto-fixing — `doctor` only diagnoses.

## Deviations from the issue (for review)

1. **Model mismatch is `warn`, not `fail`.** The issue lists "model byte mismatch"
   as a failure point; a reachable-but-different model still means the cable and
   backend work, so it is reported loudly but does not set a nonzero exit. A
   *silent* device is the hard failure.
2. **Round-trip writes slot 1 only** (the issue says "a slot"), to minimise flash
   wear, behind a mandatory full backup, writing back byte-identical data.
