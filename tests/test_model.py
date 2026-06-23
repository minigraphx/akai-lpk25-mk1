import pytest

from lpk25.model import Program


def make(slot=1):
    # slot, ch10(byte9), oct+4, transpose+12, arp on, excl, 1/8, clock int,
    # latch on, taps4, tempo226, arp_oct3
    return Program.from_payload(slot, bytes([slot, 9, 8, 24, 1, 3, 2, 0, 1, 4, 1, 98, 3]))


def test_reslot_sets_echo_and_slot_preserves_rest():
    p = make(1)
    q = p.reslot(3)
    assert q.slot == 3
    assert q.raw[0] == 3                    # slot-echo byte corrected
    assert q.raw[1:] == p.raw[1:]           # every other byte preserved
    assert q.values["midi_channel"] == 10   # values re-decoded from new payload
    assert p.raw[0] == 1                     # original program untouched


def test_reslot_empty_raw_raises():
    with pytest.raises(ValueError):
        Program(slot=1, raw=b"").reslot(2)
