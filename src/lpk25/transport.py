"""MIDI transport: send/receive whole SysEx frames (including F0/F7).

The real backend (:class:`MidoTransport`) uses ``mido`` + ``python-rtmidi`` and
is imported lazily, so the rest of the package imports and unit-tests cleanly
without the MIDI extra installed. :class:`MockTransport` is a scriptable,
dependency-free fake device for tests and offline demos.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Callable

DEFAULT_PORT_MATCH = "LPK25"


class TransportError(RuntimeError):
    pass


class Transport(ABC):
    @abstractmethod
    def send(self, frame: bytes) -> None:
        """Send one complete MIDI message (SysEx frames include F0..F7)."""

    @abstractmethod
    def receive(self, timeout: float = 1.0) -> bytes | None:
        """Return the next incoming message as raw bytes, or None on timeout."""

    def request(self, frame: bytes, timeout: float = 1.0) -> bytes | None:
        """Send a frame and wait for a single reply."""
        self.send(frame)
        return self.receive(timeout=timeout)

    def close(self) -> None:  # noqa: B027 - optional override, default no-op
        """Release MIDI resources. Subclasses override; default is a no-op."""

    def __enter__(self) -> Transport:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def list_ports() -> dict:
    """Return {'inputs': [...], 'outputs': [...]} of available MIDI port names."""
    mido = _import_mido()
    return {
        "inputs": list(mido.get_input_names()),
        "outputs": list(mido.get_output_names()),
    }


def _import_mido():
    try:
        import mido  # type: ignore
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise TransportError(
            "The MIDI backend is not installed. Run:  pip install 'lpk25[midi]'"
        ) from exc
    return mido


def _match_port(names: list[str], match: str) -> str | None:
    low = match.lower()
    for n in names:
        if low in n.lower():
            return n
    return None


class MidoTransport(Transport):
    """Real MIDI transport backed by mido/python-rtmidi."""

    def __init__(
        self,
        port_match: str = DEFAULT_PORT_MATCH,
        input_name: str | None = None,
        output_name: str | None = None,
    ):
        mido = _import_mido()
        self._mido = mido
        ins = mido.get_input_names()
        outs = mido.get_output_names()
        in_name = input_name or _match_port(ins, port_match)
        out_name = output_name or _match_port(outs, port_match)
        if in_name is None or out_name is None:
            raise TransportError(
                f"Could not find a MIDI port matching {port_match!r}.\n"
                f"  inputs:  {ins}\n  outputs: {outs}\n"
                "Pass --port or --in-port/--out-port to choose explicitly."
            )
        self.input_name = in_name
        self.output_name = out_name
        self._in = mido.open_input(in_name)
        self._out = mido.open_output(out_name)

    def send(self, frame: bytes) -> None:
        frame = bytes(frame)
        if frame and frame[0] == 0xF0 and frame[-1] == 0xF7:
            msg = self._mido.Message("sysex", data=list(frame[1:-1]))
        else:
            msg = self._mido.Message.from_bytes(list(frame))
        self._out.send(msg)

    def receive(self, timeout: float = 1.0, sysex_only: bool = False) -> bytes | None:
        """Return the next incoming message, or None on timeout.

        With ``sysex_only`` set, skip any non-SysEx traffic (Channel Voice such
        as a sustain-pedal CC, Active Sensing, Clock, etc.) and keep waiting for
        an ``F0 .. F7`` frame until the timeout. This keeps a program read from
        being hijacked by stray 3-byte messages the keyboard happens to emit.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            msg = self._in.poll()
            if msg is not None:
                data = bytes(msg.bytes())
                if not sysex_only or (data and data[0] == 0xF0):
                    return data
            else:
                time.sleep(0.002)
        return None

    def request(self, frame: bytes, timeout: float = 1.0) -> bytes | None:
        """Send a frame and wait for the SysEx reply, ignoring stray messages."""
        self.send(frame)
        return self.receive(timeout=timeout, sysex_only=True)

    def monitor(self, callback: Callable[[bytes], None], duration: float | None = None) -> None:
        """Stream incoming messages to ``callback`` until ``duration`` elapses
        (or forever if None). Used as the behavioural oracle."""
        end = None if duration is None else time.monotonic() + duration
        while end is None or time.monotonic() < end:
            msg = self._in.poll()
            if msg is not None:
                callback(bytes(msg.bytes()))
            else:
                time.sleep(0.002)

    def close(self) -> None:
        for port in (getattr(self, "_in", None), getattr(self, "_out", None)):
            try:
                if port is not None:
                    port.close()
            except Exception:  # pragma: no cover - best effort
                pass


class MockTransport(Transport):
    """In-memory fake LPK25 for tests and offline demos.

    Responds to get/send/get-active frames using a configurable program store so
    the higher layers can be exercised without hardware.
    """

    def __init__(self, programs: dict | None = None, model: int = 0x76):
        from . import protocol

        self._protocol = protocol
        self.model = model
        # slot -> payload (payload[0] is the slot echo). Realistic 13-byte layout
        # matching the confirmed map: ch 1, octave 0 (idx2=4), transpose 0
        # (idx3=12), arp off, mode up (idx5=0), tempo 120 (idx10:11 = 0,120).
        self.programs: dict = programs or {
            s: bytes([s, 0, 4, 12, 0, 0, 5, 0, 0, 3, 0, 120, 0]) for s in range(1, 5)
        }
        self.active = 1
        self.sent: list[bytes] = []
        self._pending: list[bytes] = []

    def send(self, frame: bytes) -> None:
        self.sent.append(bytes(frame))
        p = self._protocol
        try:
            f = p.parse_frame(frame)
        except p.ProtocolError:
            return
        if f.opcode == p.OP_GET_PROGRAM and f.slot in self.programs:
            payload = self.programs[f.slot]
            self._pending.append(p.build_frame(p.OP_GET_PROGRAM, payload,
                                               p.ProtocolConfig(model=self.model)))
        elif f.opcode == p.OP_SEND_PROGRAM and f.data:
            self.programs[f.data[0]] = bytes(f.data)
        elif f.opcode == p.OP_ACTIVATE_PROGRAM and f.slot:
            self.active = f.slot
        elif f.opcode == p.OP_GET_ACTIVE_PROGRAM:
            self._pending.append(p.build_frame(p.OP_GET_ACTIVE_PROGRAM, bytes([self.active]),
                                               p.ProtocolConfig(model=self.model)))

    def receive(self, timeout: float = 1.0) -> bytes | None:
        return self._pending.pop(0) if self._pending else None
