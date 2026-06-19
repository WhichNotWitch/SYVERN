import json
from urllib.error import URLError

from syvern.adapters.base import ParseResult
from syvern.adapters.monticore import MontiCoreAdapter
from syvern.models import ElementSummary


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class FakePilot:
    name = "pilot"

    def __init__(self, result: ParseResult) -> None:
        self.result = result

    def parse(self, text: str) -> ParseResult:
        return self.result


def test_monticore_adapter_parse_posts_text_and_maps_elements(monkeypatch):
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

    monkeypatch.setattr("syvern.adapters.monticore.urlopen", fake_urlopen)

    adapter = MontiCoreAdapter(endpoint="http://monticore.local/api", version="2026.1", timeout_s=1.5)
    result = adapter.parse("part Vehicle.Engine")

    assert calls == [
        {
            "url": "http://monticore.local/api/parse",
            "timeout": 1.5,
            "body": {"text": "part Vehicle.Engine"},
            "content_type": "application/json",
        }
    ]
    assert result.ok is True
    assert [(item.type, item.qualified_name) for item in result.element_summary] == [
        ("part", "vehicle.engine")
    ]


def test_monticore_adapter_parser_agrees_on_normalized_element_multisets(monkeypatch):
    def fake_urlopen(request, timeout):
        return FakeResponse(
            {
                "ok": True,
                "elements": [
                    {"type": "attribute", "qualified_name": "Vehicle.Mass"},
                    {"type": "part", "qualified_name": "Vehicle.Engine"},
                ],
                "errors": [],
            }
        )

    monkeypatch.setattr("syvern.adapters.monticore.urlopen", fake_urlopen)

    pilot = FakePilot(
        ParseResult(
            ok=True,
            element_summary=[
                ElementSummary(type="part", qualified_name="vehicle.engine"),
                ElementSummary(type="attribute", qualified_name="vehicle.mass"),
            ],
        )
    )
    adapter = MontiCoreAdapter(endpoint="http://monticore.local/api", version="2026.1", timeout_s=1.5)

    assert adapter.parser_agrees("part Vehicle.Engine attribute Vehicle.Mass", pilot) is True


def test_monticore_adapter_parser_disagrees_on_parse_status_or_summary(monkeypatch):
    responses = [
        {"ok": False, "elements": [], "errors": []},
        {
            "ok": True,
            "elements": [{"type": "part", "qualified_name": "vehicle.body"}],
            "errors": [],
        },
    ]

    def fake_urlopen(request, timeout):
        return FakeResponse(responses.pop(0))

    monkeypatch.setattr("syvern.adapters.monticore.urlopen", fake_urlopen)

    pilot = FakePilot(
        ParseResult(
            ok=True,
            element_summary=[ElementSummary(type="part", qualified_name="vehicle.engine")],
        )
    )
    adapter = MontiCoreAdapter(endpoint="http://monticore.local/api", version="2026.1", timeout_s=1.5)

    assert adapter.parser_agrees("part vehicle.engine", pilot) is False
    assert adapter.parser_agrees("part vehicle.engine", pilot) is False


def test_monticore_adapter_normalizes_backend_errors(monkeypatch):
    def fake_urlopen(request, timeout):
        raise URLError("timed out")

    monkeypatch.setattr("syvern.adapters.monticore.urlopen", fake_urlopen)

    adapter = MontiCoreAdapter(endpoint="http://monticore.local/api", version="2026.1", timeout_s=1.5)
    result = adapter.parse("part Vehicle.Engine")

    assert result.ok is False
    assert result.errors[0].stage == "parse"
    assert result.errors[0].code == "MONTICORE_BACKEND_ERROR"
    assert "timed out" in result.errors[0].message


def test_monticore_adapter_fingerprint_uses_declared_backend_version():
    adapter = MontiCoreAdapter(endpoint="http://monticore.local/api", version="2026.1", timeout_s=1.5)

    assert adapter.fingerprint() == "monticore@2026.1"
