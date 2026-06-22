"""High-level device operations, with the safety model baked in.

Every write auto-backs-up first and verifies by reading the slot back. Reads are
always safe. A future GUI sits directly on top of this class.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from . import protocol
from .model import Preset, Program
from .transport import Transport

SLOTS = (1, 2, 3, 4)

# Conservative rate limits to protect the device flash (from the family docs).
MIN_DELAY_BETWEEN_FRAMES = 0.08
MIN_DELAY_BETWEEN_BATCHES = 0.3


class DeviceError(RuntimeError):
    pass


class VerificationError(DeviceError):
    """Raised when a written program does not read back identically."""


@dataclass
class WriteResult:
    slot: int
    verified: bool
    backup_path: str | None


class Device:
    def __init__(self, transport: Transport, model: int | None = None):
        self.transport = transport
        self.config = protocol.ProtocolConfig()
        if model is not None:
            self.config.model = model

    # --- read path --------------------------------------------------------

    def get_active_program(self, timeout: float = 1.0) -> int | None:
        reply = self.transport.request(
            protocol.build_get_active_program(self.config), timeout=timeout
        )
        if reply is None:
            return None
        f = protocol.parse_frame(reply)
        return f.slot

    def get_program_payload(self, slot: int, timeout: float = 1.0) -> bytes:
        reply = self.transport.request(
            protocol.build_get_program(slot, self.config), timeout=timeout
        )
        if reply is None:
            raise DeviceError(f"no reply when reading program {slot}")
        f = protocol.parse_frame(reply)
        if f.opcode != protocol.OP_GET_PROGRAM:
            raise DeviceError(f"unexpected opcode 0x{f.opcode:02X} reading program {slot}")
        return f.data

    def get_program(self, slot: int, timeout: float = 1.0) -> Program:
        return Program.from_payload(slot, self.get_program_payload(slot, timeout))

    def dump(self, timeout: float = 1.0) -> Preset:
        programs: list[Program] = []
        for slot in SLOTS:
            programs.append(self.get_program(slot, timeout))
            time.sleep(MIN_DELAY_BETWEEN_FRAMES)
        return Preset(programs=programs, device_model=self.config.model)

    # --- write path (guarded) --------------------------------------------

    def _send_program_payload(self, slot: int, payload: bytes) -> None:
        frame = protocol.build_send_program(slot, payload[1:], self.config)
        # payload[0] is the slot echo; build_send_program re-adds the slot byte.
        self.transport.send(frame)
        time.sleep(MIN_DELAY_BETWEEN_FRAMES)

    def send_program(
        self,
        program: Program,
        verify: bool = True,
        backup_dir: str | None = "backups",
    ) -> WriteResult:
        """Write one program. Auto-backs-up all slots first, then verifies."""
        backup_path = None
        if backup_dir is not None:
            backup_path = self.backup(backup_dir)

        payload = program.to_payload()
        self._send_program_payload(program.slot, payload)

        verified = True
        if verify:
            time.sleep(MIN_DELAY_BETWEEN_FRAMES)
            read_back = self.get_program_payload(program.slot)
            verified = read_back == payload
            if not verified:
                raise VerificationError(
                    f"slot {program.slot}: read-back differs from what was sent\n"
                    f"  sent: {payload.hex()}\n  got:  {read_back.hex()}"
                )
        return WriteResult(slot=program.slot, verified=verified, backup_path=backup_path)

    def load(
        self, preset: Preset, verify: bool = True, backup_dir: str | None = "backups"
    ) -> list[WriteResult]:
        backup_path = self.backup(backup_dir) if backup_dir is not None else None
        results: list[WriteResult] = []
        for i, program in enumerate(preset.programs):
            # only back up once, before the first write
            results.append(
                self.send_program(program, verify=verify, backup_dir=None)
            )
            if i < len(preset.programs) - 1:
                time.sleep(MIN_DELAY_BETWEEN_BATCHES)
        for r in results:
            r.backup_path = backup_path
        return results

    # --- safety net -------------------------------------------------------

    def backup(self, backup_dir: str = "backups") -> str:
        os.makedirs(backup_dir, exist_ok=True)
        preset = self.dump()
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = os.path.join(backup_dir, f"lpk25-backup-{stamp}.json")
        preset.save(path)
        return path

    def restore(self, path: str, verify: bool = True) -> list[WriteResult]:
        preset = Preset.load(path)
        return self.load(preset, verify=verify, backup_dir="backups")

    # --- behavioural oracle ----------------------------------------------

    def monitor(self, callback: Callable[[bytes], None], duration: float | None = None) -> None:
        mon = getattr(self.transport, "monitor", None)
        if mon is None:
            raise DeviceError("this transport does not support monitoring")
        mon(callback, duration)
