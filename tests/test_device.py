import os

import pytest

from lpk25 import protocol
from lpk25.device import Device, DeviceError, VerificationError
from lpk25.model import Preset, Program
from lpk25.transport import MockTransport


def make_device() -> Device:
    return Device(MockTransport(model=0x76), model=0x76)


def test_dump_returns_four_programs():
    preset = make_device().dump()
    assert len(preset.programs) == 4
    assert [p.slot for p in preset.programs] == [1, 2, 3, 4]
    assert preset.device_model == 0x76


def test_get_active_program():
    assert make_device().get_active_program() == 1


def test_activate_changes_active_slot():
    dev = make_device()
    assert dev.activate(3) == 3
    assert dev.get_active_program() == 3


def test_activate_rejects_out_of_range_slot():
    with pytest.raises(DeviceError):
        make_device().activate(9)


def test_activate_no_verify_returns_none_but_still_switches():
    tr = MockTransport(model=0x76)
    dev = Device(tr, model=0x76)
    assert dev.activate(2, verify=False) is None
    assert tr.active == 2


def test_activate_raises_when_device_reports_other_slot():
    # A transport that swallows the activate frame so 'active' never moves.
    class _DropActivate(MockTransport):
        def send(self, frame: bytes) -> None:
            f = protocol.parse_frame(frame)
            if f.opcode == protocol.OP_ACTIVATE_PROGRAM:
                self.sent.append(bytes(frame))
                return
            super().send(frame)

    dev = Device(_DropActivate(model=0x76), model=0x76)
    with pytest.raises(VerificationError):
        dev.activate(4)


def test_round_trip_integrity():
    dev = make_device()
    original = dev.get_program(2)
    result = dev.send_program(original, verify=True, backup_dir=None)
    assert result.verified
    again = dev.get_program(2)
    assert again.raw == original.raw


def test_edit_then_write_changes_only_that_field():
    dev = make_device()
    prog = dev.get_program(1)
    prog.values["midi_channel"] = 10
    dev.send_program(prog, verify=True, backup_dir=None)
    read_back = dev.get_program(1)
    assert read_back.values["midi_channel"] == 10


def test_backup_and_restore(tmp_path):
    dev = make_device()
    backup_dir = str(tmp_path / "backups")
    path = dev.backup(backup_dir)
    assert os.path.exists(path)

    # mutate the device, then restore
    dev.transport.programs[1] = bytes([1, 5, 4, 12, 0, 0, 0, 0, 0, 2, 120, 0])
    dev.restore(path, verify=True)
    restored = dev.get_program(1)
    loaded = Preset.load(path)
    assert restored.raw == loaded.programs[0].raw


def test_preset_json_round_trip():
    preset = make_device().dump()
    restored = Preset.from_json(preset.to_json())
    assert [p.raw for p in restored.programs] == [p.raw for p in preset.programs]


def test_program_to_payload_is_byte_exact_when_unedited():
    raw = bytes([2, 3, 4, 12, 1, 1, 5, 7, 1, 4, 120, 3])
    prog = Program.from_payload(2, raw)
    assert prog.to_payload() == raw
