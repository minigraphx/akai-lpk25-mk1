from lpk25 import codec


def sample_payload() -> bytes:
    # slot, ch(=>1), oct, transpose, arp_on, latch, mode, timediv, clock, taps, tempo, arpoct
    return bytes([1, 0, 4, 12, 1, 0, 2, 4, 1, 3, 120, 2])


def test_decode_known_fields():
    values = codec.decode_program(sample_payload())
    assert values["midi_channel"] == 1  # byte 0 -> channel 1
    assert values["arp_enabled"] is True
    assert values["arp_latch"] is False
    assert values["arp_mode"] == "exclusive"  # code 2
    assert values["time_division"] == "1/16"  # code 4
    assert values["clock"] == "external"  # code 1
    assert values["tempo_taps"] == 3
    assert values["arp_octave"] == 2  # byte 2 -> 2 (arp octave range is 0-3)


def test_encode_is_inverse_of_decode():
    raw = sample_payload()
    values = codec.decode_program(raw)
    assert codec.encode_program(values, raw) == raw


def test_encode_patches_only_named_field():
    raw = sample_payload()
    out = codec.encode_program({"midi_channel": 10}, raw)
    assert out[1] == 9  # 10 - 1 offset
    # everything else untouched
    assert out[:1] == raw[:1]
    assert out[2:] == raw[2:]


def test_enum_label_and_code_both_accepted():
    raw = sample_payload()
    by_label = codec.encode_program({"arp_mode": "random"}, raw)
    by_code = codec.encode_program({"arp_mode": 5}, raw)
    assert by_label == by_code
    assert by_label[6] == 5


def test_out_of_range_raises():
    raw = sample_payload()
    try:
        codec.encode_program({"midi_channel": 99}, raw)
    except codec.CodecError:
        return
    raise AssertionError("expected CodecError")


def test_unknown_field_raises():
    try:
        codec.encode_program({"nope": 1}, sample_payload())
    except codec.CodecError:
        return
    raise AssertionError("expected CodecError")


def test_short_payload_skips_missing_fields():
    values = codec.decode_program(bytes([1, 0, 4]))  # only 3 bytes
    assert "midi_channel" in values
    assert "tempo" not in values
