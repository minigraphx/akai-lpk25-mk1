from lpk25 import cli, codec, protocol
from lpk25.transport import MockTransport


def run(argv, transport):
    # Patch _make_transport so the CLI talks to our in-memory device.
    orig = cli._make_transport
    cli._make_transport = lambda args: transport
    try:
        return cli.main(argv)
    finally:
        cli._make_transport = orig


def _sent_opcodes(tr):
    ops = []
    for f in tr.sent:
        try:
            ops.append(protocol.parse_frame(f).opcode)
        except protocol.ProtocolError:
            pass
    return ops


def test_dry_run_edit_previews_without_writing(capsys):
    tr = MockTransport()
    before = bytes(tr.programs[1])
    rc = run(["--mock", "--dry-run", "edit", "1", "--channel", "5"], tr)
    assert rc == 0
    assert tr.programs[1] == before                     # nothing written
    out = capsys.readouterr().out
    assert "midi_channel" in out
    assert "dry run" in out
    assert protocol.OP_SEND_PROGRAM not in _sent_opcodes(tr)


def test_dry_run_reports_no_change(capsys):
    tr = MockTransport()
    # slot 1 default channel is 1; setting it to 1 changes nothing
    rc = run(["--mock", "--dry-run", "edit", "1", "--channel", "1"], tr)
    assert rc == 0
    assert "no change" in capsys.readouterr().out


def test_dry_run_copy_does_not_prompt_or_write(monkeypatch):
    tr = MockTransport()
    run(["--mock", "edit", "1", "--channel", "7"], tr)      # make slot 1 distinctive
    before = {s: bytes(tr.programs[s]) for s in (2, 3)}

    def _no_input(*a):
        raise AssertionError("--dry-run must not prompt")

    monkeypatch.setattr("builtins.input", _no_input)
    rc = run(["--mock", "--dry-run", "copy", "1", "2", "3"], tr)  # note: no --yes
    assert rc == 0
    assert tr.programs[2] == before[2] and tr.programs[3] == before[3]


def test_dry_run_set_previews_without_writing(tmp_path, capsys):
    tr = MockTransport()
    run(["--mock", "edit", "1", "--channel", "5"], tr)
    path = tmp_path / "p1.json"
    run(["--mock", "get", "1", "-o", str(path)], tr)
    before2 = bytes(tr.programs[2])
    capsys.readouterr()
    rc = run(["--mock", "--dry-run", "set", "2", str(path)], tr)
    assert rc == 0
    assert tr.programs[2] == before2
    out = capsys.readouterr().out
    assert "midi_channel" in out and "dry run" in out


def test_dry_run_load_writes_nothing(tmp_path):
    tr = MockTransport()
    path = tmp_path / "dump.json"
    run(["--mock", "dump", "-o", str(path)], tr)
    run(["--mock", "edit", "1", "--channel", "9"], tr)
    after_edit = bytes(tr.programs[1])
    rc = run(["--mock", "--dry-run", "load", str(path)], tr)
    assert rc == 0
    assert tr.programs[1] == after_edit                 # preview wrote nothing


def test_dry_run_restore_writes_nothing(tmp_path):
    tr = MockTransport()
    path = tmp_path / "backup.json"
    run(["--mock", "dump", "-o", str(path)], tr)
    run(["--mock", "edit", "1", "--channel", "9"], tr)
    after_edit = bytes(tr.programs[1])
    rc = run(["--mock", "--dry-run", "restore", str(path)], tr)
    assert rc == 0
    assert tr.programs[1] == after_edit


def test_dry_run_preset_apply_writes_nothing(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LPK25_PRESET_DIR", str(tmp_path))
    tr = MockTransport()
    run(["--mock", "edit", "1", "--channel", "6"], tr)
    run(["--mock", "preset", "save", "p", "--from-slot", "1"], tr)
    before2 = bytes(tr.programs[2])
    capsys.readouterr()
    rc = run(["--mock", "--dry-run", "preset", "apply", "p", "2"], tr)
    assert rc == 0
    assert tr.programs[2] == before2
    assert "dry run" in capsys.readouterr().out


def test_real_edit_still_writes():
    # sanity: without --dry-run the write still happens
    tr = MockTransport()
    rc = run(["--mock", "edit", "1", "--channel", "5"], tr)
    assert rc == 0
    assert codec.decode_program(tr.programs[1])["midi_channel"] == 5
