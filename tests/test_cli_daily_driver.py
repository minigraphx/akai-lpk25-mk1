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


def test_show_table(capsys):
    tr = MockTransport()
    rc = run(["--mock", "show"], tr)
    assert rc == 0
    out = capsys.readouterr().out
    assert "tempo" in out                 # header present
    assert out.count("\n") >= 5           # header + 4 slots
    assert "▶" in out                # active slot marked


def test_show_single_slot(capsys):
    tr = MockTransport()
    rc = run(["--mock", "show", "1"], tr)
    assert rc == 0
    out = capsys.readouterr().out
    assert out.startswith("slot 1")


def test_show_json(capsys):
    tr = MockTransport()
    rc = run(["--mock", "show", "--json"], tr)
    assert rc == 0
    out = capsys.readouterr().out
    assert '"programs"' in out            # falls back to dump JSON


def test_preset_save_and_apply_cross_slot(tmp_path, monkeypatch):
    monkeypatch.setenv("LPK25_PRESET_DIR", str(tmp_path))
    tr = MockTransport()
    # make slot 1 distinctive, then save it as a preset
    run(["--mock", "edit", "1", "--channel", "7", "--tempo", "150"], tr)
    assert run(["--mock", "preset", "save", "myset", "--from-slot", "1"], tr) == 0
    # apply onto slot 3
    assert run(["--mock", "preset", "apply", "myset", "3"], tr) == 0
    v = codec.decode_program(tr.programs[3])
    assert v["midi_channel"] == 7 and v["tempo"] == 150
    # slot-echo byte was corrected to the target slot (read-back verify passed)
    assert tr.programs[3][0] == 3


def test_preset_save_refuses_overwrite(tmp_path, monkeypatch):
    monkeypatch.setenv("LPK25_PRESET_DIR", str(tmp_path))
    tr = MockTransport()
    assert run(["--mock", "preset", "save", "dup", "--from-slot", "1"], tr) == 0
    assert run(["--mock", "preset", "save", "dup", "--from-slot", "1"], tr) != 0
    assert run(["--mock", "preset", "save", "dup", "--from-slot", "1", "--force"], tr) == 0


def test_preset_apply_missing_errors(tmp_path, monkeypatch):
    monkeypatch.setenv("LPK25_PRESET_DIR", str(tmp_path))
    tr = MockTransport()
    assert run(["--mock", "preset", "apply", "ghost", "1"], tr) != 0


def test_preset_list(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LPK25_PRESET_DIR", str(tmp_path))
    tr = MockTransport()
    run(["--mock", "preset", "save", "alpha", "--from-slot", "1"], tr)
    capsys.readouterr()  # clear
    assert run(["--mock", "preset", "list"], tr) == 0
    assert "alpha" in capsys.readouterr().out


def test_preset_save_duplicate_prints_already_exists(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LPK25_PRESET_DIR", str(tmp_path))
    tr = MockTransport()
    assert run(["--mock", "preset", "save", "dup2", "--from-slot", "1"], tr) == 0
    capsys.readouterr()  # clear
    rc = run(["--mock", "preset", "save", "dup2", "--from-slot", "1"], tr)
    assert rc != 0
    assert "already exists" in capsys.readouterr().err


def test_preset_apply_missing_prints_not_found(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LPK25_PRESET_DIR", str(tmp_path))
    tr = MockTransport()
    capsys.readouterr()  # clear
    rc = run(["--mock", "preset", "apply", "nosuchpreset", "1"], tr)
    assert rc != 0
    assert "not found" in capsys.readouterr().err


def test_preset_list_empty(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LPK25_PRESET_DIR", str(tmp_path))
    tr = MockTransport()
    capsys.readouterr()  # clear
    rc = run(["--mock", "preset", "list"], tr)
    assert rc == 0
    assert "(no presets)" in capsys.readouterr().out
