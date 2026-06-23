from lpk25.tui.monitor import MidiMonitor


class _FakeInput:
    """Transport-like object that yields queued frames from receive()."""
    def __init__(self, frames):
        self._frames = list(frames)

    def receive(self, timeout=0.1):
        return self._frames.pop(0) if self._frames else None


def test_consume_decodes_frames_into_lines():
    m = MidiMonitor(_FakeInput([]))
    m._consume(bytes([0x90, 60, 100]))          # Note On C4
    m._consume(bytes([0x80, 60, 0]))            # Note Off C4
    lines = m.lines(10)
    assert len(lines) == 2
    assert "Note On" in lines[0]
    assert "C4" in lines[0]


def test_ring_buffer_caps_at_maxlen():
    m = MidiMonitor(_FakeInput([]), maxlen=5)
    for n in range(20):
        m._consume(bytes([0x90, 60 + (n % 5), 100]))
    assert len(m.lines(100)) == 5               # only newest 5 kept


def test_available_false_without_receive():
    class NoInput:
        pass
    assert MidiMonitor(NoInput()).available is False
    assert MidiMonitor(_FakeInput([])).available is True
