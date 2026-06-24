from lpk25 import diagnostics as dg
from lpk25.device import Device
from lpk25.transport import MockTransport


def test_check_backend_mock_is_ok():
    r = dg.check_backend(mock=True)
    assert r.status == "ok"
    assert "mock" in r.detail.lower()


def test_check_backend_present(monkeypatch):
    monkeypatch.setattr(dg, "_module_present", lambda name: True)
    r = dg.check_backend(mock=False)
    assert r.status == "ok"
    assert "mido" in r.detail


def test_check_backend_missing_gives_install_hint(monkeypatch):
    monkeypatch.setattr(dg, "_module_present", lambda name: False)
    r = dg.check_backend(mock=False)
    assert r.status == "fail"
    assert r.hint == dg.INSTALL_HINT


def test_check_ports_mock_is_ok():
    assert dg.check_ports(True, "LPK25", None, None).status == "ok"


def test_check_ports_matched():
    def fake():
        return {"inputs": ["LPK25:LPK25 MIDI 1 24:0"], "outputs": ["LPK25:LPK25 MIDI 1 24:0"]}
    r = dg.check_ports(False, "LPK25", None, None, list_ports_fn=fake)
    assert r.status == "ok"
    assert "LPK25" in r.detail


def test_check_ports_no_match_fails_with_hint():
    def fake():
        return {"inputs": ["Some Synth"], "outputs": ["Some Synth"]}
    r = dg.check_ports(False, "LPK25", None, None, list_ports_fn=fake)
    assert r.status == "fail"
    assert r.hint and "--port" in r.hint


def test_check_ports_none_present_fails():
    def fake():
        return {"inputs": [], "outputs": []}
    r = dg.check_ports(False, "LPK25", None, None, list_ports_fn=fake)
    assert r.status == "fail"


def test_check_ports_explicit_names_bypass_match():
    def fake():
        return {"inputs": ["weird-in"], "outputs": ["weird-out"]}
    r = dg.check_ports(False, "LPK25", "weird-in", "weird-out", list_ports_fn=fake)
    assert r.status == "ok"


class _SilentTransport:
    def send(self, frame): pass
    def receive(self, timeout=1.0): return None
    def request(self, frame, timeout=1.0): return None
    def close(self): pass


def test_check_device_responds_default_model_ok():
    r = dg.check_device(MockTransport(model=0x76))
    assert r.status == "ok"
    assert "0x76" in r.detail


def test_check_device_wrong_model_warns():
    r = dg.check_device(MockTransport(model=0x77), expected_model=0x76)
    assert r.status == "warn"
    assert "--model" in (r.hint or "")


def test_check_device_silent_fails():
    r = dg.check_device(_SilentTransport())
    assert r.status == "fail"
    assert "asleep" in (r.hint or "")


def test_check_roundtrip_ok(tmp_path):
    dev = Device(MockTransport())
    dev.backup_dir = str(tmp_path)
    r = dg.check_roundtrip(dev)
    assert r.status == "ok"
    assert "verified" in r.detail


def test_run_diagnostics_all_ok_mock(tmp_path):
    def factory():
        dev = Device(MockTransport())
        dev.backup_dir = str(tmp_path)
        return dev

    results = dg.run_diagnostics(
        mock=True, port_match="LPK25", in_port=None, out_port=None,
        model=None, roundtrip=True, device_factory=factory,
    )
    assert [r.status for r in results] == ["ok", "ok", "ok", "ok"]


def test_run_diagnostics_backend_fail_skips_downstream(monkeypatch):
    monkeypatch.setattr(dg, "_module_present", lambda name: False)
    calls = []
    results = dg.run_diagnostics(
        mock=False, port_match="LPK25", in_port=None, out_port=None,
        model=None, roundtrip=True,
        device_factory=lambda: calls.append(1),  # must never be called
    )
    assert results[0].status == "fail"
    assert [r.status for r in results[1:]] == ["skip", "skip", "skip"]
    assert calls == []


def test_run_diagnostics_roundtrip_off_is_skip(tmp_path):
    def factory():
        dev = Device(MockTransport())
        dev.backup_dir = str(tmp_path)
        return dev

    results = dg.run_diagnostics(
        mock=True, port_match="LPK25", in_port=None, out_port=None,
        model=None, roundtrip=False, device_factory=factory,
    )
    assert results[3].status == "skip"
    assert "--roundtrip" in results[3].detail
