"""Protocol discovery helpers: identify the device and probe for its model byte.

These are all **read-only** and therefore safe to run against real hardware.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import protocol
from .transport import Transport


@dataclass
class ProbeResult:
    model: int
    responded: bool
    reply: bytes | None = None


def identify(transport: Transport, timeout: float = 1.0) -> protocol.IdentityReply | None:
    """Send a Universal Device Inquiry and parse the reply, if any.

    This is the safest, most reliable way to learn the LPK25 mk1's model byte.
    """
    reply = transport.request(protocol.IDENTITY_REQUEST, timeout=timeout)
    if reply is None:
        return None
    try:
        return protocol.parse_identity_reply(reply)
    except protocol.ProtocolError:
        return None


def probe_models(
    transport: Transport,
    candidates: list[int] | None = None,
    timeout: float = 0.4,
) -> list[ProbeResult]:
    """Try a get-active-program request for each candidate model byte and record
    which ones reply. Read-only and safe."""
    candidates = candidates if candidates is not None else protocol.MK1_MODEL_CANDIDATES
    results: list[ProbeResult] = []
    for model in candidates:
        cfg = protocol.ProtocolConfig(model=model)
        reply = transport.request(protocol.build_get_active_program(cfg), timeout=timeout)
        ok = False
        if reply is not None:
            try:
                f = protocol.parse_frame(reply)
                ok = f.model == model
            except protocol.ProtocolError:
                ok = False
        results.append(ProbeResult(model=model, responded=ok, reply=reply))
    return results


def detect_model(transport: Transport) -> int | None:
    """Best-effort single model byte: prefer device inquiry, fall back to probing."""
    ident = identify(transport)
    if ident is not None and ident.member >= 0:
        # The inquiry's member id is not necessarily the SysEx model byte, so
        # confirm by probing; fall through if it doesn't match.
        pass
    for r in probe_models(transport):
        if r.responded:
            return r.model
    return None
