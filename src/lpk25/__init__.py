"""lpk25 — cross-platform program editor and SysEx library for the Akai LPK25 mk1.

Pure-Python core (``protocol``, ``codec``, ``model``) imports without the MIDI
backend; ``transport``/``device`` provide hardware access when ``lpk25[midi]`` is
installed.
"""

from __future__ import annotations

from . import codec, model, protocol
from .model import Preset, Program

__version__ = "0.1.0"

__all__ = ["protocol", "codec", "model", "Program", "Preset", "__version__"]
