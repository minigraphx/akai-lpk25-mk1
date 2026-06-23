import pytest

from lpk25 import codec
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


def _focus(c, field_name):
    c.field_idx = [f.name for f in FIELD_ORDER].index(field_name)


def test_step_int_clamps_within_bounds():
    c = make_controller()
    _focus(c, "keybed_octave")                 # lo=-4, hi=4, starts 0
    for _ in range(10):
        c.step(1)
    assert c.rows()[0].values["keybed_octave"] == 4
    for _ in range(20):
        c.step(-1)
    assert c.rows()[0].values["keybed_octave"] == -4


def test_step_enum_cycles():
    c = make_controller()
    _focus(c, "arp_mode")                       # up,down,inclusive,exclusive,order,random
    assert c.rows()[0].values["arp_mode"] == "up"
    c.step(1)
    assert c.rows()[0].values["arp_mode"] == "down"
    c.step(-1)
    assert c.rows()[0].values["arp_mode"] == "up"
    c.step(-1)                                  # wraps to last
    assert c.rows()[0].values["arp_mode"] == "random"


def test_step_bool_toggles_and_marks_dirty():
    c = make_controller()
    _focus(c, "arp_enabled")
    before = c.rows()[0].values["arp_enabled"]
    c.step(1)
    assert c.rows()[0].values["arp_enabled"] is (not before)
    assert c.rows()[0].dirty is True
    assert c.any_dirty() is True


def test_step_tempo_u14_clamps():
    c = make_controller()
    _focus(c, "tempo")                          # lo=30, hi=240
    for _ in range(500):
        c.step(1)
    assert c.rows()[0].values["tempo"] == 240


def test_set_value_numeric_and_validation():
    c = make_controller()
    _focus(c, "tempo")
    c.set_value("140")
    assert c.rows()[0].values["tempo"] == 140
    with pytest.raises(codec.CodecError):
        c.set_value("999")                      # out of range
    with pytest.raises(codec.CodecError):
        c.set_value("abc")                      # not a number
    _focus(c, "arp_mode")
    with pytest.raises(codec.CodecError):
        c.set_value("2")                        # enum is not type-in editable


def test_undo_slot_reverts():
    c = make_controller()
    _focus(c, "keybed_octave")
    c.step(1)
    assert c.rows()[0].dirty is True
    c.undo_slot()
    assert c.rows()[0].dirty is False
    assert c.rows()[0].values["keybed_octave"] == 0
