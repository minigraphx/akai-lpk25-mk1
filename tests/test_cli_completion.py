"""Tests for the `lpk25 completion <shell>` command (issue #11).

These exercise the argcomplete-backed shellcode generation and the parser
wiring; they do not spawn a real shell.
"""

import pytest

from lpk25 import cli

argcomplete = pytest.importorskip("argcomplete")


def _run(argv, capsys):
    rc = cli.main(argv)
    return rc, capsys.readouterr()


def test_completion_bash_emits_registration(capsys):
    rc, out = _run(["completion", "bash"], capsys)
    assert rc == 0
    # The bash/zsh registration defines this function and binds it to `lpk25`.
    assert "_python_argcomplete" in out.out
    assert "lpk25" in out.out
    assert out.err == ""


def test_completion_zsh_emits_registration(capsys):
    rc, out = _run(["completion", "zsh"], capsys)
    assert rc == 0
    # argcomplete ships a combined bash/zsh script that branches on $ZSH_VERSION.
    assert "compdef _python_argcomplete lpk25" in out.out


def test_completion_fish_is_distinct(capsys):
    rc, out = _run(["completion", "fish"], capsys)
    assert rc == 0
    assert "__fish_lpk25_complete" in out.out
    assert "complete --command lpk25" in out.out
    # fish uses its own syntax, not the bash function.
    assert "compdef" not in out.out


def test_completion_autodetects_from_shell_env(capsys, monkeypatch):
    monkeypatch.setenv("SHELL", "/usr/local/bin/fish")
    rc, out = _run(["completion"], capsys)
    assert rc == 0
    assert "__fish_lpk25_complete" in out.out


def test_completion_unknown_shell_env_errors(capsys, monkeypatch):
    monkeypatch.setenv("SHELL", "/bin/tcsh")
    rc, out = _run(["completion"], capsys)
    assert rc == 2
    assert "could not detect your shell" in out.err


def test_completion_rejects_unsupported_shell(capsys):
    # argparse `choices` rejects this before the command runs.
    with pytest.raises(SystemExit):
        cli.main(["completion", "powershell"])


def test_completion_reports_missing_argcomplete(capsys, monkeypatch):
    # Simulate argcomplete not being installed: make its import fail.
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "argcomplete":
            raise ImportError("no argcomplete")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    rc, out = _run(["completion", "bash"], capsys)
    assert rc == 2
    assert "argcomplete" in out.err
