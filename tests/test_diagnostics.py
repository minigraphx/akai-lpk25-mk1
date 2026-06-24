from lpk25 import diagnostics as dg


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
