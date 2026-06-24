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
