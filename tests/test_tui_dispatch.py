import curses

from lpk25.device import Device
from lpk25.transport import MockTransport
from lpk25.tui.app import UIState, dispatch
from lpk25.tui.controller import FIELD_ORDER, EditorController


def make():
    dev = Device(MockTransport(model=0x76), model=0x76)
    return EditorController(dev, dev.dump(), dev.get_active_program())


class FakeIO:
    """Scripted prompt/choose/confirm for dispatch tests."""
    def __init__(self, prompt=None, choose=None, confirm=True):
        self._prompt, self._choose, self._confirm = prompt, choose, confirm
        self.calls = []

    def prompt(self, label):
        self.calls.append(("prompt", label))
        return self._prompt

    def choose(self, title, options):
        self.calls.append(("choose", title, tuple(options)))
        return self._choose

    def confirm(self, msg):
        self.calls.append(("confirm", msg))
        return self._confirm


def test_arrows_move_cursor():
    c = make()
    ui = UIState()
    dispatch(curses.KEY_DOWN, c, ui, FakeIO())
    dispatch(curses.KEY_RIGHT, c, ui, FakeIO())
    assert (c.slot_idx, c.field_idx) == (1, 1)


def test_minus_plus_step_value():
    c = make()
    c.field_idx = [f.name for f in FIELD_ORDER].index("keybed_octave")
    dispatch(ord("+"), c, make_ui := UIState(), FakeIO())
    assert c.rows()[0].values["keybed_octave"] == 1
    dispatch(ord("-"), c, make_ui, FakeIO())
    assert c.rows()[0].values["keybed_octave"] == 0


def test_w_writes_current_slot():
    c = make()
    c.field_idx = [f.name for f in FIELD_ORDER].index("keybed_octave")
    dispatch(ord("+"), c, UIState(), FakeIO())
    msg = dispatch(ord("w"), c, UIState(), FakeIO())
    assert "slot 1" in msg
    assert c.any_dirty() is False


def test_a_activates_current_slot():
    c = make()
    dispatch(curses.KEY_DOWN, c, UIState(), FakeIO())     # slot 2
    msg = dispatch(ord("a"), c, UIState(), FakeIO())
    assert "2" in msg
    assert c.active_slot == 2


def test_enter_type_in_sets_value():
    c = make()
    c.field_idx = [f.name for f in FIELD_ORDER].index("tempo")
    io = FakeIO(prompt="140")
    dispatch(ord("\n"), c, UIState(), io)
    assert c.rows()[0].values["tempo"] == 140


def test_enter_type_in_invalid_reports_message():
    c = make()
    c.field_idx = [f.name for f in FIELD_ORDER].index("tempo")
    msg = dispatch(ord("\n"), c, UIState(), FakeIO(prompt="999"))
    assert "invalid" in msg.lower()


def test_m_toggles_monitor_and_q_quits_when_clean():
    c = make()
    ui = UIState()
    dispatch(ord("m"), c, ui, FakeIO())
    assert ui.show_monitor is True
    dispatch(ord("q"), c, ui, FakeIO())
    assert ui.running is False


def test_q_with_unsaved_edits_confirms():
    c = make()
    c.field_idx = [f.name for f in FIELD_ORDER].index("keybed_octave")
    dispatch(ord("+"), c, UIState(), FakeIO())
    ui = UIState()
    dispatch(ord("q"), c, ui, FakeIO(confirm=False))     # declines
    assert ui.running is True
    dispatch(ord("q"), c, ui, FakeIO(confirm=True))      # accepts
    assert ui.running is False


def test_l_loads_chosen_preset(tmp_path, monkeypatch):
    monkeypatch.setenv("LPK25_PRESET_DIR", str(tmp_path))
    c = make()
    c.field_idx = [f.name for f in FIELD_ORDER].index("keybed_octave")
    dispatch(ord("+"), c, UIState(), FakeIO())
    c.save_preset("p1")
    dispatch(curses.KEY_DOWN, c, UIState(), FakeIO())    # slot 2
    dispatch(ord("l"), c, UIState(), FakeIO(choose="p1"))
    assert c.rows()[1].values["keybed_octave"] == 1


def test_s_saves_preset(tmp_path, monkeypatch):
    monkeypatch.setenv("LPK25_PRESET_DIR", str(tmp_path))
    from lpk25 import library
    c = make()
    msg = dispatch(ord("s"), c, UIState(), FakeIO(prompt="p1"))
    assert "saved" in msg and "p1" in msg
    assert "p1" in library.list_preset_names()


def test_s_overwrite_confirm_forces_then_cancels(tmp_path, monkeypatch):
    monkeypatch.setenv("LPK25_PRESET_DIR", str(tmp_path))
    c = make()
    dispatch(ord("s"), c, UIState(), FakeIO(prompt="dup"))            # first save
    msg = dispatch(ord("s"), c, UIState(), FakeIO(prompt="dup", confirm=True))  # overwrite
    assert "saved" in msg
    msg2 = dispatch(ord("s"), c, UIState(), FakeIO(prompt="dup", confirm=False))  # decline
    assert msg2 == "cancelled"


def test_bank_save_and_load_via_dispatch(tmp_path, monkeypatch):
    monkeypatch.setenv("LPK25_BANK_DIR", str(tmp_path))
    c = make()
    c.field_idx = [f.name for f in FIELD_ORDER].index("tempo")
    dispatch(ord("\n"), c, UIState(), FakeIO(prompt="150"))           # set tempo 150
    dispatch(ord("b"), c, UIState(), FakeIO(prompt="bankA"))          # save bank
    c.reload()                                                        # discard edits
    dispatch(ord("B"), c, UIState(), FakeIO(choose="bankA"))          # load bank
    assert c.rows()[0].values["tempo"] == 150
