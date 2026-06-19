import json
from urllib.error import URLError

from syvern.adapters.perturbation import LLMPerturbationAdapter


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def test_llm_perturbation_adapter_posts_spec_count_and_rubric(monkeypatch):
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
        return FakeResponse({"perturbations": ["rewrite a", "rewrite b"]})

    monkeypatch.setattr("syvern.adapters.perturbation.urlopen", fake_urlopen)

    adapter = LLMPerturbationAdapter(
        endpoint="http://perturb.local/api",
        model="perturb-model-1",
        rubric_version="ipt-rubric-v1",
        timeout_s=2.0,
    )

    assert adapter.generate("model the engine", 2) == ["rewrite a", "rewrite b"]
    assert calls == [
        {
            "url": "http://perturb.local/api/perturb",
            "timeout": 2.0,
            "body": {
                "spec": "model the engine",
                "n": 2,
                "model": "perturb-model-1",
                "rubric_version": "ipt-rubric-v1",
            },
            "content_type": "application/json",
        }
    ]


def test_llm_perturbation_adapter_filters_malformed_backend_payload(monkeypatch):
    def fake_urlopen(request, timeout):
        return FakeResponse({"perturbations": [" keep ", 7, "", "keep", "second"]})

    monkeypatch.setattr("syvern.adapters.perturbation.urlopen", fake_urlopen)

    adapter = LLMPerturbationAdapter(
        endpoint="http://perturb.local/api",
        model="perturb-model-1",
        rubric_version="ipt-rubric-v1",
        timeout_s=2.0,
    )

    assert adapter.generate("spec", 3) == ["keep", "second"]


def test_llm_perturbation_adapter_backend_errors_return_empty_list(monkeypatch):
    def fake_urlopen(request, timeout):
        raise URLError("connection refused")

    monkeypatch.setattr("syvern.adapters.perturbation.urlopen", fake_urlopen)

    adapter = LLMPerturbationAdapter(
        endpoint="http://perturb.local/api",
        model="perturb-model-1",
        rubric_version="ipt-rubric-v1",
        timeout_s=2.0,
    )

    assert adapter.generate("spec", 3) == []


def test_llm_perturbation_adapter_fingerprint_uses_model_and_rubric():
    adapter = LLMPerturbationAdapter(
        endpoint="http://perturb.local/api",
        model="perturb-model-1",
        rubric_version="ipt-rubric-v1",
        timeout_s=2.0,
    )

    assert adapter.fingerprint() == "perturbation-llm@perturb-model-1+rubric@ipt-rubric-v1"
