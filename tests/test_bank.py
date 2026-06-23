import pytest

from lpk25 import cli, codec, library
from lpk25.model import Preset, Program
from lpk25.transport import MockTransport


def _preset4() -> Preset:
    return Preset(
        programs=[
            Program.from_payload(s, bytes([s, 0, 4, 12, 0, 0, 5, 0, 0, 3, 0, 120, 0]))
            for s in (1, 2, 3, 4)
        ]
    )


def run(argv, transport):
    orig = cli._make_transport
    cli._make_transport = lambda args: transport
    try:
        return cli.main(argv)
    finally:
        cli._make_transport = orig


# --- library layer --------------------------------------------------------

def test_save_and_load_bank_roundtrip(tmp_path):
    p = _preset4()
    path = library.save_bank("b", p, directory=str(tmp_path))
    assert path.endswith("b.json")
    loaded = library.load_bank("b", directory=str(tmp_path))
    assert [pr.slot for pr in loaded.programs] == [1, 2, 3, 4]
    assert loaded.programs[0].raw == p.programs[0].raw


def test_save_bank_overwrite_guard(tmp_path):
    p = _preset4()
    library.save_bank("b", p, directory=str(tmp_path))
    with pytest.raises(library.LibraryError):
        library.save_bank("b", p, directory=str(tmp_path))
    library.save_bank("b", p, force=True, directory=str(tmp_path))  # force ok


def test_load_missing_bank_errors(tmp_path):
    with pytest.raises(library.LibraryError):
        library.load_bank("ghost", directory=str(tmp_path))


def test_list_and_delete_bank(tmp_path):
    p = _preset4()
    library.save_bank("a", p, directory=str(tmp_path))
    library.save_bank("b", p, directory=str(tmp_path))
    assert library.list_bank_names(str(tmp_path)) == ["a", "b"]
    library.delete_bank("a", directory=str(tmp_path))
    assert library.list_bank_names(str(tmp_path)) == ["b"]
    with pytest.raises(library.LibraryError):
        library.delete_bank("a", directory=str(tmp_path))


def test_banks_and_presets_use_separate_dirs(tmp_path, monkeypatch):
    monkeypatch.delenv("LPK25_BANK_DIR", raising=False)
    monkeypatch.delenv("LPK25_PRESET_DIR", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert library.bank_dir() != library.preset_dir()
    assert library.bank_dir().endswith("banks")
    assert library.preset_dir().endswith("presets")


# --- CLI layer ------------------------------------------------------------

def test_bank_save_and_apply_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("LPK25_BANK_DIR", str(tmp_path))
    tr = MockTransport()
    run(["--mock", "edit", "1", "--channel", "7"], tr)
    run(["--mock", "edit", "2", "--tempo", "150"], tr)
    assert run(["--mock", "bank", "save", "live"], tr) == 0
    # disturb the device, then apply the bank to restore it
    run(["--mock", "edit", "1", "--channel", "1"], tr)
    assert run(["--mock", "bank", "apply", "live", "-y"], tr) == 0
    assert codec.decode_program(tr.programs[1])["midi_channel"] == 7
    assert codec.decode_program(tr.programs[2])["tempo"] == 150
    for s in (1, 2, 3, 4):
        assert tr.programs[s][0] == s  # slot-echo bytes correct


def test_bank_apply_confirm_no_aborts(tmp_path, monkeypatch):
    monkeypatch.setenv("LPK25_BANK_DIR", str(tmp_path))
    tr = MockTransport()
    run(["--mock", "bank", "save", "b"], tr)
    run(["--mock", "edit", "1", "--channel", "9"], tr)
    before = bytes(tr.programs[1])
    monkeypatch.setattr("builtins.input", lambda *a: "n")
    rc = run(["--mock", "bank", "apply", "b"], tr)
    assert rc == 1
    assert tr.programs[1] == before  # nothing written


def test_bank_apply_dry_run_previews_without_writing(tmp_path, monkeypatch):
    monkeypatch.setenv("LPK25_BANK_DIR", str(tmp_path))
    tr = MockTransport()
    run(["--mock", "edit", "1", "--channel", "7"], tr)
    run(["--mock", "bank", "save", "b"], tr)
    run(["--mock", "edit", "1", "--channel", "1"], tr)
    after = bytes(tr.programs[1])

    def _no_input(*a):
        raise AssertionError("--dry-run must not prompt")

    monkeypatch.setattr("builtins.input", _no_input)
    rc = run(["--mock", "--dry-run", "bank", "apply", "b"], tr)
    assert rc == 0
    assert tr.programs[1] == after  # preview wrote nothing


def test_bank_list_show_delete(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LPK25_BANK_DIR", str(tmp_path))
    tr = MockTransport()
    assert run(["--mock", "bank", "list"], tr) == 0
    assert "(no banks)" in capsys.readouterr().out
    run(["--mock", "bank", "save", "live"], tr)
    capsys.readouterr()
    assert run(["--mock", "bank", "list"], tr) == 0
    assert "live" in capsys.readouterr().out
    assert run(["--mock", "bank", "show", "live"], tr) == 0
    out = capsys.readouterr().out
    assert "tempo" in out and out.count("\n") >= 4   # header + 4 slots
    assert run(["--mock", "bank", "delete", "live"], tr) == 0
    assert run(["--mock", "bank", "list"], tr) == 0
    assert "(no banks)" in capsys.readouterr().out


def test_bank_save_overwrite_guard_cli(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LPK25_BANK_DIR", str(tmp_path))
    tr = MockTransport()
    assert run(["--mock", "bank", "save", "dup"], tr) == 0
    capsys.readouterr()
    rc = run(["--mock", "bank", "save", "dup"], tr)
    assert rc != 0
    assert "already exists" in capsys.readouterr().err
    assert run(["--mock", "bank", "save", "dup", "--force"], tr) == 0
