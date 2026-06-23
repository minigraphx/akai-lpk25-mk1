"""Named single-program preset library.

Presets are stored as the existing single-program ``Preset`` JSON, so they
interoperate with ``lpk25 get -o`` / ``lpk25 set``. All functions are pure file
operations with no device dependency.
"""

from __future__ import annotations

import json
import os

from .model import Preset, Program


class LibraryError(RuntimeError):
    """Raised for preset-library problems (missing preset, overwrite guard)."""


def _config_dir(env_var: str, subdir: str) -> str:
    """Resolve a config subdirectory (does NOT create it).

    Precedence: ``$<env_var>`` > ``$XDG_CONFIG_HOME/lpk25/<subdir>`` >
    ``~/.config/lpk25/<subdir>``.
    """
    env = os.environ.get(env_var)
    if env:
        return env
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(
        os.path.expanduser("~"), ".config"
    )
    return os.path.join(base, "lpk25", subdir)


def preset_dir() -> str:
    """Resolve the single-program presets directory (``$LPK25_PRESET_DIR``)."""
    return _config_dir("LPK25_PRESET_DIR", "presets")


def bank_dir() -> str:
    """Resolve the full-device banks directory (``$LPK25_BANK_DIR``)."""
    return _config_dir("LPK25_BANK_DIR", "banks")


def backup_dir() -> str:
    """Resolve the device-backup directory (``$LPK25_BACKUP_DIR``)."""
    return _config_dir("LPK25_BACKUP_DIR", "backups")


def _validate_name(name: str) -> None:
    if not name or name in (".", "..") or os.path.basename(name) != name:
        raise LibraryError(
            f"invalid preset name {name!r} (must be a bare name, no path separators)"
        )


def _path(name: str, directory: str | None) -> str:
    _validate_name(name)
    return os.path.join(directory or preset_dir(), f"{name}.json")


def save_preset(
    name: str, program: Program, force: bool = False, directory: str | None = None
) -> str:
    """Save ``program`` as a single-program preset named ``name``. Returns the path.

    Refuses to overwrite an existing preset unless ``force`` is True."""
    path = _path(name, directory)
    if os.path.exists(path) and not force:
        raise LibraryError(f"preset {name!r} already exists (use --force to overwrite)")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    Preset(programs=[program]).save(path)
    return path


def load_preset(name: str, directory: str | None = None) -> Program:
    """Load the single program from preset ``name``."""
    path = _path(name, directory)
    if not os.path.exists(path):
        avail = ", ".join(list_preset_names(directory)) or "(none)"
        raise LibraryError(f"preset {name!r} not found. Available: {avail}")
    try:
        preset = Preset.load(path)
    except (json.JSONDecodeError, OSError, ValueError) as exc:
        raise LibraryError(f"preset {name!r} is unreadable: {exc}") from exc
    if not preset.programs:
        raise LibraryError(f"preset {name!r} contains no program")
    return preset.programs[0]


def list_preset_names(directory: str | None = None) -> list[str]:
    """Sorted names of saved presets (empty if the directory does not exist)."""
    directory = directory or preset_dir()
    if not os.path.isdir(directory):
        return []
    return sorted(f[:-5] for f in os.listdir(directory) if f.endswith(".json"))


def list_presets(directory: str | None = None) -> list[tuple[str, Program]]:
    """(name, program) pairs for every readable preset."""
    out: list[tuple[str, Program]] = []
    for name in list_preset_names(directory):
        try:
            out.append((name, load_preset(name, directory)))
        except LibraryError:
            continue
    return out


# --- banks (full 4-program device state) ----------------------------------

def save_bank(
    name: str, preset: Preset, force: bool = False, directory: str | None = None
) -> str:
    """Save a full ``Preset`` (all 4 programs) as a named bank. Returns the path.

    Refuses to overwrite an existing bank unless ``force`` is True."""
    path = _path(name, directory or bank_dir())
    if os.path.exists(path) and not force:
        raise LibraryError(f"bank {name!r} already exists (use --force to overwrite)")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    preset.save(path)
    return path


def load_bank(name: str, directory: str | None = None) -> Preset:
    """Load the full ``Preset`` stored in bank ``name``."""
    path = _path(name, directory or bank_dir())
    if not os.path.exists(path):
        avail = ", ".join(list_bank_names(directory)) or "(none)"
        raise LibraryError(f"bank {name!r} not found. Available: {avail}")
    try:
        preset = Preset.load(path)
    except (json.JSONDecodeError, OSError, ValueError) as exc:
        raise LibraryError(f"bank {name!r} is unreadable: {exc}") from exc
    if not preset.programs:
        raise LibraryError(f"bank {name!r} contains no programs")
    return preset


def list_bank_names(directory: str | None = None) -> list[str]:
    """Sorted names of saved banks (empty if the directory does not exist)."""
    directory = directory or bank_dir()
    if not os.path.isdir(directory):
        return []
    return sorted(f[:-5] for f in os.listdir(directory) if f.endswith(".json"))


def list_banks(directory: str | None = None) -> list[tuple[str, Preset]]:
    """(name, preset) pairs for every readable bank."""
    out: list[tuple[str, Preset]] = []
    for name in list_bank_names(directory):
        try:
            out.append((name, load_bank(name, directory)))
        except LibraryError:
            continue
    return out


def delete_bank(name: str, directory: str | None = None) -> str:
    """Delete bank ``name``. Returns the removed path; errors if it is missing."""
    path = _path(name, directory or bank_dir())
    if not os.path.exists(path):
        avail = ", ".join(list_bank_names(directory)) or "(none)"
        raise LibraryError(f"bank {name!r} not found. Available: {avail}")
    os.remove(path)
    return path


# --- device backups -------------------------------------------------------

def list_backup_paths(directory: str | None = None) -> list[str]:
    """Full paths of ``lpk25-backup-*.json`` files, newest first.

    Sorted by mtime (filename as a stable tiebreaker)."""
    directory = directory or backup_dir()
    if not os.path.isdir(directory):
        return []
    paths = [
        os.path.join(directory, f)
        for f in os.listdir(directory)
        if f.startswith("lpk25-backup-") and f.endswith(".json")
    ]
    paths.sort(key=lambda p: (os.path.getmtime(p), os.path.basename(p)), reverse=True)
    return paths


def latest_backup(directory: str | None = None) -> str | None:
    """Path of the most recent backup, or None if there are none."""
    paths = list_backup_paths(directory)
    return paths[0] if paths else None


def prune_backups(keep: int, directory: str | None = None) -> list[str]:
    """Delete all but the newest ``keep`` backups. Returns the removed paths."""
    if keep < 0:
        raise LibraryError("keep must be >= 0")
    to_delete = list_backup_paths(directory)[keep:]
    for p in to_delete:
        os.remove(p)
    return to_delete
