import os

import pytest

from lpk25 import cli, codec, library
from lpk25.model import Preset, Program
from lpk25.transport import MockTransport


def _write_backup(directory: str, stamp: str, mtime: float, channel: int = 1) -> str:
    os.makedirs(directory, exist_ok=True)
    prog = Program.from_payload(
        1, bytes([1, channel - 1, 4, 12, 0, 0, 5, 0, 0, 3, 0, 120, 0])
    )
    path = os.path.join(directory, f"lpk25-backup-{stamp}.json")
    Preset(programs=[prog]).save(path)
    os.utime(path, (mtime, mtime))
    return path


def run(argv, transport):
    orig = cli._make_transport
    cli._make_transport = lambda args: transport
    try:
        return cli.main(argv)
    finally:
        cli._make_transport = orig


# --- library --------------------------------------------------------------

def test_list_backup_paths_newest_first(tmp_path):
    d = str(tmp_path / "bk")
    _write_backup(d, "20260101-000001", mtime=100)
    _write_backup(d, "20260101-000002", mtime=200)
    _write_backup(d, "20260101-000003", mtime=300)
    names = [os.path.basename(p) for p in library.list_backup_paths(d)]
    assert names == [
        "lpk25-backup-20260101-000003.json",
        "lpk25-backup-20260101-000002.json",
        "lpk25-backup-20260101-000001.json",
    ]


def test_latest_backup(tmp_path):
    d = str(tmp_path / "bk")
    assert library.latest_backup(d) is None
    _write_backup(d, "20260101-000001", mtime=100)
    newest = _write_backup(d, "20260101-000002", mtime=200)
    assert library.latest_backup(d) == newest


def test_prune_keeps_newest_n(tmp_path):
    d = str(tmp_path / "bk")
    for i in range(1, 6):
        _write_backup(d, f"20260101-00000{i}", mtime=i * 100)
    deleted = library.prune_backups(2, d)
    assert len(deleted) == 3
    remaining = [os.path.basename(p) for p in library.list_backup_paths(d)]
    assert remaining == [
        "lpk25-backup-20260101-000005.json",
        "lpk25-backup-20260101-000004.json",
    ]


def test_prune_keep_zero_deletes_all(tmp_path):
    d = str(tmp_path / "bk")
    _write_backup(d, "20260101-000001", mtime=100)
    assert len(library.prune_backups(0, d)) == 1
    assert library.list_backup_paths(d) == []


def test_prune_negative_keep_errors(tmp_path):
    with pytest.raises(library.LibraryError):
        library.prune_backups(-1, str(tmp_path))


def test_backup_dir_env(tmp_path, monkeypatch):
    monkeypatch.setenv("LPK25_BACKUP_DIR", str(tmp_path / "custom"))
    assert library.backup_dir() == str(tmp_path / "custom")


# --- cli ------------------------------------------------------------------

def test_cli_backup_save_to_configured_dir(tmp_path, monkeypatch, capsys):
    d = tmp_path / "bk"
    monkeypatch.setenv("LPK25_BACKUP_DIR", str(d))
    tr = MockTransport()
    assert run(["--mock", "backup"], tr) == 0          # bare backup = save
    assert len(list(d.glob("lpk25-backup-*.json"))) == 1
    assert "Backup written to" in capsys.readouterr().out


def test_cli_backup_list_newest_first(tmp_path, monkeypatch, capsys):
    d = str(tmp_path / "bk")
    _write_backup(d, "20260101-000001", mtime=100, channel=3)
    _write_backup(d, "20260101-000002", mtime=200, channel=5)
    monkeypatch.setenv("LPK25_BACKUP_DIR", d)
    tr = MockTransport()
    assert run(["--mock", "backup", "list"], tr) == 0
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
    assert lines[0].startswith("lpk25-backup-20260101-000002.json")
    assert "ch[" in lines[0]


def test_cli_backup_list_empty(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LPK25_BACKUP_DIR", str(tmp_path / "bk"))
    tr = MockTransport()
    assert run(["--mock", "backup", "list"], tr) == 0
    assert "(no backups)" in capsys.readouterr().out


def test_cli_backup_prune(tmp_path, monkeypatch):
    d = str(tmp_path / "bk")
    for i in range(1, 5):
        _write_backup(d, f"20260101-00000{i}", mtime=i * 100)
    monkeypatch.setenv("LPK25_BACKUP_DIR", d)
    tr = MockTransport()
    assert run(["--mock", "backup", "prune", "--keep", "1", "-y"], tr) == 0
    assert len(library.list_backup_paths(d)) == 1


def test_cli_backup_prune_confirm_no_keeps_all(tmp_path, monkeypatch):
    d = str(tmp_path / "bk")
    for i in range(1, 4):
        _write_backup(d, f"20260101-00000{i}", mtime=i * 100)
    monkeypatch.setenv("LPK25_BACKUP_DIR", d)
    monkeypatch.setattr("builtins.input", lambda *a: "n")
    tr = MockTransport()
    rc = run(["--mock", "backup", "prune", "--keep", "1"], tr)
    assert rc == 1
    assert len(library.list_backup_paths(d)) == 3   # nothing deleted


def test_cli_restore_latest(tmp_path, monkeypatch):
    d = str(tmp_path / "bk")
    monkeypatch.setenv("LPK25_BACKUP_DIR", d)
    _write_backup(d, "20260101-000001", mtime=100, channel=3)
    _write_backup(d, "20260101-000002", mtime=200, channel=7)  # newest
    tr = MockTransport()
    assert run(["--mock", "restore", "--latest"], tr) == 0
    assert codec.decode_program(tr.programs[1])["midi_channel"] == 7


def test_cli_restore_no_args_errors(tmp_path):
    tr = MockTransport()
    assert run(["--mock", "restore"], tr) == 2
