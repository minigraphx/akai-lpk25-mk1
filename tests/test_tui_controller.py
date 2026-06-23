from lpk25.device import Device
from lpk25.transport import MockTransport
from lpk25.tui.controller import FIELD_ORDER, EditorController, RowView


def make_controller() -> EditorController:
    dev = Device(MockTransport(model=0x76), model=0x76)
    return EditorController(dev, dev.dump(), dev.get_active_program())


def test_rows_describe_four_programs():
    c = make_controller()
    rows = c.rows()
    assert [r.slot for r in rows] == [1, 2, 3, 4]
    assert all(isinstance(r, RowView) for r in rows)
    assert all(r.dirty is False for r in rows)        # nothing edited yet
    assert [r.active for r in rows] == [True, False, False, False]  # mock active = 1
    assert rows[0].values["midi_channel"] == 1        # decoded display value


def test_field_order_is_render_columns_without_slot():
    names = [f.name for f in FIELD_ORDER]
    assert "midi_channel" in names
    assert "slot" not in names
    assert len(names) == 11                            # all mapped editable fields


def test_move_clamps_to_grid():
    c = make_controller()
    c.move(-1, -1)                                     # already top-left
    assert (c.slot_idx, c.field_idx) == (0, 0)
    c.move(99, 99)                                     # past bottom-right
    assert c.slot_idx == 3
    assert c.field_idx == len(FIELD_ORDER) - 1


def test_header_names_focused_field_and_slot():
    c = make_controller()
    assert c.header().startswith("slot 1 · ")
