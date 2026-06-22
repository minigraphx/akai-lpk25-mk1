from lpk25 import protocol as p


def test_frame_round_trip():
    cfg = p.ProtocolConfig(model=0x76)
    frame = p.build_frame(p.OP_GET_PROGRAM, bytes([1]), cfg)
    parsed = p.parse_frame(frame)
    assert parsed.manufacturer == p.MANUFACTURER_AKAI
    assert parsed.device == p.DEVICE_BROADCAST
    assert parsed.model == 0x76
    assert parsed.opcode == p.OP_GET_PROGRAM
    assert parsed.data == bytes([1])
    assert parsed.slot == 1


def test_get_program_bytes_match_family_layout():
    # F0 47 7F <model> 63 <len_hi> <len_lo> <slot> F7
    frame = p.build_get_program(2, p.ProtocolConfig(model=0x75))
    assert list(frame) == [0xF0, 0x47, 0x7F, 0x75, 0x63, 0x00, 0x01, 0x02, 0xF7]


def test_send_program_prefixes_slot():
    frame = p.build_send_program(3, bytes([10, 11]), p.ProtocolConfig(model=0x76))
    parsed = p.parse_frame(frame)
    assert parsed.opcode == p.OP_SEND_PROGRAM
    assert parsed.data == bytes([3, 10, 11])  # slot byte prepended


def test_length_encoding_two_seven_bit_bytes():
    data = bytes(range(0, 100))  # 100 bytes
    frame = p.build_frame(0x61, data, p.ProtocolConfig(model=0x76))
    assert frame[5] == (100 >> 7) & 0x7F
    assert frame[6] == 100 & 0x7F
    assert p.parse_frame(frame).data == data


def test_length_mismatch_raises():
    good = p.build_get_program(1, p.ProtocolConfig(model=0x76))
    tampered = bytearray(good)
    tampered[6] = 5  # claim 5 data bytes, but there is 1
    try:
        p.parse_frame(bytes(tampered))
    except p.ProtocolError:
        return
    raise AssertionError("expected ProtocolError")


def test_non_7bit_data_rejected():
    try:
        p.build_frame(0x61, bytes([0x80]), p.ProtocolConfig(model=0x76))
    except p.ProtocolError:
        return
    raise AssertionError("expected ProtocolError")


def test_identity_request_is_standard():
    assert list(p.IDENTITY_REQUEST) == [0xF0, 0x7E, 0x7F, 0x06, 0x01, 0xF7]


def test_parse_identity_reply():
    raw = bytes([0xF0, 0x7E, 0x00, 0x06, 0x02, 0x47, 0x76, 0x00, 0x19, 0x00, 1, 0, 0, 5, 0xF7])
    reply = p.parse_identity_reply(raw)
    assert reply.manufacturer == 0x47
    assert reply.family == 0x76
    assert reply.member == 0x19
