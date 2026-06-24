from lpk25 import cli
from lpk25.transport import MockTransport


def test_tui_requires_a_tty(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdout.isatty", lambda: False)
    rc = cli.main(["--mock", "tui"])
    assert rc == 2
    assert "terminal" in capsys.readouterr().err.lower()


def test_tui_invokes_app_run_when_tty(monkeypatch):
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    called = {}

    def fake_run(transport, mock):
        called["mock"] = mock
        return 0

    monkeypatch.setattr("lpk25.tui.app.run", fake_run)
    monkeypatch.setattr(cli, "_make_transport", lambda args: MockTransport())
    rc = cli.main(["--mock", "tui"])
    assert rc == 0
    assert called["mock"] is True
