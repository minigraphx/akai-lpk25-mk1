from lpk25 import mididecode


def test_note_name_anchors():
    assert mididecode.note_name(0) == "C-1"
    assert mididecode.note_name(60) == "C4"
    assert mididecode.note_name(69) == "A4"  # A440
    assert mididecode.note_name(61) == "C#4"
    assert mididecode.note_name(127) == "G9"


def test_note_on_and_off():
    assert mididecode.decode_message(bytes([0x99, 60, 100])) == "ch10 Note On  C4 vel 100"
    assert mididecode.decode_message(bytes([0x80, 60, 64])) == "ch1 Note Off C4 vel 64"


def test_note_on_velocity_zero_is_note_off():
    assert mididecode.decode_message(bytes([0x90, 60, 0])) == "ch1 Note Off C4 vel 0"


def test_control_change_labels_known_cc():
    assert mididecode.decode_message(bytes([0xB0, 64, 127])) == "ch1 CC 64 (Sustain) = 127"
    # unknown CC has no label
    assert mididecode.decode_message(bytes([0xB0, 9, 5])) == "ch1 CC 9 = 5"


def test_program_change_and_pressure():
    assert mididecode.decode_message(bytes([0xC2, 5])) == "ch3 Program Change 5"
    assert mididecode.decode_message(bytes([0xD0, 80])) == "ch1 Channel Pressure 80"
    assert mididecode.decode_message(bytes([0xA0, 60, 80])) == "ch1 Poly Pressure C4 80"


def test_pitch_bend_signed_centered():
    assert mididecode.decode_message(bytes([0xE0, 0x00, 0x40])) == "ch1 Pitch Bend +0"
    assert mididecode.decode_message(bytes([0xE0, 0x00, 0x00])) == "ch1 Pitch Bend -8192"
    assert mididecode.decode_message(bytes([0xE0, 0x7F, 0x7F])) == "ch1 Pitch Bend +8191"


def test_system_realtime_and_common():
    assert mididecode.decode_message(bytes([0xF8])) == "Clock"
    assert mididecode.decode_message(bytes([0xFA])) == "Start"
    assert mididecode.decode_message(bytes([0xFC])) == "Stop"
    assert mididecode.decode_message(bytes([0xFE])) == "Active Sensing"
    assert mididecode.decode_message(bytes([0xF6])) == "Tune Request"
    assert mididecode.decode_message(bytes([0xF2, 0x00, 0x01])) == "Song Position 128"
    assert mididecode.decode_message(bytes([0xF3, 7])) == "Song Select 7"


def test_sysex_labels_manufacturer():
    akai = mididecode.decode_message(bytes([0xF0, 0x47, 0x7F, 0x76, 0xF7]))
    assert akai.startswith("SysEx (Akai), 5 bytes:")
    universal = mididecode.decode_message(bytes([0xF0, 0x7E, 0x7F, 0x06, 0x01, 0xF7]))
    assert universal.startswith("SysEx (Universal non-realtime)")


def test_empty_and_truncated_fall_back():
    assert mididecode.decode_message(b"") == "(empty)"
    # a note-on missing its data bytes -> hex fallback, never a crash
    assert mididecode.decode_message(bytes([0x90])) == "90"


def test_is_noise():
    assert mididecode.is_noise(bytes([0xF8])) is True       # Clock
    assert mididecode.is_noise(bytes([0xFE])) is True       # Active Sensing
    assert mididecode.is_noise(bytes([0xFA])) is False      # Start is meaningful
    assert mididecode.is_noise(bytes([0x90, 60, 100])) is False
    assert mididecode.is_noise(b"") is False


def test_format_line_raw_vs_decoded():
    frame = bytes([0x99, 60, 100])
    assert mididecode.format_line(frame) == "ch10 Note On  C4 vel 100"
    assert mididecode.format_line(frame, raw=True) == "99 3C 64"


def test_format_line_timestamp_prefix():
    frame = bytes([0xFA])
    assert mididecode.format_line(frame, t=0.0) == "[  0.000] Start"
    assert mididecode.format_line(frame, t=1.25) == "[  1.250] Start"
    assert mididecode.format_line(frame, raw=True, t=2.5) == "[  2.500] FA"
