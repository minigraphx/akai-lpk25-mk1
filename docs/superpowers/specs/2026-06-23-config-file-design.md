# LPK25 mk1 CLI — Config File — Design

- **Date:** 2026-06-23
- **Status:** Approved (design discussion); ready for implementation
- **Author:** drafted collaboratively via the brainstorming method
- **Builds on:** the global CLI flags (`--port/--in-port/--out-port/--model`) and
  the `library._config_dir` env-var directories. Tracks issue #7.

## Problem

Connection settings (`--port`, `--model`, …) must be repeated on every command,
and only the *directories* have env vars — there's no persistent place to set a
default port or model. Power users running many commands per session want a
config file.

## Goal

A TOML config at `~/.config/lpk25/config.toml` providing defaults for the
connection settings and directories, with clear precedence and a `config`
command to inspect the resolved values.

## Non-goals (YAGNI)

- Writing/editing the config from the CLI (`config set …`) — hand-edit the file.
- Per-profile configs / multiple named profiles.
- Configuring per-command flags (e.g. default `--seconds`).

## Decisions (locked)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Keys | **connection + directories** (`port`, `in_port`, `out_port`, `model`, `preset_dir`, `bank_dir`, `backup_dir`) | one place for every default |
| Format / parse | **TOML**: stdlib `tomllib` on 3.11+, **conditional `tomli` dep** on <3.11 | full TOML on every supported Python |
| Inspect | **`lpk25 config`** command (effective values + file path) | debug precedence |
| Precedence | **CLI flag > env var > config file > built-in default** | least-surprise |
| Location | `$LPK25_CONFIG` else `<config>/lpk25/config.toml` | overridable (and test-isolatable) |

## Config file

```toml
# ~/.config/lpk25/config.toml
port = "LPK25"          # MIDI port name substring
# in_port = "..."       # exact input port (optional)
# out_port = "..."      # exact output port (optional)
model = 0x76            # device model byte
preset_dir = "~/Music/lpk25/presets"
bank_dir   = "~/Music/lpk25/banks"
backup_dir = "~/Music/lpk25/backups"
```

`~` in directory values is expanded.

## Precedence & resolution

Resolved once in `main()` (after `parse_args`, before dispatch):

- **Connection** (`port/in_port/out_port/model`): argparse defaults become
  `None`; resolve each as `CLI value if given else $LPK25_<KEY> else config[key]
  else built-in default` (`port` → `"LPK25"`, others → `None`/downstream default).
  `model` accepts an int (`0x76`) or string (`"0x76"`).
- **Directories**: bridge config → environment — if `$LPK25_<DIR>` is unset and
  the config provides it, set the env var (expanded) so `library` (already
  env-driven) picks it up. Env still wins over config; CLI has no dir flags.

This keeps `library`/`device` unchanged: they keep reading env vars.

## Architecture / components

```
src/lpk25/
  config.py     NEW — config_path(), load_config(), apply(args)
  cli.py        main() calls config.apply(args); + cmd_config + `config` subparser;
                connection flags default to None (resolved by config.apply)
pyproject.toml  + dependency: tomli ; python_version < "3.11"
conftest.py     autouse fixture also points $LPK25_CONFIG at a tmp (missing) file
```

### `config.py`

```python
ENV = {"port": "LPK25_PORT", "in_port": "LPK25_IN_PORT",
       "out_port": "LPK25_OUT_PORT", "model": "LPK25_MODEL"}
DIRS = {"preset_dir": "LPK25_PRESET_DIR", "bank_dir": "LPK25_BANK_DIR",
        "backup_dir": "LPK25_BACKUP_DIR"}

class ConfigError(RuntimeError): ...

def config_path() -> str: ...          # $LPK25_CONFIG or <config>/lpk25/config.toml
def load_config(path=None) -> dict: ... # {} if missing; ConfigError on bad TOML
def apply(args) -> dict: ...            # mutate args + os.environ per precedence
```

`load_config` imports `tomllib`, falling back to `tomli`; a clear `ConfigError`
if neither is available (only possible on <3.11 without the dep).

### `cli.cmd_config`

Prints the config file path (noting if absent) and the effective `port`,
`in_port`, `out_port`, `model`, and the three resolved directories
(`library.preset_dir()` etc., which already reflect any config→env bridging).

## Error handling

| Case | Behaviour |
|------|-----------|
| no config file | treated as empty; defaults apply |
| malformed TOML | `ConfigError` → rc 1 with the file path |
| bad `model` value | `ConfigError`/`ValueError` → rc 1 |
| `tomli` missing on <3.11 | `ConfigError` explaining the dependency |

## Testing (all offline)

- **config:** `load_config` returns `{}` when missing; parses a sample TOML;
  `apply` precedence — CLI flag beats env beats config beats default for `port`
  and `model`; config `*_dir` values populate the env only when unset (env wins);
  `~` expansion; malformed TOML raises `ConfigError`.
- **cli:** `lpk25 config` prints the resolved values and path; a config file
  (via `$LPK25_CONFIG`) changes the effective `port`/dirs; a CLI flag still
  overrides it.
- **isolation:** conftest points `$LPK25_CONFIG` at a missing tmp path so tests
  never read the developer's real config.

## Documentation

- README: document the config file, keys, precedence, and `lpk25 config`.
- Issue #7 closed by the implementing PR.
