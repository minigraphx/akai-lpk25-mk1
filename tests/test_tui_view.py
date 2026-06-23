"""Tests for the pure helper in tui/view.py (no curses)."""

from lpk25.device import Device
from lpk25.transport import MockTransport
from lpk25.tui import view
from lpk25.tui.controller import FIELD_ORDER, EditorController


def _ctl():
    dev = Device(MockTransport(model=0x76), model=0x76)
    return EditorController(dev, dev.dump(), dev.get_active_program())


def test_grid_cells_shape():
    """_grid_cells returns (cells, widths) with 5 rows (header + 4 data) and proper slots."""
    c = _ctl()
    cells, widths = view._grid_cells(c)

    # 5 rows total: 1 header + 4 data rows
    assert len(cells) == 5
    assert cells[0][0] == "slot"  # header

    # Data rows have slot labels 1, 2, 3, 4
    assert cells[1][0] == "1"
    assert cells[2][0] == "2"
    assert cells[3][0] == "3"
    assert cells[4][0] == "4"

    # Each row has header columns (slot + FIELD_ORDER fields)
    expected_cols = 1 + len(FIELD_ORDER)
    for row in cells:
        assert len(row) == expected_cols

    # Widths should match the number of columns
    assert len(widths) == expected_cols


def test_grid_cells_dirty_marker():
    """Dirty slot shows '*' after the slot number."""
    c = _ctl()
    c.slot_idx = 0
    c.field_idx = 0
    c.step(1)  # Make a change to slot 1
    cells, _ = view._grid_cells(c)

    # Slot 1 should have dirty marker
    assert cells[1][0] == "1*"
    # Other slots should not
    assert cells[2][0] == "2"
    assert cells[3][0] == "3"
    assert cells[4][0] == "4"


def test_grid_cells_column_widths():
    """Column widths are computed correctly (max of each column)."""
    c = _ctl()
    cells, widths = view._grid_cells(c)

    # Each width should equal the max length in that column
    for col_idx in range(len(widths)):
        expected_width = max(len(row[col_idx]) for row in cells)
        assert widths[col_idx] == expected_width
