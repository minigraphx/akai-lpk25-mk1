import pytest

from lpk25 import protocol
from lpk25.model import Preset, Program


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


def _bank():
    return Preset(
        programs=[
            Program.from_payload(s, bytes([s, s, 4, 12, 0, 0, 5, 0, 0, 3, 0, 120, 0]))
            for s in (1, 2, 3, 4)
        ],
        device_model=0x76,
    )


def test_to_syx_one_frame_per_program():
    frames = protocol.split_sysex(_bank().to_syx())
    assert len(frames) == 4
    f = protocol.parse_frame(frames[0])
    assert f.manufacturer == 0x47 and f.model == 0x76
    assert f.opcode == protocol.OP_SEND_PROGRAM
    assert f.data[0] == 1 and len(f.data) == 13   # slot echo + full 13-byte payload


def test_syx_round_trips():
    p = _bank()
    q = Preset.from_syx(p.to_syx())
    assert [x.slot for x in q.programs] == [1, 2, 3, 4]
    assert [x.raw for x in q.programs] == [x.raw for x in p.programs]


def test_from_syx_skips_non_program_frames():
    stray = bytes([0xF0, 0x7E, 0x7F, 0x06, 0x02, 0xF7])   # a device-inquiry-style frame
    q = Preset.from_syx(stray + _bank().to_syx())
    assert len(q.programs) == 4


def test_from_syx_no_frames_raises():
    with pytest.raises(ValueError):
        Preset.from_syx(bytes([0xF0, 0x7E, 0x7F, 0x06, 0x02, 0xF7]))


def test_save_load_syx_round_trip(tmp_path):
    p = _bank()
    path = str(tmp_path / "bank.syx")
    p.save(path)
    q = Preset.load(path)
    assert [x.raw for x in q.programs] == [x.raw for x in p.programs]


def test_save_load_json_still_works(tmp_path):
    p = _bank()
    path = str(tmp_path / "bank.json")
    p.save(path)
    q = Preset.load(path)
    assert [x.raw for x in q.programs] == [x.raw for x in p.programs]
