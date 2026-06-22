from lpk25 import codec


def sample_payload() -> bytes:
    # Confirmed map: slot, ch(->1), octave(->0), transpose(->0), arp_on,
    # arp_mode(=exclusive, idx 5), then idx 6-12 still unmapped (base-dump bytes).
    return bytes([1, 0, 4, 12, 1, 3, 5, 0, 0, 3, 0, 30, 0])


def test_decode_known_fields():
    values = codec.decode_program(sample_payload())
    assert values["midi_channel"] == 1  # byte 0 -> channel 1
    assert values["keybed_octave"] == 0  # byte 4 -> octave 0
    assert values["transpose"] == 0  # byte 12 -> transpose 0
    assert values["arp_enabled"] is True
    assert values["arp_mode"] == "exclusive"  # code 3 at idx 5
    # idx 6-12 are still unmapped, so no further fields are decoded
    assert "arp_latch" not in values
    assert "time_division" not in values


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
    assert by_label[5] == 5  # arp_mode is at idx 5


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


def test_keybed_octave_encoding_confirmed():
    # Golden vectors from real hardware (2026-06-22): octave min/center/+1/max.
    cases = {0x00: -4, 0x04: 0, 0x05: 1, 0x08: 4}
    for byte, octave in cases.items():
        payload = bytes([1, 0, byte, 0x0C, 0]) + bytes(8)
        assert codec.decode_program(payload)["keybed_octave"] == octave
        # round-trips back to the same byte
        out = codec.encode_program({"keybed_octave": octave}, payload)
        assert out[2] == byte


def test_arp_mode_confirmed_codes_and_index():
    # Hardware (2026-06-22): mode byte is idx 5; Up=0, Exclusive=3.
    up = bytes([1, 0, 8, 12, 1, 0, 5, 0, 0, 3, 0, 30, 0])
    excl = bytes([1, 0, 8, 12, 1, 3, 5, 0, 0, 3, 0, 30, 0])
    assert codec.decode_program(up)["arp_mode"] == "up"
    assert codec.decode_program(excl)["arp_mode"] == "exclusive"
    # encode round-trips the label back to its code at idx 5
    out = codec.encode_program({"arp_mode": "exclusive"}, bytes(13))
    assert out[5] == 3
    assert codec.ARP_MODES[2] == "inclusive" and codec.ARP_MODES[3] == "exclusive"


def test_tempo_u14_two_byte_field():
    # Hardware (2026-06-23): tempo = (idx10<<7)|idx11. Fast tap -> 226 BPM.
    fast = bytes([1, 0, 4, 12, 1, 0, 5, 0, 0, 3, 1, 98, 0])
    assert codec.decode_program(fast)["tempo"] == 226
    slow = bytes([1, 0, 4, 12, 0, 0, 5, 0, 0, 3, 0, 30, 0])
    assert codec.decode_program(slow)["tempo"] == 30
    # encode splits high/low correctly and round-trips
    out = codec.encode_program({"tempo": 226}, bytes(13))
    assert out[10] == 1 and out[11] == 98
    assert codec.decode_program(codec.encode_program({"tempo": 240}, bytes(13)))["tempo"] == 240


def test_tempo_out_of_range_rejected():
    try:
        codec.encode_program({"tempo": 999}, bytes(13))
    except codec.CodecError:
        return
    raise AssertionError("expected CodecError for tempo out of range")


def test_diff_labels_both_tempo_bytes():
    a = bytes([1, 0, 4, 12, 1, 0, 5, 0, 0, 3, 0, 120, 0])
    b = bytes([1, 0, 4, 12, 1, 0, 5, 0, 0, 3, 1, 98, 0])
    changes = {c.index: c for c in codec.diff_payloads(a, b)}
    assert changes[10].field == "tempo" and changes[11].field == "tempo"
