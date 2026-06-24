"""Background MIDI input reader for the TUI monitor pane.

Runs a daemon thread that reads input frames from the transport, decodes each
with mididecode, and keeps the newest lines in a bounded ring buffer. Inert
when the transport exposes no input (offline / no [midi] extra)."""

from __future__ import annotations

import threading
from collections import deque

from .. import mididecode


class MidiMonitor:
    def __init__(self, transport, maxlen: int = 200):
        self._transport = transport
        self._lines: deque[str] = deque(maxlen=maxlen)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def available(self) -> bool:
        return callable(getattr(self._transport, "receive", None))

    def _consume(self, frame: bytes) -> None:
        if frame:
            self._lines.append(mididecode.decode_message(frame))

    def lines(self, n: int) -> list[str]:
        return list(self._lines)[-n:]

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                frame = self._transport.receive(timeout=0.1)
            except Exception:
                return
            self._consume(frame)

    def start(self) -> None:
        if not self.available or self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=0.5)
            self._thread = None
