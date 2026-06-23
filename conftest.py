"""Make ``src/`` importable during tests without an editable install."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))


@pytest.fixture(autouse=True)
def _isolate_lpk25_dirs(tmp_path, monkeypatch):
    """Point the preset/bank/backup directories at a per-test tmp dir so tests
    never read or write the real ``~/.config/lpk25`` (auto-backups included).
    Individual tests can still override any of these with ``monkeypatch.setenv``.
    """
    monkeypatch.setenv("LPK25_PRESET_DIR", str(tmp_path / "presets"))
    monkeypatch.setenv("LPK25_BANK_DIR", str(tmp_path / "banks"))
    monkeypatch.setenv("LPK25_BACKUP_DIR", str(tmp_path / "backups"))
