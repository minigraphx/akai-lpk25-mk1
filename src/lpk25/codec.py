"""Decode/encode an LPK25 mk1 program payload to/from semantic values.

IMPORTANT — the field map below is **provisional**. We could not capture the
official editor, so offsets and encodings are derived from the LPK25 MK2 layout
(minus swing) and the official editor's documented parameter list. Every field
is flagged ``verified=False`` until confirmed against real hardware (via the
round-trip and behavioural-oracle methods described in the design doc).

Safety: decoding always keeps the full raw payload, and encoding patches only
the known fields back into a copy of that raw payload. Bytes we don't understand
are preserved verbatim, so a read -> write round-trip is byte-exact even while
the field map is incomplete.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Arp modes. CONFIRMED on real hardware (2026-06-22): Up=0 and Exclusive=3
# (the codec previously had Inclusive/Exclusive swapped). The remaining order
# follows the official editor list (Up, Down, Inclusive, Exclusive, Order,
# Random); Down/Inclusive/Order/Random codes are inferred, not yet observed.
ARP_MODES: dict[int, str] = {
    0: "up",
    1: "down",
    2: "inclusive",
    3: "exclusive",
    4: "order",
    5: "random",
}

TIME_DIVISIONS: dict[int, str] = {
    0: "1/4",
    1: "1/4T",
    2: "1/8",
    3: "1/8T",
    4: "1/16",
    5: "1/16T",
    6: "1/32",
    7: "1/32T",
}

CLOCK_SOURCES: dict[int, str] = {0: "internal", 1: "external"}


class CodecError(ValueError):
    """Raised when a value is out of range or an enum label is unknown."""


@dataclass
class Field:
    """One decodable field within the program payload.

    ``index`` is the byte offset into the data payload (where index 0 is the
    program/slot echo). ``kind`` is one of ``int``/``bool``/``enum``/``u14``.
    For ``int`` fields the semantic value is ``byte + offset``. ``u14`` is a
    14-bit big-endian value split across two 7-bit bytes at ``index`` (high) and
    ``index+1`` (low): ``value = (hi << 7) | lo`` — used for tempo (30-240).
    """

    name: str
    index: int
    kind: str = "int"
    offset: int = 0
    lo: int | None = None
    hi: int | None = None
    enum: dict[int, str] | None = None
    verified: bool = False

    @property
    def span(self) -> int:
        """Number of payload bytes this field occupies."""
        return 2 if self.kind == "u14" else 1

    def decode(self, raw: bytes) -> Any:
        b = raw[self.index]
        if self.kind == "bool":
            return bool(b)
        if self.kind == "enum":
            assert self.enum is not None
            return self.enum.get(b, b)  # unknown codes pass through as ints
        if self.kind == "u14":
            return ((b << 7) | raw[self.index + 1]) + self.offset
        return b + self.offset

    def encode_into(self, buf: bytearray, value: Any) -> None:
        if self.kind == "bool":
            buf[self.index] = 1 if value else 0
            return
        if self.kind == "enum":
            assert self.enum is not None
            if isinstance(value, int):
                code = value
            else:
                rev = {v: k for k, v in self.enum.items()}
                if value not in rev:
                    raise CodecError(f"{self.name}: unknown value {value!r}")
                code = rev[value]
            buf[self.index] = code & 0x7F
            return
        v = int(value)
        if self.lo is not None and self.hi is not None and not (self.lo <= v <= self.hi):
            raise CodecError(f"{self.name}={v} out of range [{self.lo}, {self.hi}]")
        raw_value = v - self.offset
        if self.kind == "u14":
            if not (0 <= raw_value <= 0x3FFF):
                raise CodecError(f"{self.name}={v} encodes to non-14-bit value {raw_value}")
            buf[self.index] = (raw_value >> 7) & 0x7F
            buf[self.index + 1] = raw_value & 0x7F
            return
        if not (0 <= raw_value <= 0x7F):
            raise CodecError(f"{self.name}={v} encodes to non-7-bit byte {raw_value}")
        buf[self.index] = raw_value


# LPK25 mk1 program field map. data[0] is the slot echo, handled separately by
# the model layer. The real payload is 13 bytes (idx 0-12), confirmed from a
# hardware dump on 2026-06-22; a sample (program 1, octave +1, arp off) is:
#   01 00 05 0c 00 03 05 00 00 03 00 1e 00
#    0  1  2  3  4  5  6  7  8  9 10 11 12
#
# CONFIRMED so far: idx 0 = slot echo; idx 4 = arp on/off (toggling it flipped
# only this byte 00<->01). Everything from idx 5 on is still PROVISIONAL and the
# old MK2-derived ordering below is known to be MISALIGNED past idx 4 (it decodes
# real dumps to nonsense, e.g. tempo=0, arp_octave=30). Those fields stay
# verified=False and decoded values must not be trusted until each is confirmed
# one-at-a-time via the change-one-byte-and-diff method. idx 12 is unmapped.
LPK25_MK1_FIELDS: list[Field] = [
    # CONFIRMED (2026-06-23, real hardware): wrote channel 10 (byte 9) to slot 1,
    # played keys, and every note-on transmitted on channel 10 (status 0x99).
    # Encoding: value = byte + 1 (byte 0 -> channel 1).
    Field("midi_channel", index=1, kind="int", offset=1, lo=1, hi=16, verified=True),
    # CONFIRMED (2026-06-23, real hardware): wrote transpose +12 (byte 24) to
    # slot 1; played keys all shifted up 12 semitones (48,60,72,84 -> 60,72,84,
    # 96). Encoding: value = byte - 12 (byte 12 -> 0), centred like octave.
    # CONFIRMED (2026-06-22, real hardware): octave up/down moves only this byte;
    # value = byte - 4 (byte 0x00 = -4, 0x04 = 0, 0x08 = +4; clamps, no wrap).
    Field("keybed_octave", index=2, kind="int", offset=-4, lo=-4, hi=4, verified=True),
    Field("transpose", index=3, kind="int", offset=-12, lo=-12, hi=12, verified=True),
    # CONFIRMED (2026-06-22, real hardware): Arp On/Off toggles exactly this byte.
    Field("arp_enabled", index=4, kind="bool", verified=True),
    # CONFIRMED (2026-06-22/23, real hardware): arp mode lives here (NOT idx 6 as
    # the MK2-derived guess had it). Up=0 and Exclusive=3 both observed via a
    # precise hold-ARP+key gesture. GOTCHA: codes follow the *editor* order
    # (Up,Down,Inclusive,Exclusive,Order,Random) NOT the keybed label order
    # (which prints excl before incl) -- so Exclusive=3, Inclusive=2.
    Field("arp_mode", index=5, kind="enum", enum=ARP_MODES, verified=True),
    # CONFIRMED (2026-06-23, real hardware): hold-ARP + a time-division key moves
    # only this byte; "1/8" -> 2, matching the standard order in TIME_DIVISIONS.
    Field("time_division", index=6, kind="enum", enum=TIME_DIVISIONS, verified=True),
    # CONFIRMED (2026-06-23, real hardware): writing idx 7 = 1 (with arp on)
    # silenced all output -- the arp stalled waiting for an external clock that
    # wasn't present. So 0 = internal, 1 = external. Restoring 0 brought the arp
    # back. (This is the clock byte, NOT latch as first guessed.)
    Field("clock", index=7, kind="enum", enum=CLOCK_SOURCES, verified=True),
    # CONFIRMED (2026-06-23, real hardware): writing idx 8 = 1 made a single key
    # tap arpeggiate continuously after release (103 notes over a 14s window vs.
    # the latch-off baseline that stopped on release). So this is arp_latch (0/1).
    Field("arp_latch", index=8, kind="bool", verified=True),
    # CONFIRMED (2026-06-23, real hardware): idx 9 = tempo_taps = how many TAP
    # TEMPO presses are needed to set a new tempo. With idx9=2, two taps changed
    # the tempo; with idx9=4, two taps were ignored but four taps changed it.
    # Direct encoding: value = number of taps (2-4).
    Field("tempo_taps", index=9, kind="int", offset=0, lo=2, hi=4, verified=True),
    # CONFIRMED (2026-06-23, real hardware): tempo is a 14-bit value spanning
    # idx 10 (high) + idx 11 (low): bpm = (idx10<<7)|idx11. A fast tap pushed it
    # to (1<<7)|98 = 226 BPM, with idx 10 ticking 00->01. Range 30-240.
    Field("tempo", index=10, kind="u14", lo=30, hi=240, verified=True),
    # CONFIRMED (2026-06-23, real hardware): hold-ARP + an arp-octave key moves
    # only this trailing byte; "oct 3" -> 3. Direct 0-3 encoding.
    Field("arp_octave", index=12, kind="int", offset=0, lo=0, hi=3, verified=True),
    # All 13 program bytes mapped and CONFIRMED on real hardware (2026-06-23).
]


def decode_program(payload: bytes, fields: list[Field] | None = None) -> dict[str, Any]:
    """Decode known fields from a program payload. Fields whose index is beyond
    the payload length are skipped (the layout/length is provisional)."""
    fields = fields if fields is not None else LPK25_MK1_FIELDS
    out: dict[str, Any] = {}
    for f in fields:
        if f.index + f.span <= len(payload):
            out[f.name] = f.decode(payload)
    return out


def encode_program(
    values: dict[str, Any],
    raw: bytes,
    fields: list[Field] | None = None,
) -> bytes:
    """Patch ``values`` into a copy of ``raw`` and return the new payload.

    Only known fields are written; everything else in ``raw`` is preserved, so
    unknown bytes survive a round trip untouched."""
    fields = fields if fields is not None else LPK25_MK1_FIELDS
    by_name = {f.name: f for f in fields}
    buf = bytearray(raw)
    for name, value in values.items():
        f = by_name.get(name)
        if f is None:
            raise CodecError(f"unknown field {name!r}")
        if f.index >= len(buf):
            raise CodecError(f"field {name!r} at index {f.index} beyond payload ({len(buf)})")
        f.encode_into(buf, value)
    return bytes(buf)


def all_verified(fields: list[Field] | None = None) -> bool:
    fields = fields if fields is not None else LPK25_MK1_FIELDS
    return all(f.verified for f in fields)


@dataclass
class ByteChange:
    """One differing byte between two program payloads.

    ``old``/``new`` are the byte values (or ``None`` if that payload is shorter
    than ``index``). ``field``/``verified`` describe the mapped field, if any.
    """

    index: int
    old: int | None
    new: int | None
    field: str | None = None
    verified: bool = False


def diff_payloads(
    a: bytes, b: bytes, fields: list[Field] | None = None
) -> list[ByteChange]:
    """Return the byte positions where two program payloads differ, annotated
    with the mapped field name (if known). The core of the ``lpk25 diff`` tool
    used to map fields by changing one device setting at a time."""
    fields = fields if fields is not None else LPK25_MK1_FIELDS
    # Map every byte a field occupies (multi-byte fields cover index..index+span-1).
    by_index = {f.index + k: f for f in fields for k in range(f.span)}
    changes: list[ByteChange] = []
    for i in range(max(len(a), len(b))):
        av = a[i] if i < len(a) else None
        bv = b[i] if i < len(b) else None
        if av != bv:
            f = by_index.get(i)
            changes.append(
                ByteChange(i, av, bv, f.name if f else None, bool(f and f.verified))
            )
    return changes
