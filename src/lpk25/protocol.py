"""SysEx framing for the Akai LPK25 mk1 (and the mk1 device family).

The mk1 family (LPD8 mk1, LPK25 mk1, ...) uses frames of the form::

    F0 47 7F <model> <op> <len_hi> <len_lo> [data...] F7

where ``47`` is the Akai manufacturer id, ``7F`` the broadcast device id, and
``<model>`` identifies the specific product. Opcodes are consistent across the
family (verified for the LPD8 mk1, hypothesised for the LPK25 mk1):

    0x63  get program        request: data = [slot]
    0x61  send program       request: data = [slot, <payload...>] (no ack)
    0x62  activate program   request: data = [slot]
    0x64  get active program request: data = []  ; reply data = [slot]

The length is a 16-bit big-endian value split into two 7-bit bytes
(``value = (hi << 7) | lo``), keeping every byte inside the legal SysEx range.

Everything that might differ on the LPK25 mk1 (the model byte in particular)
lives in :class:`ProtocolConfig` so discovery findings are a config change, not
a code change.
"""

from __future__ import annotations

from dataclasses import dataclass, field

SYSEX_START = 0xF0
SYSEX_END = 0xF7

MANUFACTURER_AKAI = 0x47
DEVICE_BROADCAST = 0x7F

# Opcodes (consistent across the Akai mk1 family).
OP_GET_PROGRAM = 0x63
OP_SEND_PROGRAM = 0x61
OP_ACTIVATE_PROGRAM = 0x62
OP_GET_ACTIVE_PROGRAM = 0x64

# Known model bytes in this generation.
MODEL_LPD8_MK1 = 0x75

# The LPK25 mk1 model byte is unknown. 0x76 is a provisional best guess (LPD8 is
# 0x75 and Akai assigned adjacent ids in this generation); the Universal Device
# Inquiry should reveal the real value. Probe these candidates if unsure.
PROVISIONAL_MODEL_LPK25_MK1 = 0x76
MK1_MODEL_CANDIDATES: list[int] = [0x76, 0x77, 0x74, 0x73, 0x78, 0x79, 0x72, 0x7A, 0x75]


class ProtocolError(ValueError):
    """Raised when a SysEx frame cannot be parsed or is malformed."""


@dataclass
class ProtocolConfig:
    """Adjustable protocol parameters. Tweak ``model`` once discovery confirms it."""

    model: int = PROVISIONAL_MODEL_LPK25_MK1
    manufacturer: int = MANUFACTURER_AKAI
    device: int = DEVICE_BROADCAST


@dataclass
class Frame:
    """A parsed mk1-family SysEx frame."""

    manufacturer: int
    device: int
    model: int
    opcode: int
    data: bytes = field(default_factory=bytes)

    @property
    def slot(self) -> int | None:
        """First data byte, which is the program/slot number for program ops."""
        return self.data[0] if self.data else None


def _encode_length(n: int) -> bytes:
    if n < 0 or n > (0x7F << 7 | 0x7F):
        raise ProtocolError(f"payload length {n} out of range")
    return bytes([(n >> 7) & 0x7F, n & 0x7F])


def _decode_length(hi: int, lo: int) -> int:
    return (hi << 7) | lo


def build_frame(opcode: int, data: bytes = b"", config: ProtocolConfig | None = None) -> bytes:
    """Build a complete ``F0 .. F7`` mk1-family frame."""
    cfg = config or ProtocolConfig()
    data = bytes(data)
    for b in data:
        if b > 0x7F:
            raise ProtocolError(f"data byte 0x{b:02X} exceeds 7-bit SysEx range")
    return bytes(
        [SYSEX_START, cfg.manufacturer, cfg.device, cfg.model, opcode]
        + list(_encode_length(len(data)))
        + list(data)
        + [SYSEX_END]
    )


def parse_frame(raw: bytes) -> Frame:
    """Parse a complete mk1-family frame. Raises :class:`ProtocolError` on bad input."""
    raw = bytes(raw)
    if len(raw) < 8:
        raise ProtocolError(f"frame too short ({len(raw)} bytes)")
    if raw[0] != SYSEX_START or raw[-1] != SYSEX_END:
        raise ProtocolError("missing F0/F7 delimiters")
    manufacturer, device, model, opcode, len_hi, len_lo = raw[1:7]
    declared = _decode_length(len_hi, len_lo)
    data = raw[7:-1]
    if len(data) != declared:
        raise ProtocolError(
            f"length mismatch: header says {declared}, payload has {len(data)}"
        )
    return Frame(manufacturer, device, model, opcode, data)


# --- Convenience builders -------------------------------------------------

def build_get_program(slot: int, config: ProtocolConfig | None = None) -> bytes:
    return build_frame(OP_GET_PROGRAM, bytes([slot]), config)


def build_send_program(slot: int, payload: bytes, config: ProtocolConfig | None = None) -> bytes:
    return build_frame(OP_SEND_PROGRAM, bytes([slot]) + bytes(payload), config)


def build_activate_program(slot: int, config: ProtocolConfig | None = None) -> bytes:
    return build_frame(OP_ACTIVATE_PROGRAM, bytes([slot]), config)


def build_get_active_program(config: ProtocolConfig | None = None) -> bytes:
    return build_frame(OP_GET_ACTIVE_PROGRAM, b"", config)


# --- Universal (non-Akai) Device Inquiry ----------------------------------
# Standard MIDI identity request, the safest way to learn the model byte.

IDENTITY_REQUEST = bytes([0xF0, 0x7E, 0x7F, 0x06, 0x01, 0xF7])


@dataclass
class IdentityReply:
    manufacturer: int
    family: int
    member: int
    version: bytes
    raw: bytes


def parse_identity_reply(raw: bytes) -> IdentityReply:
    """Parse a Universal Device Inquiry reply (``F0 7E <dev> 06 02 ...``)."""
    raw = bytes(raw)
    if len(raw) < 7 or raw[0] != 0xF0 or raw[-1] != 0xF7:
        raise ProtocolError("not a SysEx frame")
    if raw[1] != 0x7E or raw[3] != 0x06 or raw[4] != 0x02:
        raise ProtocolError("not a device-inquiry reply")
    body = raw[5:-1]
    manufacturer = body[0]
    # Akai uses a single-byte manufacturer id; family/member are little-endian pairs.
    family = body[1] | (body[2] << 7) if len(body) >= 3 else -1
    member = body[3] | (body[4] << 7) if len(body) >= 5 else -1
    version = bytes(body[5:]) if len(body) > 5 else b""
    return IdentityReply(manufacturer, family, member, version, raw)
