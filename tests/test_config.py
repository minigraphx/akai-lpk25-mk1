import argparse
import os

import pytest

from lpk25 import cli, config


def _args(**kw) -> argparse.Namespace:
    ns = argparse.Namespace(port=None, in_port=None, out_port=None, model=None)
    ns.__dict__.update(kw)
    return ns


def _write_cfg(tmp_path, text: str) -> str:
    p = tmp_path / "config.toml"
    p.write_text(text)
    return str(p)


# --- loading --------------------------------------------------------------

def test_load_missing_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("LPK25_CONFIG", str(tmp_path / "nope.toml"))
    assert config.load_config() == {}


def test_load_parses_toml(tmp_path, monkeypatch):
    monkeypatch.setenv("LPK25_CONFIG", _write_cfg(tmp_path, 'port = "MYKB"\nmodel = 0x77\n'))
    cfg = config.load_config()
    assert cfg["port"] == "MYKB"
    assert cfg["model"] == 0x77


def test_malformed_toml_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("LPK25_CONFIG", _write_cfg(tmp_path, "this is = = not toml"))
    with pytest.raises(config.ConfigError):
        config.load_config()


# --- precedence -----------------------------------------------------------

def test_precedence_cli_over_env_over_config(tmp_path, monkeypatch):
    monkeypatch.setenv("LPK25_CONFIG", _write_cfg(tmp_path, 'port = "FROMCFG"\nmodel = 0x70\n'))
    monkeypatch.delenv("LPK25_PORT", raising=False)
    a = _args()
    config.apply(a)
    assert a.port == "FROMCFG" and a.model == 0x70           # config only

    monkeypatch.setenv("LPK25_PORT", "FROMENV")
    a = _args()
    config.apply(a)
    assert a.port == "FROMENV"                                # env beats config

    a = _args(port="FROMCLI")
    config.apply(a)
    assert a.port == "FROMCLI"                                # CLI beats env


def test_default_port_when_nothing_set(tmp_path, monkeypatch):
    monkeypatch.setenv("LPK25_CONFIG", str(tmp_path / "none.toml"))
    monkeypatch.delenv("LPK25_PORT", raising=False)
    a = _args()
    config.apply(a)
    assert a.port == "LPK25"


def test_model_accepts_string(tmp_path, monkeypatch):
    monkeypatch.setenv("LPK25_CONFIG", _write_cfg(tmp_path, 'model = "0x78"\n'))
    a = _args()
    config.apply(a)
    assert a.model == 0x78


def test_bad_model_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("LPK25_CONFIG", _write_cfg(tmp_path, 'model = "nope"\n'))
    a = _args()
    with pytest.raises(config.ConfigError):
        config.apply(a)


# --- directory bridging ---------------------------------------------------

def test_config_dirs_bridge_to_env(tmp_path, monkeypatch):
    monkeypatch.setenv("LPK25_CONFIG", _write_cfg(
        tmp_path, f'preset_dir = "{tmp_path}/p"\nbank_dir = "{tmp_path}/b"\n'))
    monkeypatch.delenv("LPK25_PRESET_DIR", raising=False)
    monkeypatch.delenv("LPK25_BANK_DIR", raising=False)
    config.apply(_args())
    assert os.environ["LPK25_PRESET_DIR"] == f"{tmp_path}/p"
    assert os.environ["LPK25_BANK_DIR"] == f"{tmp_path}/b"


def test_env_dir_wins_over_config(tmp_path, monkeypatch):
    monkeypatch.setenv("LPK25_CONFIG", _write_cfg(tmp_path, f'preset_dir = "{tmp_path}/cfg"\n'))
    monkeypatch.setenv("LPK25_PRESET_DIR", f"{tmp_path}/env")
    config.apply(_args())
    assert os.environ["LPK25_PRESET_DIR"] == f"{tmp_path}/env"


def test_tilde_expansion_in_dirs(tmp_path, monkeypatch):
    monkeypatch.setenv("LPK25_CONFIG", _write_cfg(tmp_path, 'preset_dir = "~/lpk25p"\n'))
    monkeypatch.delenv("LPK25_PRESET_DIR", raising=False)
    config.apply(_args())
    assert os.environ["LPK25_PRESET_DIR"] == os.path.expanduser("~/lpk25p")


# --- cli `config` command -------------------------------------------------

def test_cli_config_shows_effective_values(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LPK25_CONFIG", _write_cfg(tmp_path, 'port = "STUDIO"\nmodel = 0x77\n'))
    assert cli.main(["config"]) == 0
    out = capsys.readouterr().out
    assert "config file:" in out
    assert "STUDIO" in out
    assert "0x77" in out


def test_cli_flag_overrides_config(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LPK25_CONFIG", _write_cfg(tmp_path, 'port = "STUDIO"\n'))
    assert cli.main(["--port", "LIVE", "config"]) == 0
    out = capsys.readouterr().out
    assert "LIVE" in out and "STUDIO" not in out


def test_cli_config_missing_file_noted(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LPK25_CONFIG", str(tmp_path / "absent.toml"))
    assert cli.main(["config"]) == 0
    assert "(not found)" in capsys.readouterr().out
