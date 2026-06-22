"""Command-line interface for the LPK25 mk1 editor.

Hardware commands need the MIDI extra (``pip install 'lpk25[midi]'``). Pure
discovery/formatting still works without it via ``--mock``.
"""

from __future__ import annotations

import argparse
import sys

from . import __version__, codec, protocol
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
        else:
            print("No Device Inquiry reply (the mk1 may not implement it).")

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
    with _make_transport(args) as tr:
        mon = getattr(tr, "monitor", None)
        if mon is None:
            _eprint("This transport does not support monitoring.")
            return 2
        print(f"Monitoring MIDI input for {args.seconds}s. Play the keyboard... (Ctrl-C to stop)")

        def show(frame: bytes) -> None:
            print(" ".join(f"{b:02X}" for b in frame))

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
    result = dev.send_program(program, verify=not args.no_verify)
    print(f"Wrote program {result.slot}; verified={result.verified}; backup={result.backup_path}")
    return 0


def cmd_load(args: argparse.Namespace) -> int:
    preset = Preset.load(args.file)
    dev = _make_device(args)
    results = dev.load(preset, verify=not args.no_verify)
    for r in results:
        print(f"  slot {r.slot}: verified={r.verified}")
    if results:
        print(f"backup: {results[0].backup_path}")
    return 0


def cmd_backup(args: argparse.Namespace) -> int:
    dev = _make_device(args)
    path = dev.backup(args.output or "backups")
    print(f"Backup written to {path}")
    return 0


def cmd_restore(args: argparse.Namespace) -> int:
    dev = _make_device(args)
    results = dev.restore(args.file, verify=not args.no_verify)
    for r in results:
        print(f"  slot {r.slot}: verified={r.verified}")
    return 0


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
    p.add_argument("--port", default="LPK25", help="substring to match the MIDI port name")
    p.add_argument("--in-port", default=None, help="exact MIDI input port name")
    p.add_argument("--out-port", default=None, help="exact MIDI output port name")
    p.add_argument(
        "--model", type=lambda s: int(s, 0), default=None,
        help="device model byte (e.g. 0x76); overrides the default guess",
    )
    p.add_argument("--mock", action="store_true", help="use the in-memory fake device")

    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("ports", help="list MIDI ports").set_defaults(func=cmd_ports)
    sub.add_parser("identify", help="device inquiry + model probe").set_defaults(func=cmd_identify)

    mon = sub.add_parser("monitor", help="print the keyboard's live MIDI output")
    mon.add_argument("--seconds", type=float, default=30.0)
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

    s = sub.add_parser("set", help="write one program from a JSON file")
    s.add_argument("slot", type=int, choices=(1, 2, 3, 4))
    s.add_argument("file")
    s.add_argument("--no-verify", action="store_true")
    s.set_defaults(func=cmd_set)

    ld = sub.add_parser("load", help="write all programs from a preset JSON file")
    ld.add_argument("file")
    ld.add_argument("--no-verify", action="store_true")
    ld.set_defaults(func=cmd_load)

    b = sub.add_parser("backup", help="back up all programs to a timestamped file")
    b.add_argument("-o", "--output", default=None, help="output directory")
    b.set_defaults(func=cmd_backup)

    rst = sub.add_parser("restore", help="restore programs from a backup file")
    rst.add_argument("file")
    rst.add_argument("--no-verify", action="store_true")
    rst.set_defaults(func=cmd_restore)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except Exception as exc:  # noqa: BLE001 - top-level user-facing handler
        _eprint(f"error: {exc}")
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
