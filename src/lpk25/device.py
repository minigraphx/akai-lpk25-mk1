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

from . import library, protocol
from .model import Preset, Program
from .transport import Transport

SLOTS = (1, 2, 3, 4)

# Sentinel for "use the device's configured backup directory" (distinct from
# None, which means "skip the backup entirely").
_DEFAULT_BACKUP_DIR = object()

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
        # Default location for auto-backups and `backup` (overridable per call).
        self.backup_dir = library.backup_dir()

    def _resolve_backup_dir(self, backup_dir: object) -> str | None:
        return self.backup_dir if backup_dir is _DEFAULT_BACKUP_DIR else backup_dir  # type: ignore[return-value]

    # --- read path --------------------------------------------------------

    def get_active_program(self, timeout: float = 1.0) -> int | None:
        reply = self.transport.request(
            protocol.build_get_active_program(self.config), timeout=timeout
        )
        if reply is None:
            return None
        f = protocol.parse_frame(reply)
        return f.slot

    def activate(self, slot: int, verify: bool = True, timeout: float = 1.0) -> int | None:
        """Recall a stored program on the device (the hardware PROGRAM + PROG 1-4).

        This selects which program is active; it does not alter program memory,
        so no backup is taken. With ``verify``, the active program is read back
        to confirm the switch took effect. Returns the confirmed active slot, or
        None if the device didn't reply (or ``verify`` is off)."""
        if slot not in SLOTS:
            raise DeviceError(f"slot must be one of {SLOTS}, got {slot}")
        self.transport.send(protocol.build_activate_program(slot, self.config))
        time.sleep(MIN_DELAY_BETWEEN_FRAMES)
        if not verify:
            return None
        active = self.get_active_program(timeout=timeout)
        if active is not None and active != slot:
            raise VerificationError(
                f"activate slot {slot} not confirmed: device reports active slot {active}"
            )
        return active

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
        backup_dir: object = _DEFAULT_BACKUP_DIR,
    ) -> WriteResult:
        """Write one program. Auto-backs-up all slots first, then verifies."""
        target = self._resolve_backup_dir(backup_dir)
        backup_path = self.backup(target) if target is not None else None

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
        self, preset: Preset, verify: bool = True, backup_dir: object = _DEFAULT_BACKUP_DIR
    ) -> list[WriteResult]:
        target = self._resolve_backup_dir(backup_dir)
        backup_path = self.backup(target) if target is not None else None
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

    def backup(self, backup_dir: object = _DEFAULT_BACKUP_DIR) -> str:
        target = self._resolve_backup_dir(backup_dir)
        if target is None:
            target = self.backup_dir
        os.makedirs(target, exist_ok=True)
        preset = self.dump()
        # Microsecond precision so rapid successive backups never collide and
        # silently overwrite each other (e.g. an auto-backup during restore).
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        path = os.path.join(target, f"lpk25-backup-{stamp}.json")
        preset.save(path)
        return path

    def restore(self, path: str, verify: bool = True) -> list[WriteResult]:
        preset = Preset.load(path)
        return self.load(preset, verify=verify)

    # --- behavioural oracle ----------------------------------------------

    def monitor(self, callback: Callable[[bytes], None], duration: float | None = None) -> None:
        mon = getattr(self.transport, "monitor", None)
        if mon is None:
            raise DeviceError("this transport does not support monitoring")
        mon(callback, duration)
