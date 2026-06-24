"""Pure (curses-free) state + logic for the TUI editor.

Holds an edited copy and an original copy of all four programs, a grid cursor,
and every edit/device/library action. The curses layer talks only to this
class, so the whole editor is exercised offline with Device(MockTransport()).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .. import codec, library, render
from ..device import Device
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
    def __init__(self, dev: Device, preset: Preset, active_slot: int | None):
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
        prog = self._edited[self.slot_idx]
        new_val = self._stepped(f, prog.values.get(f.name), delta)
        prog.raw = codec.encode_program({f.name: new_val}, prog.raw)
        prog.values[f.name] = new_val

    def set_value(self, text: str) -> None:
        f = self.focused_field()
        if f.kind in ("bool", "enum"):
            raise codec.CodecError(f"{f.name} is not a numeric field (use -/+)")
        try:
            v = int(text)
        except ValueError as e:
            raise codec.CodecError(f"{f.name}: not a number: {text!r}") from e
        prog = self._edited[self.slot_idx]
        prog.raw = codec.encode_program({f.name: v}, prog.raw)   # validates range AND updates raw
        prog.values[f.name] = v

    def undo_slot(self) -> None:
        i = self.slot_idx
        self._edited[i] = Program.from_payload(self._original[i].slot, self._original[i].raw)

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
