import pytest

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


def test_activate_sets_active_slot(capsys):
    tr = MockTransport()
    rc = run(["--mock", "activate", "3"], tr)
    assert rc == 0
    assert tr.active == 3
    assert "slot 3" in capsys.readouterr().out


def test_activate_then_show_marks_that_slot(capsys):
    tr = MockTransport()
    assert run(["--mock", "activate", "3"], tr) == 0
    capsys.readouterr()  # drop the activate output
    assert run(["--mock", "show"], tr) == 0
    out = capsys.readouterr().out
    # The single ▶-marked data row is slot 3 (slot is the first column).
    marked = [ln for ln in out.splitlines() if ln.startswith("▶")]
    assert len(marked) == 1
    assert marked[0].split()[1] == "3"


def test_activate_rejects_out_of_range_slot():
    tr = MockTransport()
    # argparse `choices` rejects this before the command runs.
    with pytest.raises(SystemExit):
        run(["--mock", "activate", "9"], tr)
    assert tr.active == 1  # unchanged


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


def test_edit_bool_off():
    tr = MockTransport()
    run(["--mock", "edit", "1", "--arp", "on"], tr)
    run(["--mock", "edit", "1", "--arp", "off"], tr)
    assert codec.decode_program(tr.programs[1])["arp_enabled"] is False


def test_copy_single_dst():
    tr = MockTransport()
    run(["--mock", "edit", "1", "--channel", "7"], tr)       # make slot 1 distinctive
    rc = run(["--mock", "copy", "1", "3", "--yes"], tr)
    assert rc == 0
    assert tr.programs[3][0] == 3                              # slot-echo corrected
    assert codec.decode_program(tr.programs[3])["midi_channel"] == 7


def test_copy_mirror_to_many_leaves_source():
    tr = MockTransport()
    run(["--mock", "edit", "1", "--channel", "9"], tr)
    rc = run(["--mock", "copy", "1", "2", "3", "4", "--yes"], tr)
    assert rc == 0
    for d in (2, 3, 4):
        assert codec.decode_program(tr.programs[d])["midi_channel"] == 9
        assert tr.programs[d][0] == d
    assert tr.programs[1][0] == 1                              # source slot echo intact


def test_copy_confirm_yes(monkeypatch):
    tr = MockTransport()
    run(["--mock", "edit", "1", "--channel", "5"], tr)
    monkeypatch.setattr("builtins.input", lambda *a: "y")
    rc = run(["--mock", "copy", "1", "2"], tr)                # no --yes -> prompts
    assert rc == 0
    assert codec.decode_program(tr.programs[2])["midi_channel"] == 5


def test_copy_confirm_no_aborts(monkeypatch):
    tr = MockTransport()
    before = bytes(tr.programs[2])
    monkeypatch.setattr("builtins.input", lambda *a: "n")
    rc = run(["--mock", "copy", "1", "2"], tr)
    assert rc == 1
    assert tr.programs[2] == before                           # nothing written


def test_copy_self_is_nothing():
    tr = MockTransport()
    rc = run(["--mock", "copy", "1", "1", "--yes"], tr)
    assert rc == 2


def test_copy_dedupes_dsts():
    tr = MockTransport()
    run(["--mock", "edit", "1", "--channel", "8"], tr)
    rc = run(["--mock", "copy", "1", "2", "2", "--yes"], tr)
    assert rc == 0
    assert codec.decode_program(tr.programs[2])["midi_channel"] == 8
    assert tr.programs[2][0] == 2


def test_copy_confirm_eof_aborts(monkeypatch):
    tr = MockTransport()
    before = bytes(tr.programs[2])
    def _raise(*a):
        raise EOFError
    monkeypatch.setattr("builtins.input", _raise)
    rc = run(["--mock", "copy", "1", "2"], tr)
    assert rc == 1
    assert tr.programs[2] == before
