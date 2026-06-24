"""Optional TOML config file for default connection settings and directories.

Resolution precedence (highest first): CLI flag > environment variable > config
file > built-in default. The config file is read once at startup by the CLI; the
``library``/``device`` layers keep reading their directory env vars, so this
module just *bridges* config values into the environment for directories and
fills in the connection arguments.
"""

from __future__ import annotations

import argparse
import os

# Connection settings: config key -> environment variable.
ENV = {
    "port": "LPK25_PORT",
    "in_port": "LPK25_IN_PORT",
    "out_port": "LPK25_OUT_PORT",
    "model": "LPK25_MODEL",
}

# Directory settings: config key -> environment variable consumed by `library`.
DIRS = {
    "preset_dir": "LPK25_PRESET_DIR",
    "bank_dir": "LPK25_BANK_DIR",
    "backup_dir": "LPK25_BACKUP_DIR",
}

DEFAULT_PORT = "LPK25"


class ConfigError(RuntimeError):
    """Raised when the config file is present but cannot be read or parsed."""


def config_path() -> str:
    """Resolve the config file path. ``$LPK25_CONFIG`` overrides the default
    ``<config>/lpk25/config.toml`` (XDG-aware)."""
    env = os.environ.get("LPK25_CONFIG")
    if env:
        return env
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(
        os.path.expanduser("~"), ".config"
    )
    return os.path.join(base, "lpk25", "config.toml")


def _toml_load(path: str) -> dict:
    try:
        import tomllib  # Python 3.11+
    except ModuleNotFoundError:
        try:
            import tomli as tomllib  # type: ignore[no-redef]
        except ModuleNotFoundError as exc:  # pragma: no cover - dep is declared
            raise ConfigError(
                "reading a TOML config on Python < 3.11 requires 'tomli' "
                "(pip install tomli)"
            ) from exc
    with open(path, "rb") as fh:
        return tomllib.load(fh)


def load_config(path: str | None = None) -> dict:
    """Load the config file as a dict. Returns ``{}`` if it does not exist;
    raises :class:`ConfigError` if it exists but is malformed."""
    path = path or config_path()
    if not os.path.exists(path):
        return {}
    try:
        return _toml_load(path)
    except ConfigError:
        raise
    except Exception as exc:  # noqa: BLE001 - surface any parse/IO error uniformly
        raise ConfigError(f"could not read config {path}: {exc}") from exc


def _coerce_model(value: object) -> int:
    """Accept an int (``0x76``) or a string (``"0x76"``/``"118"``)."""
    if isinstance(value, bool):  # bool is an int subclass; reject it explicitly
        raise ConfigError(f"invalid model {value!r}")
    if isinstance(value, int):
        return value
    try:
        return int(str(value), 0)
    except ValueError as exc:
        raise ConfigError(f"invalid model {value!r}") from exc


def apply(args: argparse.Namespace, config: dict | None = None) -> dict:
    """Fill in connection args and bridge directory settings into the environment
    following the precedence rules. Mutates ``args`` and ``os.environ`` in place
    and returns the loaded config dict."""
    cfg = load_config() if config is None else config

    # Connection: CLI (already on args) > env > config > default.
    if getattr(args, "port", None) is None:
        args.port = os.environ.get(ENV["port"]) or cfg.get("port") or DEFAULT_PORT
    if getattr(args, "in_port", None) is None:
        args.in_port = os.environ.get(ENV["in_port"]) or cfg.get("in_port")
    if getattr(args, "out_port", None) is None:
        args.out_port = os.environ.get(ENV["out_port"]) or cfg.get("out_port")
    if getattr(args, "model", None) is None:
        env_model = os.environ.get(ENV["model"])
        if env_model:
            args.model = _coerce_model(env_model)
        elif cfg.get("model") is not None:
            args.model = _coerce_model(cfg["model"])

    # Directories: env wins; otherwise bridge config -> env so `library` sees it.
    for key, env_var in DIRS.items():
        if not os.environ.get(env_var) and cfg.get(key):
            os.environ[env_var] = os.path.expanduser(str(cfg[key]))

    return cfg
