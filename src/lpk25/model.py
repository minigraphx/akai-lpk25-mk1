"""Data model for LPK25 mk1 programs and presets, with JSON (de)serialisation.

A :class:`Program` keeps both the decoded, human-friendly field values and the
full raw payload. Saving/loading uses JSON by default (human-readable, diffable,
hand-editable); the raw bytes are retained as hex so a round trip is byte-exact
even where the field map is incomplete.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from . import codec

SCHEMA_VERSION = 1


@dataclass
class Program:
    """A single LPK25 program (one of 4 slots)."""

    slot: int
    values: dict[str, Any] = field(default_factory=dict)
    raw: bytes = b""

    @classmethod
    def from_payload(cls, slot: int, payload: bytes) -> Program:
        return cls(slot=slot, values=codec.decode_program(payload), raw=bytes(payload))

    def to_payload(self) -> bytes:
        """Re-encode known fields onto the preserved raw payload.

        If the values are unchanged from what was decoded, the original raw bytes
        are returned verbatim (byte-exact backup/restore, independent of the
        provisional field map)."""
        if not self.raw:
            raise ValueError("cannot encode a program with no raw template payload")
        if self.values == codec.decode_program(self.raw):
            return self.raw
        return codec.encode_program(self.values, self.raw)

    def reslot(self, dst: int) -> Program:
        """Return a copy of this program addressed to slot ``dst``.

        Rewrites the slot-echo byte (payload[0]) to ``dst`` so a cross-slot write
        reads back identically — the device echoes the target slot in byte 0."""
        if not self.raw:
            raise ValueError("cannot reslot a program with no raw payload")
        return Program.from_payload(dst, bytes([dst]) + self.raw[1:])

    def to_dict(self) -> dict[str, Any]:
        return {
            "slot": self.slot,
            "values": dict(self.values),
            "raw_hex": self.raw.hex(),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Program:
        raw = bytes.fromhex(d.get("raw_hex", "")) if d.get("raw_hex") else b""
        return cls(slot=int(d["slot"]), values=dict(d.get("values", {})), raw=raw)


@dataclass
class Preset:
    """A full backup/restore unit: up to 4 programs plus optional globals."""

    programs: list[Program] = field(default_factory=list)
    globals_raw: bytes | None = None
    device_model: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "device": "akai-lpk25-mk1",
            "device_model": self.device_model,
            "programs": [p.to_dict() for p in self.programs],
            "globals_hex": self.globals_raw.hex() if self.globals_raw else None,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Preset:
        globals_hex = d.get("globals_hex")
        return cls(
            programs=[Program.from_dict(p) for p in d.get("programs", [])],
            globals_raw=bytes.fromhex(globals_hex) if globals_hex else None,
            device_model=d.get("device_model"),
        )

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_json(cls, text: str) -> Preset:
        return cls.from_dict(json.loads(text))

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(self.to_json())

    @classmethod
    def load(cls, path: str) -> Preset:
        with open(path, encoding="utf-8") as fh:
            return cls.from_json(fh.read())
