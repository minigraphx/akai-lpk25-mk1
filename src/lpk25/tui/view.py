"""curses drawing + input overlays for the TUI. Thin: no edit logic here."""

from __future__ import annotations

import curses

from .. import render
from .controller import FIELD_ORDER

_HEADERS = ["slot"] + [h for name, h in render._COLUMNS if name != "slot"]
_KEYS_1 = "up/dn slot   l/r field   -/+ change   ⏎ type   w write   a activate"
_KEYS_2 = "s/l preset   b/B bank   r reload   m monitor   ? help   q quit"


def _fmt_value(name: str, value: object) -> str:
    return render._disp(name, value)


def _grid_lines(controller) -> list[tuple[str, bool]]:
    """Return (text, is_active) per row; the focused cell is wrapped in [..]."""
    rows = controller.rows()
    field_names = [f.name for f in FIELD_ORDER]
    cells = [_HEADERS]
    for r in rows:
        line = [str(r.slot) + ("*" if r.dirty else "")]
        line += [_fmt_value(n, r.values.get(n)) for n in field_names]
        cells.append(line)
    widths = [max(len(row[i]) for row in cells) for i in range(len(_HEADERS))]

    def render_row(cols, prefix):
        return prefix + "  ".join(c.rjust(widths[i]) for i, c in enumerate(cols))

    out = [(render_row(cells[0], "  "), False)]
    for ri, r in enumerate(rows):
        prefix = "▶ " if r.active else "  "
        out.append((render_row(cells[ri + 1], prefix), r.active))
    return out


def draw(stdscr, controller, monitor, ui, mock: bool, message: str) -> None:
    stdscr.erase()
    maxy, maxx = stdscr.getmaxyx()
    tag = "  [MOCK]" if mock else ""
    stdscr.addnstr(0, 0, f"lpk25 tui — {controller.header()}{tag}", maxx - 1, curses.A_BOLD)

    grid = _grid_lines(controller)
    for i, (line, _active) in enumerate(grid):
        y = 2 + i
        if y >= maxy - 4:
            break
        attr = curses.A_REVERSE if (i - 1) == controller.slot_idx else curses.A_NORMAL
        stdscr.addnstr(y, 0, line, maxx - 1, attr)

    legend_y = 2 + len(grid) + 1
    if legend_y < maxy - 1:
        stdscr.addnstr(legend_y, 0, _KEYS_1, maxx - 1, curses.A_DIM)
    if legend_y + 1 < maxy - 1:
        stdscr.addnstr(legend_y + 1, 0, _KEYS_2, maxx - 1, curses.A_DIM)

    if ui.show_monitor:
        my = legend_y + 3
        if my < maxy - 1:
            stdscr.addnstr(my, 0, "── monitor (m) " + "─" * max(0, maxx - 16), maxx - 1)
            if monitor.available and not mock:
                for j, mln in enumerate(monitor.lines(maxy - my - 2)):
                    if my + 1 + j < maxy - 1:
                        stdscr.addnstr(my + 1 + j, 0, mln, maxx - 1)
            elif my + 1 < maxy - 1:
                stdscr.addnstr(my + 1, 0, "no MIDI input (offline)", maxx - 1, curses.A_DIM)

    stdscr.addnstr(maxy - 1, 0, (message or "")[: maxx - 1], maxx - 1, curses.A_REVERSE)
    stdscr.refresh()


def _read_line(stdscr, label: str) -> str | None:
    maxy, maxx = stdscr.getmaxyx()
    curses.echo()
    curses.curs_set(1)
    stdscr.addnstr(maxy - 1, 0, " " * (maxx - 1), maxx - 1)
    stdscr.addnstr(maxy - 1, 0, label, maxx - 1)
    try:
        raw = stdscr.getstr(maxy - 1, len(label), 64)
    finally:
        curses.noecho()
        curses.curs_set(0)
    if raw is None:
        return None
    text = raw.decode("utf-8", "replace").strip()
    return text or None


def prompt(stdscr, label: str) -> str | None:
    return _read_line(stdscr, label)


def choose(stdscr, title: str, options: list[str]) -> str | None:
    # Minimal picker: list options with indices, read a number.
    maxy, maxx = stdscr.getmaxyx()
    stdscr.erase()
    stdscr.addnstr(0, 0, title, maxx - 1, curses.A_BOLD)
    for i, opt in enumerate(options):
        stdscr.addnstr(2 + i, 0, f"{i + 1}. {opt}", maxx - 1)
    stdscr.refresh()
    text = _read_line(stdscr, "pick number (Enter to cancel): ")
    if not text or not text.isdigit():
        return None
    idx = int(text) - 1
    return options[idx] if 0 <= idx < len(options) else None


def confirm(stdscr, msg: str) -> bool:
    text = _read_line(stdscr, f"{msg} [y/N]: ")
    return bool(text) and text.lower().startswith("y")
