"""Command-line interface for the LPK25 mk1 editor.

Hardware commands need the MIDI extra (``pip install 'lpk25[midi]'``). Pure
discovery/formatting still works without it via ``--mock``.
"""

from __future__ import annotations

import argparse
import os
import sys

from . import __version__, codec, config, library, protocol, render
from .model import Preset


def _eprint(*args: object) -> None:
    print(*args, file=sys.stderr)


def _make_transport(args: argparse.Namespace):
    if getattr(args, "mock", False):
        from .transport import MockTransport

        return MockTransport(model=args.model if args.model is not None else 0x76)
    from .transport import MidoTransport

    return MidoTransport(
        port_match=args.port,
        input_name=args.in_port,
        output_name=args.out_port,
    )


def _make_device(args: argparse.Namespace):
    from .device import Device

    return Device(_make_transport(args), model=args.model)


def _format_change(c) -> str:
    """One readable line for a codec.diff_payloads change (shared by `diff`
    and `--dry-run`)."""
    old = "--" if c.old is None else f"0x{c.old:02X} ({c.old})"
    new = "--" if c.new is None else f"0x{c.new:02X} ({c.new})"
    label = c.field or "unmapped"
    mark = "confirmed" if c.verified else "unverified"
    return f"  idx {c.index:2d}: {old} -> {new}   {label} [{mark}]"


def _preview(dev, programs) -> int:
    """Dry-run a set of writes: read each target slot and print what would
    change, writing nothing. Mirrors the device's slot-echo handling (byte 0 is
    the slot) so the diff matches exactly what a real write would store."""
    for prog in programs:
        current = dev.get_program(prog.slot)
        target = bytes([prog.slot]) + prog.to_payload()[1:]
        changes = codec.diff_payloads(current.raw, target)
        if not changes:
            print(f"slot {prog.slot}: no change")
            continue
        print(f"slot {prog.slot}: {len(changes)} byte(s) would change")
        for c in changes:
            print(_format_change(c))
    print("\n(dry run — nothing written)")
    return 0


# --- commands -------------------------------------------------------------

def cmd_ports(args: argparse.Namespace) -> int:
    from .transport import list_ports

    ports = list_ports()
    print("Inputs:")
    for n in ports["inputs"]:
        print(f"  {n}")
    print("Outputs:")
    for n in ports["outputs"]:
        print(f"  {n}")
    return 0


def cmd_config(args: argparse.Namespace) -> int:
    """Show the effective configuration (after CLI > env > config > default)."""
    path = config.config_path()
    print(f"config file: {path}" + ("" if os.path.exists(path) else " (not found)"))
    print(f"port:       {args.port}")
    print(f"in_port:    {args.in_port or '(auto)'}")
    print(f"out_port:   {args.out_port or '(auto)'}")
    print(f"model:      {hex(args.model) if args.model is not None else '0x76 (default)'}")
    print(f"preset_dir: {library.preset_dir()}")
    print(f"bank_dir:   {library.bank_dir()}")
    print(f"backup_dir: {library.backup_dir()}")
    return 0


def cmd_identify(args: argparse.Namespace) -> int:
    from .discovery import identify, probe_models

    with _make_transport(args) as tr:
        ident = identify(tr)
        if ident is not None:
            is_akai = ident.manufacturer == protocol.MANUFACTURER_AKAI
            mfr = "Akai" if is_akai else hex(ident.manufacturer)
            print("Device Inquiry reply:")
            print(f"  manufacturer: {mfr} (0x{ident.manufacturer:02X})")
            print(f"  family:       {ident.family}")
            print(f"  member:       {ident.member}")
            print(f"  version:      {ident.version.hex(' ') if ident.version else '(none)'}")
            if 0 <= ident.family <= 0x7F:
                print(f"  -> model byte (family LSB): 0x{ident.family:02X}")
        else:
            print("No Device Inquiry reply.")

        print("\nProbing candidate model bytes (read-only)...")
        any_ok = False
        for r in probe_models(tr):
            status = "RESPONDED" if r.responded else "-"
            print(f"  model 0x{r.model:02X}: {status}")
            any_ok = any_ok or r.responded
        if not any_ok:
            _eprint(
                "\nNo model responded. The mk1 framing may differ from the hypothesis; "
                "capture raw replies with 'lpk25 raw-recv' while pressing buttons, and share them."
            )
            return 2
    return 0


def cmd_monitor(args: argparse.Namespace) -> int:
    import time

    from . import mididecode

    with _make_transport(args) as tr:
        mon = getattr(tr, "monitor", None)
        if mon is None:
            _eprint("This transport does not support monitoring.")
            return 2
        print(f"Monitoring MIDI input for {args.seconds}s. Play the keyboard... (Ctrl-C to stop)")

        start: list[float] = []

        def show(frame: bytes) -> None:
            if not args.all and mididecode.is_noise(frame):
                return
            t = None
            if args.timestamps:
                now = time.monotonic()
                if not start:
                    start.append(now)
                t = now - start[0]
            print(mididecode.format_line(frame, raw=args.raw, t=t))

        try:
            mon(show, duration=args.seconds)
        except KeyboardInterrupt:
            pass
    return 0


def cmd_raw_recv(args: argparse.Namespace) -> int:
    with _make_transport(args) as tr:
        print(f"Listening for raw MIDI for {args.seconds}s...")
        captured: list[bytes] = []

        def show(frame: bytes) -> None:
            captured.append(frame)
            print(" ".join(f"{b:02X}" for b in frame))

        mon = getattr(tr, "monitor", None)
        if mon is None:
            _eprint("This transport does not support monitoring.")
            return 2
        try:
            mon(show, duration=args.seconds)
        except KeyboardInterrupt:
            pass
        if args.output and captured:
            with open(args.output, "wb") as fh:
                for frame in captured:
                    fh.write(bytes(frame))
            print(f"Wrote {len(captured)} message(s) to {args.output}")
    return 0


def cmd_raw_send(args: argparse.Namespace) -> int:
    with open(args.file, "rb") as fh:
        blob = fh.read()
    frames = _split_syx(blob)
    with _make_transport(args) as tr:
        for frame in frames:
            tr.send(frame)
        print(f"Sent {len(frames)} SysEx frame(s) from {args.file}")
    return 0


def cmd_dump(args: argparse.Namespace) -> int:
    dev = _make_device(args)
    preset = dev.dump()
    text = preset.to_json()
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"Wrote {len(preset.programs)} program(s) to {args.output}")
    else:
        print(text)
    _warn_unverified()
    return 0


def cmd_get(args: argparse.Namespace) -> int:
    dev = _make_device(args)
    program = dev.get_program(args.slot)
    preset = Preset(programs=[program], device_model=dev.config.model)
    text = preset.to_json()
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"Wrote program {args.slot} to {args.output}")
    else:
        print(text)
    _warn_unverified()
    return 0


def cmd_set(args: argparse.Namespace) -> int:
    preset = Preset.load(args.file)
    if not preset.programs:
        _eprint("No program found in file.")
        return 2
    program = preset.programs[0]
    program.slot = args.slot
    dev = _make_device(args)
    if args.dry_run:
        return _preview(dev, [program])
    result = dev.send_program(program, verify=not args.no_verify)
    print(f"Wrote program {result.slot}; verified={result.verified}; backup={result.backup_path}")
    return 0


def cmd_diff(args: argparse.Namespace) -> int:
    """Compare two dump/get JSON files byte-by-byte (offline, no device).

    The field-mapping workhorse: dump a baseline, change ONE setting on the
    device, dump again, and `diff` to see exactly which byte moved."""
    a = Preset.load(args.a)
    b = Preset.load(args.b)
    a_by_slot = {p.slot: p for p in a.programs}
    b_by_slot = {p.slot: p for p in b.programs}
    common = sorted(set(a_by_slot) & set(b_by_slot))
    if not common:
        _eprint("no slots in common between the two files")
        return 2
    total = 0
    for slot in common:
        changes = codec.diff_payloads(a_by_slot[slot].raw, b_by_slot[slot].raw)
        if not changes:
            print(f"slot {slot}: identical ({len(a_by_slot[slot].raw)} bytes)")
            continue
        total += len(changes)
        print(f"slot {slot}: {len(changes)} byte(s) changed")
        for c in changes:
            print(_format_change(c))
    if total == 0:
        print("\nNo differences — the change may not have persisted to the program "
              "(try reselecting the program with the Prog button before re-reading).")
    return 0


# Maps each `edit`/`set-field` CLI dest to its codec field name.
EDIT_FLAGS = {
    "channel": "midi_channel",
    "octave": "keybed_octave",
    "transpose": "transpose",
    "arp": "arp_enabled",
    "arp_mode": "arp_mode",
    "time_div": "time_division",
    "clock": "clock",
    "latch": "arp_latch",
    "tempo": "tempo",
    "taps": "tempo_taps",
    "arp_octave": "arp_octave",
}


def _collect_edits(args: argparse.Namespace) -> dict:
    values: dict = {}
    for dest, field in EDIT_FLAGS.items():
        v = getattr(args, dest, None)
        if v is None:
            continue
        if field in ("arp_enabled", "arp_latch"):
            v = v == "on"
        values[field] = v
    return values


def cmd_edit(args: argparse.Namespace) -> int:
    from .model import Program

    values = _collect_edits(args)
    if not values:
        _eprint("nothing to change (pass at least one field flag, e.g. --channel 5)")
        return 2
    dev = _make_device(args)
    before = dev.get_program(args.slot)
    patched = Program(
        slot=args.slot,
        values={**codec.decode_program(before.raw), **values},
        raw=before.raw,
    )
    if args.dry_run:
        return _preview(dev, [patched])
    result = dev.send_program(patched, verify=not args.no_verify)
    after = dev.get_program(args.slot)
    print(f"Wrote program {result.slot}; verified={result.verified}; "
          f"backup={result.backup_path}")
    for c in codec.diff_payloads(before.raw, after.raw):
        label = c.field or f"idx{c.index}"
        print(f"  {label}: {c.old} -> {c.new}")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    dev = _make_device(args)
    if args.json:
        print(dev.dump().to_json())
        return 0
    if args.slot is not None:
        print(render.format_program(dev.get_program(args.slot)))
        return 0
    print(render.format_presets_table(dev.dump(), dev.get_active_program()))
    return 0


def cmd_preset(args: argparse.Namespace) -> int:
    if args.preset_action == "list":
        rows = library.list_presets()
        if not rows:
            print("(no presets)")
            return 0
        for name, prog in rows:
            v = codec.decode_program(prog.raw)
            print(f"{name}: ch{v['midi_channel']} oct{v['keybed_octave']:+d} "
                  f"arp={'on' if v['arp_enabled'] else 'off'} tempo{v['tempo']}")
        return 0

    try:
        if args.preset_action == "save":
            dev = _make_device(args)
            prog = dev.get_program(args.from_slot)
            path = library.save_preset(args.name, prog, force=args.force)
            print(f"Saved preset {args.name} to {path}")
            return 0

        if args.preset_action == "apply":
            prog = library.load_preset(args.name)
            dev = _make_device(args)
            target = prog.reslot(args.slot)
            if args.dry_run:
                return _preview(dev, [target])
            result = dev.send_program(target, verify=not args.no_verify)
            print(f"Applied preset {args.name} to slot {result.slot}; "
                  f"verified={result.verified}")
            return 0
    except library.LibraryError as exc:
        _eprint(f"error: {exc}")
        return 1

    _eprint("unknown preset action")
    return 2


def _confirm(prompt: str) -> bool:
    """Ask a yes/no question on stdin. True only for 'y'/'yes' (case-insensitive).
    Treats EOF (closed stdin) as 'no'."""
    try:
        return input(prompt).strip().lower() in ("y", "yes")
    except EOFError:
        return False


def cmd_copy(args: argparse.Namespace) -> int:
    src = args.src
    dsts = sorted(set(args.dst))
    if src in dsts:
        dsts.remove(src)
        _eprint(f"skipping slot {src} (same as source)")
    if not dsts:
        _eprint("nothing to copy (destination is the source)")
        return 2
    # Confirm before any device read (skipped for --dry-run, which writes nothing).
    if not args.yes and not args.dry_run:
        slots = ", ".join(str(d) for d in dsts)
        prompt = f"About to overwrite slot(s) {slots} with a copy of slot {src}. Proceed? [y/N] "
        if not _confirm(prompt):
            _eprint("aborted; nothing written")
            return 1
    dev = _make_device(args)
    src_prog = dev.get_program(src)
    programs = [src_prog.reslot(d) for d in dsts]
    if args.dry_run:
        return _preview(dev, programs)
    results = dev.load(Preset(programs=programs), verify=not args.no_verify)
    for r in results:
        print(f"  slot {r.slot}: verified={r.verified}")
    if results:
        print(f"backup: {results[0].backup_path}")
    return 0


def cmd_load(args: argparse.Namespace) -> int:
    preset = Preset.load(args.file)
    dev = _make_device(args)
    if args.dry_run:
        return _preview(dev, preset.programs)
    results = dev.load(preset, verify=not args.no_verify)
    for r in results:
        print(f"  slot {r.slot}: verified={r.verified}")
    if results:
        print(f"backup: {results[0].backup_path}")
    return 0


def _backup_summary(path: str) -> str:
    try:
        preset = Preset.load(path)
    except (OSError, ValueError):
        return "(unreadable)"
    chans = ",".join(
        str(codec.decode_program(p.raw).get("midi_channel", "?")) for p in preset.programs
    )
    return f"{len(preset.programs)} programs, ch[{chans}]"


def cmd_backup(args: argparse.Namespace) -> int:
    action = getattr(args, "backup_action", None) or "save"
    directory = args.output  # None -> the configured default ($LPK25_BACKUP_DIR)

    if action == "save":
        dev = _make_device(args)
        path = dev.backup(directory) if directory else dev.backup()
        print(f"Backup written to {path}")
        return 0

    if action == "list":
        paths = library.list_backup_paths(directory)
        if not paths:
            print("(no backups)")
            return 0
        for p in paths:
            print(f"{os.path.basename(p)}  {_backup_summary(p)}")
        return 0

    if action == "prune":
        paths = library.list_backup_paths(directory)
        doomed = paths[args.keep:]
        if not doomed:
            print(f"nothing to prune ({len(paths)} backup(s), keeping {args.keep})")
            return 0
        if not args.yes and not _confirm(
            f"Delete {len(doomed)} old backup(s), keeping the newest {args.keep}? [y/N] "
        ):
            _eprint("aborted; nothing deleted")
            return 1
        deleted = library.prune_backups(args.keep, directory)
        print(f"Deleted {len(deleted)} backup(s); kept {len(paths) - len(deleted)}.")
        return 0

    _eprint("unknown backup action")
    return 2


def cmd_restore(args: argparse.Namespace) -> int:
    dev = _make_device(args)
    path = args.file
    if args.latest:
        path = library.latest_backup()
        if path is None:
            _eprint("no backups found to restore")
            return 2
        print(f"Restoring latest backup: {path}")
    if path is None:
        _eprint("specify a backup file or --latest")
        return 2
    if args.dry_run:
        return _preview(dev, Preset.load(path).programs)
    results = dev.restore(path, verify=not args.no_verify)
    for r in results:
        print(f"  slot {r.slot}: verified={r.verified}")
    return 0


def cmd_bank(args: argparse.Namespace) -> int:
    """Named full-device banks: save/apply/list/show/delete all 4 programs."""
    if args.bank_action == "list":
        rows = library.list_banks()
        if not rows:
            print("(no banks)")
            return 0
        for name, preset in rows:
            print(f"{name} ({len(preset.programs)} programs)")
        return 0

    try:
        if args.bank_action == "save":
            dev = _make_device(args)
            preset = dev.dump()
            path = library.save_bank(args.name, preset, force=args.force)
            print(f"Saved bank {args.name} ({len(preset.programs)} programs) to {path}")
            return 0

        if args.bank_action == "show":
            print(render.format_presets_table(library.load_bank(args.name)))
            return 0

        if args.bank_action == "delete":
            path = library.delete_bank(args.name)
            print(f"Deleted bank {args.name} ({path})")
            return 0

        if args.bank_action == "apply":
            preset = library.load_bank(args.name)
            dev = _make_device(args)
            if args.dry_run:
                return _preview(dev, preset.programs)
            if not args.yes:
                n = len(preset.programs)
                prompt = (f"About to overwrite {n} slot(s) from bank {args.name!r}. "
                          "Proceed? [y/N] ")
                if not _confirm(prompt):
                    _eprint("aborted; nothing written")
                    return 1
            results = dev.load(preset, verify=not args.no_verify)
            for r in results:
                print(f"  slot {r.slot}: verified={r.verified}")
            if results:
                print(f"backup: {results[0].backup_path}")
            return 0
    except library.LibraryError as exc:
        _eprint(f"error: {exc}")
        return 1

    _eprint("unknown bank action")
    return 2


# --- helpers --------------------------------------------------------------

def _split_syx(blob: bytes) -> list[bytes]:
    frames: list[bytes] = []
    cur = bytearray()
    for b in blob:
        if b == 0xF0:
            cur = bytearray([b])
        elif b == 0xF7 and cur:
            cur.append(b)
            frames.append(bytes(cur))
            cur = bytearray()
        elif cur:
            cur.append(b)
    return frames


def _warn_unverified() -> None:
    if not codec.all_verified():
        _eprint(
            "\nNOTE: the program field map is still PROVISIONAL (unverified against "
            "real hardware). Decoded values may be wrong; raw bytes are exact. "
            "See docs/protocol.md."
        )


# --- argument parser ------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="lpk25", description="Akai LPK25 mk1 editor")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument("--port", default=None,
                   help="substring to match the MIDI port name (default: LPK25, or config)")
    p.add_argument("--in-port", default=None, help="exact MIDI input port name")
    p.add_argument("--out-port", default=None, help="exact MIDI output port name")
    p.add_argument(
        "--model", type=lambda s: int(s, 0), default=None,
        help="device model byte (e.g. 0x76); overrides the default guess",
    )
    p.add_argument("--mock", action="store_true", help="use the in-memory fake device")
    p.add_argument(
        "--dry-run", action="store_true",
        help="for write commands: read the target slot(s) and print what would "
             "change, without writing or backing up",
    )

    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("ports", help="list MIDI ports").set_defaults(func=cmd_ports)
    sub.add_parser("identify", help="device inquiry + model probe").set_defaults(func=cmd_identify)
    sub.add_parser("config", help="show the effective configuration and file path"
                   ).set_defaults(func=cmd_config)

    mon = sub.add_parser("monitor", help="print the keyboard's live MIDI output (decoded)")
    mon.add_argument("--seconds", type=float, default=30.0)
    mon.add_argument("--raw", action="store_true", help="print raw hex instead of decoded text")
    mon.add_argument("--all", action="store_true",
                     help="also show Active Sensing and Clock (hidden by default)")
    mon.add_argument("--timestamps", action="store_true",
                     help="prefix each line with a relative timestamp")
    mon.set_defaults(func=cmd_monitor)

    rr = sub.add_parser("raw-recv", help="capture raw MIDI to a .syx file")
    rr.add_argument("--seconds", type=float, default=15.0)
    rr.add_argument("-o", "--output", default=None)
    rr.set_defaults(func=cmd_raw_recv)

    rs = sub.add_parser("raw-send", help="replay a .syx file to the device")
    rs.add_argument("file")
    rs.set_defaults(func=cmd_raw_send)

    d = sub.add_parser("dump", help="read all 4 programs")
    d.add_argument("-o", "--output", default=None)
    d.set_defaults(func=cmd_dump)

    g = sub.add_parser("get", help="read one program")
    g.add_argument("slot", type=int, choices=(1, 2, 3, 4))
    g.add_argument("-o", "--output", default=None)
    g.set_defaults(func=cmd_get)

    df = sub.add_parser("diff", help="compare two dump/get JSON files (offline)")
    df.add_argument("a", help="baseline JSON file")
    df.add_argument("b", help="changed JSON file")
    df.set_defaults(func=cmd_diff)

    ed = sub.add_parser("edit", help="change one or more fields on a slot")
    ed.add_argument("slot", type=int, choices=(1, 2, 3, 4))
    ed.add_argument("--channel", type=int)
    ed.add_argument("--octave", type=int)
    ed.add_argument("--transpose", type=int)
    ed.add_argument("--arp", choices=("on", "off"))
    ed.add_argument("--arp-mode", dest="arp_mode", choices=tuple(codec.ARP_MODES.values()))
    ed.add_argument("--time-div", dest="time_div", choices=tuple(codec.TIME_DIVISIONS.values()))
    ed.add_argument("--clock", choices=tuple(codec.CLOCK_SOURCES.values()))
    ed.add_argument("--latch", choices=("on", "off"))
    ed.add_argument("--tempo", type=int)
    ed.add_argument("--taps", type=int)
    ed.add_argument("--arp-octave", dest="arp_octave", type=int)
    ed.add_argument("--no-verify", action="store_true")
    ed.set_defaults(func=cmd_edit)

    sh = sub.add_parser("show", help="human-readable readout of the device state")
    sh.add_argument("slot", type=int, nargs="?", choices=(1, 2, 3, 4))
    sh.add_argument("--json", action="store_true", help="print dump JSON instead")
    sh.set_defaults(func=cmd_show)

    pr = sub.add_parser("preset", help="named single-program preset library")
    pr_sub = pr.add_subparsers(dest="preset_action", required=True)

    pr_save = pr_sub.add_parser("save", help="save a slot as a named preset")
    pr_save.add_argument("name")
    pr_save.add_argument("--from-slot", dest="from_slot", type=int,
                         choices=(1, 2, 3, 4), default=1)
    pr_save.add_argument("--force", action="store_true")
    pr_save.set_defaults(func=cmd_preset)

    pr_apply = pr_sub.add_parser("apply", help="write a named preset onto a slot")
    pr_apply.add_argument("name")
    pr_apply.add_argument("slot", type=int, choices=(1, 2, 3, 4))
    pr_apply.add_argument("--no-verify", action="store_true")
    pr_apply.set_defaults(func=cmd_preset)

    pr_list = pr_sub.add_parser("list", help="list saved presets")
    pr_list.set_defaults(func=cmd_preset)

    bk = sub.add_parser("bank", help="named full-device bank library (all 4 programs)")
    bk_sub = bk.add_subparsers(dest="bank_action", required=True)

    bk_save = bk_sub.add_parser("save", help="dump all 4 programs into a named bank")
    bk_save.add_argument("name")
    bk_save.add_argument("--force", action="store_true")
    bk_save.set_defaults(func=cmd_bank)

    bk_apply = bk_sub.add_parser("apply", help="write a named bank onto all 4 slots")
    bk_apply.add_argument("name")
    bk_apply.add_argument("-y", "--yes", action="store_true", help="skip the confirmation prompt")
    bk_apply.add_argument("--no-verify", action="store_true")
    bk_apply.set_defaults(func=cmd_bank)

    bk_list = bk_sub.add_parser("list", help="list saved banks")
    bk_list.set_defaults(func=cmd_bank)

    bk_show = bk_sub.add_parser("show", help="print a bank's 4-program table")
    bk_show.add_argument("name")
    bk_show.set_defaults(func=cmd_bank)

    bk_delete = bk_sub.add_parser("delete", help="delete a saved bank")
    bk_delete.add_argument("name")
    bk_delete.set_defaults(func=cmd_bank)

    cp = sub.add_parser("copy", help="copy a program from one slot onto others")
    cp.add_argument("src", type=int, choices=(1, 2, 3, 4))
    cp.add_argument("dst", type=int, nargs="+", choices=(1, 2, 3, 4))
    cp.add_argument("-y", "--yes", action="store_true", help="skip the confirmation prompt")
    cp.add_argument("--no-verify", action="store_true")
    cp.set_defaults(func=cmd_copy)

    s = sub.add_parser("set", help="write one program from a JSON file")
    s.add_argument("slot", type=int, choices=(1, 2, 3, 4))
    s.add_argument("file")
    s.add_argument("--no-verify", action="store_true")
    s.set_defaults(func=cmd_set)

    ld = sub.add_parser("load", help="write all programs from a preset JSON file")
    ld.add_argument("file")
    ld.add_argument("--no-verify", action="store_true")
    ld.set_defaults(func=cmd_load)

    def _add_dir(parser: argparse.ArgumentParser) -> None:
        parser.add_argument("-o", "--output", "--dir", dest="output", default=None,
                            help="backup directory (default: $LPK25_BACKUP_DIR)")

    b = sub.add_parser("backup", help="save / list / prune device backups")
    _add_dir(b)
    b.set_defaults(func=cmd_backup, backup_action=None)
    b_sub = b.add_subparsers(dest="backup_action")
    b_save = b_sub.add_parser("save", help="save a timestamped backup (default action)")
    _add_dir(b_save)
    b_save.set_defaults(func=cmd_backup, backup_action="save")
    b_list = b_sub.add_parser("list", help="list backups, newest first")
    _add_dir(b_list)
    b_list.set_defaults(func=cmd_backup, backup_action="list")
    b_prune = b_sub.add_parser("prune", help="delete old backups, keeping the newest N")
    _add_dir(b_prune)
    b_prune.add_argument("--keep", type=int, required=True, help="number of newest backups to keep")
    b_prune.add_argument("-y", "--yes", action="store_true", help="skip the confirmation prompt")
    b_prune.set_defaults(func=cmd_backup, backup_action="prune")

    rst = sub.add_parser("restore", help="restore programs from a backup file")
    rst.add_argument("file", nargs="?", help="backup file (omit with --latest)")
    rst.add_argument("--latest", action="store_true", help="restore the most recent backup")
    rst.add_argument("--no-verify", action="store_true")
    rst.set_defaults(func=cmd_restore)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        config.apply(args)
        return args.func(args)
    except Exception as exc:  # noqa: BLE001 - top-level user-facing handler
        _eprint(f"error: {exc}")
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
