"""Decode raw MIDI messages into human-readable text for ``lpk25 monitor``.

Each function takes one complete MIDI message (the byte sequences delivered by
:meth:`Transport.monitor`) and returns a concise, readable description. This is
pure parsing of the standard MIDI byte format — no hardware or dependencies — so
it is fully unit-testable offline.
"""

from __future__ import annotations

# Sharp spelling; index = pitch class (0 = C).
_NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# A few well-known Control Change numbers worth labelling (the LPK25's SUSTAIN
# button sends CC 64 when the arpeggiator is off).
_CC_NAMES = {
    1: "Mod Wheel",
    7: "Volume",
    10: "Pan",
    11: "Expression",
    64: "Sustain",
    120: "All Sound Off",
    121: "Reset All Controllers",
    123: "All Notes Off",
}

# System real-time / common status bytes that carry no channel.
_SYSTEM_NAMES = {
    0xF1: "MTC Quarter Frame",
    0xF6: "Tune Request",
    0xF8: "Clock",
    0xFA: "Start",
    0xFB: "Continue",
    0xFC: "Stop",
    0xFE: "Active Sensing",
    0xFF: "Reset",
}


def note_name(note: int) -> str:
    """MIDI note number -> scientific pitch name, e.g. 60 -> ``C4``, 69 -> ``A4``."""
    return f"{_NOTE_NAMES[note % 12]}{note // 12 - 1}"


def _hex(frame: bytes) -> str:
    return " ".join(f"{b:02X}" for b in frame)


def _manufacturer(frame: bytes) -> str:
    if len(frame) < 2:
        return "SysEx"
    mfr = frame[1]
    if mfr == 0x7E:
        return "SysEx (Universal non-realtime)"
    if mfr == 0x7F:
        return "SysEx (Universal realtime)"
    if mfr == 0x47:
        return "SysEx (Akai)"
    return f"SysEx (mfr 0x{mfr:02X})"


def decode_message(frame: bytes) -> str:
    """Return a one-line, human-readable description of one MIDI message.

    Falls back to a hex dump for anything malformed or unrecognised, so the
    monitor never hides traffic it cannot fully parse.
    """
    frame = bytes(frame)
    if not frame:
        return "(empty)"

    status = frame[0]

    # System Exclusive.
    if status == 0xF0:
        return f"{_manufacturer(frame)}, {len(frame)} bytes: {_hex(frame)}"

    # System common / real-time (no channel nibble). Multi-byte common messages
    # are handled first so they don't fall through to the name lookup below.
    if status >= 0xF0:
        if status == 0xF2 and len(frame) >= 3:  # Song Position Pointer
            return f"Song Position {(frame[2] << 7) | frame[1]}"
        if status == 0xF3 and len(frame) >= 2:  # Song Select
            return f"Song Select {frame[1]}"
        if status == 0xF1 and len(frame) >= 2:  # MTC quarter frame
            return f"MTC Quarter Frame 0x{frame[1]:02X}"
        name = _SYSTEM_NAMES.get(status)
        return name if name is not None else _hex(frame)

    # Channel voice messages.
    kind = status & 0xF0
    channel = (status & 0x0F) + 1
    d1 = frame[1] if len(frame) > 1 else None
    d2 = frame[2] if len(frame) > 2 else None

    if kind == 0x90 and d1 is not None and d2 is not None:
        # Note On with velocity 0 is, by convention, a Note Off.
        if d2 == 0:
            return f"ch{channel} Note Off {note_name(d1)} vel 0"
        return f"ch{channel} Note On  {note_name(d1)} vel {d2}"
    if kind == 0x80 and d1 is not None and d2 is not None:
        return f"ch{channel} Note Off {note_name(d1)} vel {d2}"
    if kind == 0xA0 and d1 is not None and d2 is not None:
        return f"ch{channel} Poly Pressure {note_name(d1)} {d2}"
    if kind == 0xB0 and d1 is not None and d2 is not None:
        label = _CC_NAMES.get(d1)
        cc = f"CC {d1}" + (f" ({label})" if label else "")
        return f"ch{channel} {cc} = {d2}"
    if kind == 0xC0 and d1 is not None:
        return f"ch{channel} Program Change {d1}"
    if kind == 0xD0 and d1 is not None:
        return f"ch{channel} Channel Pressure {d1}"
    if kind == 0xE0 and d1 is not None and d2 is not None:
        bend = ((d2 << 7) | d1) - 8192
        return f"ch{channel} Pitch Bend {bend:+d}"

    # Anything we couldn't parse (truncated channel message, etc.).
    return _hex(frame)


# High-rate transport spam that floods the monitor; hidden unless --all.
_NOISE = {0xF8, 0xFE}  # MIDI Clock, Active Sensing


def is_noise(frame: bytes) -> bool:
    """True for messages hidden by default (MIDI Clock, Active Sensing)."""
    return bool(frame) and frame[0] in _NOISE


def format_line(frame: bytes, *, raw: bool = False, t: float | None = None) -> str:
    """Render one monitor line: an optional ``[   t]`` timestamp prefix followed
    by the raw hex (``raw=True``) or the decoded description."""
    body = _hex(bytes(frame)) if raw else decode_message(frame)
    return body if t is None else f"[{t:7.3f}] {body}"
