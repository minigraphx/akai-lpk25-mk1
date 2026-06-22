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


def test_diff_payloads_detects_changed_byte():
    # The real captures: arp toggled on (idx 4: 00 -> 01), nothing else.
    a = bytes.fromhex("0100050c000305000003001e00")
    b = bytes.fromhex("0100050c010305000003001e00")
    changes = codec.diff_payloads(a, b)
    assert len(changes) == 1
    c = changes[0]
    assert (c.index, c.old, c.new) == (4, 0, 1)
    assert c.field == "arp_enabled"
    assert c.verified is True


def test_diff_payloads_identical_is_empty():
    p = bytes.fromhex("0100050c000305000003001e00")
    assert codec.diff_payloads(p, p) == []


def test_diff_payloads_unmapped_and_length_change():
    # 13-byte payload vs. one with the trailing (unmapped) idx 12 flipped + grown.
    a = bytes.fromhex("0100050c000305000003001e00")       # 13 bytes
    b = bytes.fromhex("0100050c000305000003001e0142")     # idx 12 changed, idx 13 added
    changes = codec.diff_payloads(a, b)
    by_idx = {c.index: c for c in changes}
    assert set(by_idx) == {12, 13}
    assert by_idx[12].old == 0 and by_idx[12].new == 1
    assert by_idx[13].old is None and by_idx[13].new == 0x42
    assert by_idx[12].field is None  # trailing byte is unmapped
    assert by_idx[13].field is None
