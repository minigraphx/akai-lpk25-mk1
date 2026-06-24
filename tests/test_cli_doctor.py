from lpk25 import cli, diagnostics
from lpk25.device import Device
from lpk25.transport import MockTransport


def test_doctor_mock_all_green(capsys):
    rc = cli.main(["--mock", "doctor"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "All checks passed." in out
    assert "✅" in out
    assert "Device responds" in out


def test_doctor_mock_roundtrip(capsys, monkeypatch, tmp_path):
    def fake_make_device(args):
        dev = Device(MockTransport())
        dev.backup_dir = str(tmp_path)
        return dev

    monkeypatch.setattr(cli, "_make_device", fake_make_device)
    rc = cli.main(["--mock", "doctor", "--roundtrip"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Write round-trip" in out
    assert "verified" in out


def test_doctor_backend_missing_exits_nonzero(capsys, monkeypatch):
    monkeypatch.setattr(diagnostics, "_module_present", lambda name: False)
    rc = cli.main(["doctor"])  # not --mock: real backend path, simulated missing
    out = capsys.readouterr().out
    assert rc == 1
    assert "❌" in out
    assert "pip install 'lpk25[midi]'" in out
    assert "issue" in out
