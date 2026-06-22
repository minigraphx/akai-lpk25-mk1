from lpk25 import render
from lpk25.model import Preset, Program


def mock_preset():
    # Mirror MockTransport's default programs (ch1, oct0, arp off, up, 1/16T,
    # internal, latch off, tempo 120, taps 3, arp_oct 0).
    def raw(s):
        return bytes([s, 0, 4, 12, 0, 0, 5, 0, 0, 3, 0, 120, 0])

    return Preset(programs=[Program.from_payload(s, raw(s)) for s in range(1, 5)])


def test_table_has_headers_and_rows():
    out = render.format_presets_table(mock_preset(), active_slot=1)
    lines = out.splitlines()
    assert "ch" in lines[0] and "tempo" in lines[0] and "aoct" in lines[0]
    assert len(lines) == 5  # header + 4 slots


def test_table_marks_active_slot():
    out = render.format_presets_table(mock_preset(), active_slot=2)
    lines = out.splitlines()
    # exactly one data row carries the active marker
    assert sum(1 for ln in lines if "▶" in ln) == 1
    assert "▶" in lines[2]  # slot 2 is the 2nd data row (index 2 overall)


def test_table_renders_labels_not_raw_bytes():
    out = render.format_presets_table(mock_preset())
    assert "off" in out      # arp_enabled False -> off
    assert "1/16T" in out    # time_division code 5
    assert "int" in out      # clock internal -> int
    assert "120" in out      # tempo


def test_format_program_single():
    prog = Program.from_payload(3, bytes([3, 4, 5, 0, 1, 3, 2, 0, 1, 3, 1, 98, 3]))
    out = render.format_program(prog)
    assert out.splitlines()[0] == "slot 3"
    assert "ch" in out and "5" in out          # channel 5 (byte 4 -> +1)
    assert "exclusive" in out                   # arp_mode code 3
    assert "on" in out                          # arp_enabled
