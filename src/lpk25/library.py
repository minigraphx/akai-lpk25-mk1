"""Named single-program preset library.

Presets are stored as the existing single-program ``Preset`` JSON, so they
interoperate with ``lpk25 get -o`` / ``lpk25 set``. All functions are pure file
operations with no device dependency.
"""

from __future__ import annotations

import os

from .model import Preset, Program


class LibraryError(RuntimeError):
    """Raised for preset-library problems (missing preset, overwrite guard)."""


def preset_dir() -> str:
    """Resolve the presets directory (does NOT create it).

    Precedence: ``$LPK25_PRESET_DIR`` > ``$XDG_CONFIG_HOME/lpk25/presets`` >
    ``~/.config/lpk25/presets``.
    """
    env = os.environ.get("LPK25_PRESET_DIR")
    if env:
        return env
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(
        os.path.expanduser("~"), ".config"
    )
    return os.path.join(base, "lpk25", "presets")


def _path(name: str, directory: str | None) -> str:
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
    preset = Preset.load(path)
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
