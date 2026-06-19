import json
from urllib.error import URLError

from syvern.adapters.pilot import PilotAdapter


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def test_pilot_adapter_parse_posts_text_and_maps_elements(monkeypatch):
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
                "ok": True,
                "elements": [{"type": "Part", "qualified_name": "Vehicle.Engine"}],
                "errors": [],
            }
        )

    monkeypatch.setattr("syvern.adapters.pilot.urlopen", fake_urlopen)

    adapter = PilotAdapter(endpoint="http://pilot.local/api", version="2026.1", timeout_s=2.5)
    result = adapter.parse("part Vehicle.Engine")

    assert calls == [
        {
            "url": "http://pilot.local/api/parse",
            "timeout": 2.5,
            "body": {"text": "part Vehicle.Engine"},
            "content_type": "application/json",
        }
    ]
    assert result.ok is True
    assert [(item.type, item.qualified_name) for item in result.element_summary] == [
        ("part", "vehicle.engine")
    ]


def test_pilot_adapter_maps_resolve_and_typecheck_counts(monkeypatch):
    responses = [
        {
            "ok": False,
            "unresolved_refs": 2,
            "errors": [
                {
                    "code": "RESOLVE_UNRESOLVED_REF",
                    "message": "missing target",
                    "location": "line 3",
                }
            ],
        },
        {
            "ok": False,
            "type_errors": 1,
            "errors": [{"code": "TYPECHECK_ERROR", "message": "bad assignment"}],
        },
    ]

    def fake_urlopen(request, timeout):
        return FakeResponse(responses.pop(0))

    monkeypatch.setattr("syvern.adapters.pilot.urlopen", fake_urlopen)

    adapter = PilotAdapter(endpoint="http://pilot.local/api", version="2026.1", timeout_s=2.5)
    resolve = adapter.resolve("part Vehicle.Engine unresolved")
    typecheck = adapter.typecheck("part Vehicle.Engine type mismatch")

    assert resolve.ok is False
    assert resolve.unresolved_refs == 2
    assert resolve.errors[0].stage == "resolve"
    assert resolve.errors[0].code == "RESOLVE_UNRESOLVED_REF"
    assert resolve.errors[0].location == "line 3"
    assert typecheck.ok is False
    assert typecheck.type_errors == 1
    assert typecheck.errors[0].stage == "typecheck"
    assert typecheck.errors[0].code == "TYPECHECK_ERROR"


def test_pilot_adapter_normalizes_backend_errors(monkeypatch):
    def fake_urlopen(request, timeout):
        raise URLError("timed out")

    monkeypatch.setattr("syvern.adapters.pilot.urlopen", fake_urlopen)

    adapter = PilotAdapter(endpoint="http://pilot.local/api", version="2026.1", timeout_s=2.5)
    result = adapter.parse("part Vehicle.Engine")

    assert result.ok is False
    assert result.errors[0].stage == "parse"
    assert result.errors[0].code == "PILOT_BACKEND_ERROR"
    assert "timed out" in result.errors[0].message


def test_pilot_adapter_fingerprint_uses_declared_backend_version():
    adapter = PilotAdapter(endpoint="http://pilot.local/api", version="2026.1", timeout_s=2.5)

    assert adapter.fingerprint() == "pilot@2026.1"
