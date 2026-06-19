import json
from urllib.error import URLError

import pytest

from syvern.adapters.formal import FormalAdapter


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def test_formal_adapter_posts_text_and_properties(monkeypatch):
    calls = []

    def fake_urlopen(request, timeout):
        calls.append(
            {
                "url": request.full_url,
                "timeout": timeout,
                "body": json.loads(request.data.decode("utf-8")),
                "content_type": request.headers["Content-type"],
            }
        )
        return FakeResponse(
            {
                "status": "proved",
                "properties_checked": 2,
                "conclusions": ["contract power holds"],
                "counterexamples": [],
            }
        )

    monkeypatch.setattr("syvern.adapters.formal.urlopen", fake_urlopen)

    adapter = FormalAdapter(
        tool="imandra",
        endpoint="http://formal.local/api",
        version="2026.1",
        timeout_s=3.0,
    )
    result = adapter.analyze("part Vehicle.Engine", properties=["req.power", "req.mass"])

    assert calls == [
        {
            "url": "http://formal.local/api/analyze",
            "timeout": 3.0,
            "body": {"text": "part Vehicle.Engine", "properties": ["req.power", "req.mass"]},
            "content_type": "application/json",
        }
    ]
    assert result.tool == "imandra"
    assert result.status == "proved"
    assert result.properties_checked == 2
    assert result.conclusions == ["contract power holds"]
    assert result.counterexamples == []


def test_formal_adapter_maps_failed_contract_counterexamples(monkeypatch):
    def fake_urlopen(request, timeout):
        return FakeResponse(
            {
                "status": "failed",
                "properties_checked": 1,
                "conclusions": ["mass bound violated"],
                "counterexamples": ["mass = -1 kg"],
            }
        )

    monkeypatch.setattr("syvern.adapters.formal.urlopen", fake_urlopen)

    adapter = FormalAdapter(
        tool="gamma",
        endpoint="http://formal.local/api",
        version="2026.1",
        timeout_s=3.0,
    )
    result = adapter.analyze("part Vehicle.Engine")

    assert result.tool == "gamma"
    assert result.status == "failed"
    assert result.properties_checked == 1
    assert result.counterexamples == ["mass = -1 kg"]


def test_formal_adapter_turns_timeouts_into_timeout_results(monkeypatch):
    def fake_urlopen(request, timeout):
        raise TimeoutError("deadline exceeded")

    monkeypatch.setattr("syvern.adapters.formal.urlopen", fake_urlopen)

    adapter = FormalAdapter(
        tool="nuxmv",
        endpoint="http://formal.local/api",
        version="2026.1",
        timeout_s=0.1,
    )
    result = adapter.analyze("part Vehicle.Engine")

    assert result.tool == "nuxmv"
    assert result.status == "timeout"
    assert result.properties_checked == 0
    assert "deadline exceeded" in result.conclusions[0]


def test_formal_adapter_turns_backend_errors_into_error_results(monkeypatch):
    def fake_urlopen(request, timeout):
        raise URLError("connection refused")

    monkeypatch.setattr("syvern.adapters.formal.urlopen", fake_urlopen)

    adapter = FormalAdapter(
        tool="imandra",
        endpoint="http://formal.local/api",
        version="2026.1",
        timeout_s=3.0,
    )
    result = adapter.analyze("part Vehicle.Engine")

    assert result.status == "error"
    assert result.properties_checked == 0
    assert "connection refused" in result.conclusions[0]


def test_formal_adapter_rejects_unsupported_tools():
    with pytest.raises(ValueError, match="unsupported formal tool"):
        FormalAdapter(
            tool="other",
            endpoint="http://formal.local/api",
            version="2026.1",
            timeout_s=3.0,
        )


def test_formal_adapter_fingerprint_uses_tool_and_version():
    adapter = FormalAdapter(
        tool="imandra",
        endpoint="http://formal.local/api",
        version="2026.1",
        timeout_s=3.0,
    )

    assert adapter.fingerprint() == "formal-imandra@2026.1"
