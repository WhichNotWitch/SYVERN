import json

import pytest
from urllib.error import URLError

from syvern.adapters.pilot import PilotAdapter, PilotBackendError


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


VALIDATE_PAYLOAD = {
    "parse": {"ok": True, "errors": []},
    "resolve": {
        "ok": False,
        "unresolved_refs": 2,
        "errors": [{"code": "RESOLVE_UNRESOLVED_REF", "message": "missing target", "location": "line 3"}],
    },
    "typecheck": {
        "ok": False,
        "type_errors": 1,
        "errors": [{"code": "TYPECHECK_ERROR", "message": "bad assignment"}],
    },
    "elements": [{"type": "Part", "qualified_name": "Vehicle.Engine"}],
    "backend_version": "2026.9",
}


def _adapter() -> PilotAdapter:
    return PilotAdapter(endpoint="http://pilot.local/api", version="2026.1", timeout_s=2.5)


def test_single_validate_call_feeds_all_three_stages(monkeypatch):
    calls = []

    def fake_urlopen(request, timeout):
        calls.append({"url": request.full_url, "method": request.get_method(), "timeout": timeout})
        return FakeResponse(VALIDATE_PAYLOAD)

    monkeypatch.setattr("syvern.adapters.pilot.urlopen", fake_urlopen)
    adapter = _adapter()

    parse = adapter.parse("part Vehicle.Engine")
    resolve = adapter.resolve("part Vehicle.Engine")
    typecheck = adapter.typecheck("part Vehicle.Engine")

    # one /validate round trip serves all three stages
    assert calls == [
        {"url": "http://pilot.local/api/validate", "method": "POST", "timeout": 2.5}
    ]
    assert parse.ok is True
    assert [(e.type, e.qualified_name) for e in parse.element_summary] == [("part", "vehicle.engine")]
    assert resolve.ok is False and resolve.unresolved_refs == 2
    assert resolve.errors[0].code == "RESOLVE_UNRESOLVED_REF" and resolve.errors[0].location == "line 3"
    assert typecheck.ok is False and typecheck.type_errors == 1
    assert typecheck.errors[0].code == "TYPECHECK_ERROR"


def test_distinct_texts_trigger_separate_calls(monkeypatch):
    calls = []

    def fake_urlopen(request, timeout):
        calls.append(json.loads(request.data.decode("utf-8"))["text"])
        return FakeResponse(VALIDATE_PAYLOAD)

    monkeypatch.setattr("syvern.adapters.pilot.urlopen", fake_urlopen)
    adapter = _adapter()

    adapter.parse("model a")
    adapter.parse("model b")
    adapter.resolve("model b")

    assert calls == ["model a", "model b"]  # memo refreshes on new text, reuses same text


def test_transport_error_raises_backend_error(monkeypatch):
    def fake_urlopen(request, timeout):
        raise URLError("timed out")

    monkeypatch.setattr("syvern.adapters.pilot.urlopen", fake_urlopen)
    adapter = _adapter()

    with pytest.raises(PilotBackendError) as excinfo:
        adapter.parse("part Vehicle.Engine")
    assert "timed out" in str(excinfo.value)


def test_validation_failure_is_not_a_backend_error(monkeypatch):
    payload = {"parse": {"ok": False, "errors": [{"code": "PARSE_SYNTAX_ERROR", "message": "x"}]},
               "resolve": {"ok": False}, "typecheck": {"ok": False}, "elements": []}
    monkeypatch.setattr("syvern.adapters.pilot.urlopen", lambda request, timeout: FakeResponse(payload))

    result = _adapter().parse("syntax_error")  # HTTP 200 + ok=false: a normal failure, no exception
    assert result.ok is False
    assert result.errors[0].code == "PARSE_SYNTAX_ERROR"


def test_fingerprint_handshakes_backend_version(monkeypatch):
    def fake_urlopen(request, timeout):
        assert request.full_url == "http://pilot.local/api/version"
        assert request.get_method() == "GET"
        return FakeResponse({"pilot_version": "2026.9", "grammar_version": "g", "rules_version": "r"})

    monkeypatch.setattr("syvern.adapters.pilot.urlopen", fake_urlopen)
    assert _adapter().fingerprint() == "pilot@2026.9"


def test_fingerprint_falls_back_when_version_unavailable(monkeypatch):
    def fake_urlopen(request, timeout):
        raise URLError("down")

    monkeypatch.setattr("syvern.adapters.pilot.urlopen", fake_urlopen)
    assert _adapter().fingerprint() == "pilot@2026.1"  # operator-declared fallback
