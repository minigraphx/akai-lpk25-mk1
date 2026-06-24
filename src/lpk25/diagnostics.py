"""Diagnostics for `lpk25 doctor`: ordered, hardware-free check logic.

Each check returns a :class:`CheckResult`; :func:`run_diagnostics` runs them in
dependency order and marks downstream checks ``skip`` when a prerequisite is not
ok. This module never prints and never imports the real MIDI backend directly —
the CLI injects a ``device_factory`` — so every check is unit-testable.
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from typing import Callable, Literal

from . import protocol

Status = Literal["ok", "warn", "fail", "skip"]

INSTALL_HINT = (
    "pip install 'lpk25[midi]'  "
    "(Linux: sudo apt-get install libasound2-dev first)"
)


@dataclass
class CheckResult:
    name: str
    status: Status
    detail: str
    hint: str | None = None


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
        from .transport import list_ports as list_ports_fn  # lazy: needs backend
    from .transport import _match_port

    ports = list_ports_fn()
    ins, outs = ports["inputs"], ports["outputs"]
    if not ins or not outs:
        return CheckResult(
            name,
            "fail",
            f"inputs={ins or 'none'}, outputs={outs or 'none'}",
            "No MIDI ports — check the USB cable/hub and that the device is on.",
        )
    in_name = in_port or _match_port(ins, port_match)
    out_name = out_port or _match_port(outs, port_match)
    if in_name is None or out_name is None:
        return CheckResult(
            name,
            "fail",
            f"no port matching {port_match!r}; inputs={ins}, outputs={outs}",
            "Pass --port SUBSTR (or --in-port/--out-port) to choose a port.",
        )
    return CheckResult(name, "ok", f"matched in/out: {in_name} / {out_name}")


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


def check_device(
    transport, expected_model: int = protocol.MODEL_LPK25_MK1
) -> CheckResult:
    """Check that a device responds and matches the expected model."""
    from .discovery import detect_model

    name = "Device responds"
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
    """Check that a device round-trips a program write correctly."""
    name = "Write round-trip"
    try:
        backup_path = device.backup()
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            name, "fail", f"backup failed: {exc}",
            "Check that the backup directory is writable.",
        )
    try:
        prog = device.get_program(slot)
        device.send_program(prog, verify=True, backup_dir=None)
    except Exception as exc:  # noqa: BLE001
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
    """Run all diagnostics checks in dependency order, skipping downstream on
    failure."""
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
        except Exception as exc:  # noqa: BLE001
            dev_result = CheckResult(
                "Device responds", "fail", f"could not open device: {exc}",
                "Check --port and that no other application holds the MIDI "
                "port.",
            )
    else:
        dev_result = _skip("Device responds", ports.name)
    results.append(dev_result)

    if not roundtrip:
        rt = CheckResult(
            "Write round-trip", "skip",
            "pass --roundtrip to test the write path",
        )
    elif dev_result.status in ("ok", "warn") and device is not None:
        rt = check_roundtrip(device)
    else:
        rt = _skip("Write round-trip", "Device responds")
    results.append(rt)

    if device is not None:
        try:
            device.transport.close()
        except Exception:  # noqa: BLE001
            pass

    return results
