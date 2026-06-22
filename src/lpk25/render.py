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
