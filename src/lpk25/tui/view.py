"""curses drawing + input overlays for the TUI. Thin: no edit logic here."""

from __future__ import annotations

import curses

from .. import render
from .controller import FIELD_ORDER

_HEADERS = ["slot"] + [h for name, h in render._COLUMNS if name != "slot"]
_KEYS_1 = "up/dn slot   l/r field   -/+ change   ⏎ type   w write   a activate"
_KEYS_2 = "s/l preset   b/B bank   r reload   m monitor   ? help   q quit"

# Field names in the same order as FIELD_ORDER (matches _HEADERS[1:])
_FIELD_NAMES = [f.name for f in FIELD_ORDER]


def _fmt_value(name: str, value: object) -> str:
    return render._disp(name, value)


def _grid_cells(controller) -> tuple[list[list[str]], list[int]]:
    """Return (cells_per_row, column_widths).

    cells_per_row[0] is the header row; cells_per_row[1..] are the 4 data rows.
    Column 0 is the slot label; columns 1.. correspond to FIELD_ORDER fields.
    """
    rows = controller.rows()
    cells = [_HEADERS[:]]
    for r in rows:
        line = [str(r.slot) + ("*" if r.dirty else "")]
        line += [_fmt_value(n, r.values.get(n)) for n in _FIELD_NAMES]
        cells.append(line)
    widths = [max(len(row[i]) for row in cells) for i in range(len(_HEADERS))]
    return cells, widths


def draw(stdscr, controller, monitor, ui, mock: bool, message: str) -> None:
    stdscr.erase()
    maxy, maxx = stdscr.getmaxyx()
    tag = "  [MOCK]" if mock else ""
    stdscr.addnstr(0, 0, f"lpk25 tui — {controller.header()}{tag}", maxx - 1, curses.A_BOLD)

    cells, widths = _grid_cells(controller)
    rows_obj = controller.rows()

    # --- header row (i=0) ---
    y = 2
    if y < maxy - 4:
        prefix = "  "
        x = 0
        x = _write_str(stdscr, y, x, maxx, prefix, curses.A_NORMAL)
        for col_idx, cell in enumerate(cells[0]):
            cell_str = cell.rjust(widths[col_idx])
            if col_idx > 0:
                x = _write_str(stdscr, y, x, maxx, "  ", curses.A_NORMAL)
            if x >= maxx - 1:
                break
            x = _write_str(stdscr, y, x, maxx, cell_str, curses.A_NORMAL)

    # --- data rows (i = 1..len(rows_obj)) ---
    for ri, r in enumerate(rows_obj):
        y = 3 + ri  # row 3,4,5,6 for data (header at 2)
        if y >= maxy - 4:
            break
        prefix = "▶ " if r.active else "  "
        x = 0
        x = _write_str(stdscr, y, x, maxx, prefix, curses.A_NORMAL)
        row_cells = cells[ri + 1]
        for col_idx, cell in enumerate(row_cells):
            cell_str = cell.rjust(widths[col_idx])
            if col_idx > 0:
                x = _write_str(stdscr, y, x, maxx, "  ", curses.A_NORMAL)
            if x >= maxx - 1:
                break
            # Highlight only the single focused cell
            if ri == controller.slot_idx and col_idx - 1 == controller.field_idx:
                attr = curses.A_REVERSE
            else:
                attr = curses.A_NORMAL
            x = _write_str(stdscr, y, x, maxx, cell_str, attr)

    num_grid_rows = 1 + len(rows_obj)  # header + data rows
    legend_y = 2 + num_grid_rows + 1
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


def _write_str(stdscr, y: int, x: int, maxx: int, text: str, attr: int) -> int:
    """Write text at (y, x) clamped to maxx-1, return new x offset."""
    if x >= maxx - 1:
        return x
    width = max(0, maxx - 1 - x)
    if width == 0:
        return x
    stdscr.addnstr(y, x, text, width, attr)
    return x + len(text)


def _read_line(stdscr, label: str) -> str | None:
    maxy, maxx = stdscr.getmaxyx()
    curses.echo()
    curses.curs_set(1)
    stdscr.addnstr(maxy - 1, 0, " " * (maxx - 1), maxx - 1)
    stdscr.addnstr(maxy - 1, 0, label, maxx - 1)
    try:
        raw = stdscr.getstr(maxy - 1, min(len(label), maxx - 1), 64)
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
        if 2 + i >= maxy - 1:
            break
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
