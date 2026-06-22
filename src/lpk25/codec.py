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

# Enumerations (labels <-> device byte values). Order is provisional.
ARP_MODES: dict[int, str] = {
    0: "up",
    1: "down",
    2: "exclusive",
    3: "inclusive",
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
    program/slot echo). ``kind`` is one of ``int``/``bool``/``enum``.
    For ``int`` fields the semantic value is ``byte + offset``.
    """

    name: str
    index: int
    kind: str = "int"
    offset: int = 0
    lo: int | None = None
    hi: int | None = None
    enum: dict[int, str] | None = None
    verified: bool = False

    def decode(self, raw: bytes) -> Any:
        b = raw[self.index]
        if self.kind == "bool":
            return bool(b)
        if self.kind == "enum":
            assert self.enum is not None
            return self.enum.get(b, b)  # unknown codes pass through as ints
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
        byte = v - self.offset
        if not (0 <= byte <= 0x7F):
            raise CodecError(f"{self.name}={v} encodes to non-7-bit byte {byte}")
        buf[self.index] = byte


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
    # idx 2 = 05 fits "octave +1" (you'd pressed octave-up); idx 3 = 0x0c = 12
    # fits transpose centred at 0. Plausible but UNCONFIRMED (no clean baseline).
    Field("midi_channel", index=1, kind="int", offset=1, lo=1, hi=16),
    Field("keybed_octave", index=2, kind="int", offset=0, lo=-4, hi=4),
    Field("transpose", index=3, kind="int", offset=0, lo=-12, hi=12),
    # CONFIRMED (2026-06-22, real hardware): Arp On/Off toggles exactly this byte.
    Field("arp_enabled", index=4, kind="bool", verified=True),
    # --- everything below is MISALIGNED/unconfirmed; do not trust decoded values.
    Field("arp_latch", index=5, kind="bool"),
    Field("arp_mode", index=6, kind="enum", enum=ARP_MODES),
    Field("time_division", index=7, kind="enum", enum=TIME_DIVISIONS),
    Field("clock", index=8, kind="enum", enum=CLOCK_SOURCES),
    Field("tempo_taps", index=9, kind="int", offset=0, lo=2, hi=4),
    Field("tempo", index=10, kind="int", offset=0, lo=30, hi=240),
    # Arp octave is 0-3 (hardware labels ARP OCT 0-3 and editor guide).
    Field("arp_octave", index=11, kind="int", offset=0, lo=0, hi=3),
]


def decode_program(payload: bytes, fields: list[Field] | None = None) -> dict[str, Any]:
    """Decode known fields from a program payload. Fields whose index is beyond
    the payload length are skipped (the layout/length is provisional)."""
    fields = fields if fields is not None else LPK25_MK1_FIELDS
    out: dict[str, Any] = {}
    for f in fields:
        if f.index < len(payload):
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
