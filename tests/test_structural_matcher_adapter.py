import json
from urllib.error import URLError

from syvern.adapters.structural_matcher import LLMStructuralMatcherAdapter
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


def test_llm_structural_matcher_posts_element_pair_and_rubric(monkeypatch):
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
        return FakeResponse({"match": True})

    monkeypatch.setattr("syvern.adapters.structural_matcher.urlopen", fake_urlopen)

    adapter = LLMStructuralMatcherAdapter(
        endpoint="http://matcher.local/api",
        model="judge-model-1",
        rubric_version="rubric-v2",
        timeout_s=2.0,
    )
    result = adapter.match(
        ElementSummary(type="part", qualified_name="vehicle.motor"),
        ElementSummary(type="part", qualified_name="vehicle.engine"),
    )

    assert calls == [
        {
            "url": "http://matcher.local/api/structural_match",
            "timeout": 2.0,
            "body": {
                "generated": {"type": "part", "qualified_name": "vehicle.motor"},
                "reference": {"type": "part", "qualified_name": "vehicle.engine"},
                "model": "judge-model-1",
                "rubric_version": "rubric-v2",
            },
            "content_type": "application/json",
        }
    ]
    assert result is True


def test_llm_structural_matcher_backend_errors_are_non_matches(monkeypatch):
    def fake_urlopen(request, timeout):
        raise URLError("connection refused")

    monkeypatch.setattr("syvern.adapters.structural_matcher.urlopen", fake_urlopen)

    adapter = LLMStructuralMatcherAdapter(
        endpoint="http://matcher.local/api",
        model="judge-model-1",
        rubric_version="rubric-v2",
        timeout_s=2.0,
    )

    assert adapter.match(
        ElementSummary(type="part", qualified_name="vehicle.motor"),
        ElementSummary(type="part", qualified_name="vehicle.engine"),
    ) is False


def test_llm_structural_matcher_fingerprint_uses_model_and_rubric():
    adapter = LLMStructuralMatcherAdapter(
        endpoint="http://matcher.local/api",
        model="judge-model-1",
        rubric_version="rubric-v2",
        timeout_s=2.0,
    )

    assert adapter.fingerprint() == "structural-llm@judge-model-1+rubric@rubric-v2"
