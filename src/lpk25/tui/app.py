"""Key dispatch, UI state, and the curses main loop for `lpk25 tui`.

`dispatch` is pure (no curses I/O): it maps a key code to controller/ui changes
through an injected `io` object, so every key path is unit-tested. The curses
loop (`run`/`_loop`, added alongside) only draws and reads keys."""

from __future__ import annotations

import curses
from dataclasses import dataclass

from .. import library


@dataclass
class UIState:
    show_monitor: bool = False
    show_help: bool = False
    running: bool = True


def _save(controller, io, kind: str) -> str | None:
    saver = controller.save_preset if kind == "preset" else controller.save_bank
    name = io.prompt(f"save {kind} name: ")
    if not name:
        return None
    try:
        saver(name)
        return f"saved {kind} {name}"
    except library.LibraryError:
        if io.confirm(f"{kind} {name!r} exists — overwrite?"):
            try:
                saver(name, force=True)
                return f"saved {kind} {name}"
            except Exception as exc:  # noqa: BLE001 - surfaced to status line
                return f"save failed: {exc}"
    return "cancelled"


def _load(controller, io, kind: str) -> str | None:
    names = (library.list_preset_names if kind == "preset" else library.list_bank_names)()
    if not names:
        return f"no {kind}s saved"
    choice = io.choose(f"load {kind}", names)
    if not choice:
        return None
    try:
        if kind == "preset":
            controller.load_preset_into_current(choice)
        else:
            controller.load_bank(choice)
        return f"loaded {kind} {choice}"
    except Exception as exc:                      # noqa: BLE001 - surfaced to status line
        return f"load failed: {exc}"


def dispatch(key: int, controller, ui: UIState, io) -> str | None:
    if key in (curses.KEY_UP, ord("k")):
        controller.move(-1, 0)
    elif key in (curses.KEY_DOWN, ord("j")):
        controller.move(1, 0)
    elif key in (curses.KEY_LEFT, ord("h")):
        controller.move(0, -1)
    elif key == curses.KEY_RIGHT:
        controller.move(0, 1)
    elif key in (ord("-"), ord("_")):
        controller.step(-1)
    elif key in (ord("+"), ord("=")):
        controller.step(1)
    elif key == ord("["):
        controller.step(-10)
    elif key == ord("]"):
        controller.step(10)
    elif key == ord("u"):
        controller.undo_slot()
        return "reverted slot"
    elif key == ord("\n"):
        text = io.prompt(f"{controller.focused_field().name} = ")
        if text:
            try:
                controller.set_value(text)
                return "set"
            except Exception as exc:              # noqa: BLE001
                return f"invalid: {exc}"
    elif key == ord("w"):
        try:
            r = controller.write_current()
            return f"wrote slot {r.slot}" + (" ✓" if r.verified else "")
        except Exception as exc:                  # noqa: BLE001
            return f"write failed: {exc}"
    elif key == ord("W"):
        try:
            rs = controller.write_all_dirty()
            return f"wrote {len(rs)} slot(s)"
        except Exception as exc:                  # noqa: BLE001
            return f"write failed: {exc}"
    elif key == ord("a"):
        try:
            return f"activated slot {controller.activate_current()}"
        except Exception as exc:                  # noqa: BLE001
            return f"activate failed: {exc}"
    elif key == ord("r"):
        if io.confirm("reload from device — discard edits?"):
            controller.reload()
            return "reloaded"
    elif key == ord("s"):
        return _save(controller, io, "preset")
    elif key == ord("l"):
        return _load(controller, io, "preset")
    elif key == ord("b"):
        return _save(controller, io, "bank")
    elif key == ord("B"):
        return _load(controller, io, "bank")
    elif key == ord("m"):
        ui.show_monitor = not ui.show_monitor
        return "monitor on" if ui.show_monitor else "monitor off"
    elif key == ord("?"):
        ui.show_help = not ui.show_help
    elif key == ord("q"):
        if not controller.any_dirty() or io.confirm("unsaved edits — quit anyway?"):
            ui.running = False
    return None


from .controller import EditorController          # noqa: E402,I001
from .monitor import MidiMonitor                  # noqa: E402
from . import view as _view                       # noqa: E402


class _CursesIO:
    def __init__(self, stdscr):
        self._stdscr = stdscr

    def prompt(self, label):
        return _view.prompt(self._stdscr, label)

    def choose(self, title, options):
        return _view.choose(self._stdscr, title, list(options))

    def confirm(self, msg):
        return _view.confirm(self._stdscr, msg)


def _loop(stdscr, controller, monitor, mock):
    curses.curs_set(0)
    stdscr.keypad(True)
    ui = UIState()
    io = _CursesIO(stdscr)
    message = "ready"
    while ui.running:
        _view.draw(stdscr, controller, monitor, ui, mock, message)
        key = stdscr.getch()
        message = dispatch(key, controller, ui, io) or message


def run(transport, mock: bool) -> int:
    from ..device import Device

    dev = Device(transport)
    controller = EditorController(dev, dev.dump(), dev.get_active_program())
    monitor = MidiMonitor(transport)
    if not mock:
        monitor.start()
    try:
        curses.wrapper(_loop, controller, monitor, mock)
    finally:
        monitor.stop()
    return 0
