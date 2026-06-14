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
