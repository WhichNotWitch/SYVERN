import json
from urllib.error import URLError

from syvern.adapters.intent_judge import LLMIntentJudgeAdapter


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def test_llm_intent_judge_posts_text_reference_and_rubric(monkeypatch):
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
        return FakeResponse({"evaluated": True, "score": 4.25})

    monkeypatch.setattr("syvern.adapters.intent_judge.urlopen", fake_urlopen)

    adapter = LLMIntentJudgeAdapter(
        endpoint="http://judge.local/api",
        model="judge-model-1",
        rubric_version="rubric-v2",
        timeout_s=2.0,
    )
    result = adapter.judge(
        "part vehicle.engine",
        {"must_include": ["vehicle.engine"]},
    )

    assert calls == [
        {
            "url": "http://judge.local/api/judge",
            "timeout": 2.0,
            "body": {
                "text": "part vehicle.engine",
                "intent_reference": {"must_include": ["vehicle.engine"]},
                "model": "judge-model-1",
                "rubric_version": "rubric-v2",
            },
            "content_type": "application/json",
        }
    ]
    assert result.evaluated is True
    assert result.score == 4.25
    assert result.source == "llm_judge"


def test_llm_intent_judge_clamps_backend_score(monkeypatch):
    def fake_urlopen(request, timeout):
        return FakeResponse({"evaluated": True, "score": 9.0})

    monkeypatch.setattr("syvern.adapters.intent_judge.urlopen", fake_urlopen)

    adapter = LLMIntentJudgeAdapter(
        endpoint="http://judge.local/api",
        model="judge-model-1",
        rubric_version="rubric-v2",
        timeout_s=2.0,
    )

    assert adapter.judge("text", {"must_include": ["x"]}).score == 5.0


def test_llm_intent_judge_backend_errors_are_unevaluated(monkeypatch):
    def fake_urlopen(request, timeout):
        raise URLError("connection refused")

    monkeypatch.setattr("syvern.adapters.intent_judge.urlopen", fake_urlopen)

    adapter = LLMIntentJudgeAdapter(
        endpoint="http://judge.local/api",
        model="judge-model-1",
        rubric_version="rubric-v2",
        timeout_s=2.0,
    )
    result = adapter.judge("text", {"must_include": ["x"]})

    assert result.evaluated is False
    assert result.score is None
    assert result.source is None


def test_llm_intent_judge_fingerprint_uses_model_and_rubric():
    adapter = LLMIntentJudgeAdapter(
        endpoint="http://judge.local/api",
        model="judge-model-1",
        rubric_version="rubric-v2",
        timeout_s=2.0,
    )

    assert adapter.fingerprint() == "intent-llm@judge-model-1+rubric@rubric-v2"
