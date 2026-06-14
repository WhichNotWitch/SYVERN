from fastapi.testclient import TestClient

from syvern.api import app, validation_cache


def setup_function():
    validation_cache.clear()


def test_health_endpoint():
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_validate_returns_documented_top_level_fields():
    client = TestClient(app)
    response = client.post("/validate", json={"text": "part A attribute x", "mode": "online_reward"})
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "sample_id",
        "tier_summary",
        "stage",
        "structural",
        "robustness",
        "intent",
        "veto",
        "monitor",
        "meta",
    }
    assert body["meta"]["mode"] == "online_reward"


def test_repeated_request_hits_cache():
    client = TestClient(app)
    payload = {"text": "part A attribute x", "mode": "online_reward"}
    first = client.post("/validate", json=payload).json()
    second = client.post("/validate", json=payload).json()
    assert first["meta"]["cache_hit"] is False
    assert second["meta"]["cache_hit"] is True
    first["meta"]["latency_ms"] = 0
    second["meta"]["latency_ms"] = 0
    first["meta"]["cache_hit"] = True
    assert first == second


def test_cache_key_distinguishes_mode():
    client = TestClient(app)
    online = client.post("/validate", json={"text": "part A attribute x", "mode": "online_reward"}).json()
    full = client.post("/validate", json={"text": "part A attribute x", "mode": "full"}).json()
    assert online["meta"]["mode"] == "online_reward"
    assert full["meta"]["mode"] == "full"
    assert full["meta"]["cache_hit"] is False


def test_validate_batch_returns_robustness_metrics_and_ordered_responses():
    client = TestClient(app)
    payload = {
        "texts": [
            "part A attribute x",
            "part B unresolved_ref",
            "part C type_error",
        ],
        "mode": "online_reward",
    }

    response = client.post("/validate_batch", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["sample_count"] == 3
    assert body["pass_at_k"] == 1.0
    assert body["stable_at_k"] == 1 / 3
    assert body["meta"]["mode"] == "online_reward"
    assert [item["meta"]["text_hash"] for item in body["responses"]] == [
        client.post("/validate", json={"text": text, "mode": "online_reward"}).json()["meta"]["text_hash"]
        for text in payload["texts"]
    ]


def test_validate_batch_uses_single_validation_cache_path():
    client = TestClient(app)
    payload = {"texts": ["part A attribute x", "part A attribute x"], "mode": "online_reward"}

    body = client.post("/validate_batch", json=payload).json()

    assert body["responses"][0]["meta"]["cache_hit"] is False
    assert body["responses"][1]["meta"]["cache_hit"] is True


def test_validate_batch_rejects_empty_texts():
    client = TestClient(app)

    response = client.post("/validate_batch", json={"texts": [], "mode": "online_reward"})

    assert response.status_code == 422
