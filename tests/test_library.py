import os

import pytest

from lpk25 import library
from lpk25.model import Program


def prog(slot=1):
    return Program.from_payload(slot, bytes([slot, 0, 4, 12, 0, 0, 5, 0, 0, 3, 0, 120, 0]))


def test_preset_dir_env_override(monkeypatch):
    monkeypatch.setenv("LPK25_PRESET_DIR", "/tmp/lpk25-presets-xyz")
    assert library.preset_dir() == "/tmp/lpk25-presets-xyz"


def test_preset_dir_xdg(monkeypatch):
    monkeypatch.delenv("LPK25_PRESET_DIR", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", "/tmp/xdg")
    assert library.preset_dir() == "/tmp/xdg/lpk25/presets"


def test_preset_dir_default(monkeypatch):
    monkeypatch.delenv("LPK25_PRESET_DIR", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    assert library.preset_dir().endswith("/.config/lpk25/presets")


def test_save_and_load_round_trip(tmp_path):
    d = str(tmp_path)
    path = library.save_preset("bass", prog(1), directory=d)
    assert os.path.isfile(path)
    loaded = library.load_preset("bass", directory=d)
    assert loaded.raw == prog(1).raw


def test_save_refuses_overwrite_without_force(tmp_path):
    d = str(tmp_path)
    library.save_preset("bass", prog(1), directory=d)
    with pytest.raises(library.LibraryError):
        library.save_preset("bass", prog(2), directory=d)
    # force overwrites
    library.save_preset("bass", prog(3), force=True, directory=d)
    assert library.load_preset("bass", directory=d).raw[0] == 3


def test_load_missing_raises_with_available(tmp_path):
    d = str(tmp_path)
    library.save_preset("one", prog(1), directory=d)
    with pytest.raises(library.LibraryError) as exc:
        library.load_preset("nope", directory=d)
    assert "one" in str(exc.value)


def test_list_presets(tmp_path):
    d = str(tmp_path)
    library.save_preset("b", prog(1), directory=d)
    library.save_preset("a", prog(2), directory=d)
    assert library.list_preset_names(directory=d) == ["a", "b"]
    rows = library.list_presets(directory=d)
    assert [n for n, _ in rows] == ["a", "b"]


def test_list_names_missing_dir_is_empty(tmp_path):
    assert library.list_preset_names(directory=str(tmp_path / "nope")) == []
