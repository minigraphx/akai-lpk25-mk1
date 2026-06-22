from lpk25 import cli, codec
from lpk25.transport import MockTransport


def run(argv, transport):
    # Patch _make_transport so the CLI talks to our in-memory device.
    orig = cli._make_transport
    cli._make_transport = lambda args: transport
    try:
        return cli.main(argv)
    finally:
        cli._make_transport = orig


def test_edit_changes_named_fields_only():
    tr = MockTransport()
    rc = run(["--mock", "edit", "1", "--channel", "5", "--octave", "-1"], tr)
    assert rc == 0
    raw = tr.programs[1]
    v = codec.decode_program(raw)
    assert v["midi_channel"] == 5
    assert v["keybed_octave"] == -1
    # untouched fields keep their defaults
    assert v["tempo"] == 120
    assert v["arp_mode"] == "up"


def test_edit_enum_and_bool_flags():
    tr = MockTransport()
    rc = run(["--mock", "edit", "2", "--arp", "on", "--arp-mode", "exclusive",
              "--clock", "external", "--latch", "on"], tr)
    assert rc == 0
    v = codec.decode_program(tr.programs[2])
    assert v["arp_enabled"] is True
    assert v["arp_mode"] == "exclusive"
    assert v["clock"] == "external"
    assert v["arp_latch"] is True


def test_edit_no_flags_errors():
    tr = MockTransport()
    rc = run(["--mock", "edit", "1"], tr)
    assert rc == 2


def test_edit_rejects_out_of_range():
    tr = MockTransport()
    rc = run(["--mock", "edit", "1", "--channel", "99"], tr)
    assert rc != 0
    # nothing written: channel byte unchanged (default 0 -> channel 1)
    assert codec.decode_program(tr.programs[1])["midi_channel"] == 1
