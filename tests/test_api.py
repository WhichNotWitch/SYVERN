import pytest
from fastapi.testclient import TestClient

from syvern.api import app, validation_cache, validation_records


@pytest.fixture(autouse=True)
def clear_api_state():
    validation_cache.clear()
    validation_records.clear()
    yield
    validation_cache.clear()
    validation_records.clear()


def _reference(engine_name="vehicle.engine"):
    return {
        "elements": [
            {"type": "part", "qualified_name": engine_name},
            {"type": "attribute", "qualified_name": "vehicle.mass"},
        ],
        "requirements": ["req.power", "req.mass"],
        "coverage": {
            "req.power": [engine_name],
            "req.mass": ["vehicle.mass"],
        },
    }


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


def test_validate_accepts_metadata_records_event_without_echoing_metadata():
    client = TestClient(app)
    payload = {
        "text": "part A attribute x",
        "mode": "online_reward",
        "metadata": {"domain": "vehicle", "checkpoint": "rft-001"},
    }

    response = client.post("/validate", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert "metadata" not in body
    records = validation_records.list()
    assert len(records) == 1
    assert records[0].metadata == {"domain": "vehicle", "checkpoint": "rft-001"}
    assert records[0].cache_hit is False


def test_validate_rejects_non_string_metadata_value():
    client = TestClient(app)

    response = client.post(
        "/validate",
        json={"text": "part A attribute x", "mode": "online_reward", "metadata": {"epoch": 1}},
    )

    assert response.status_code == 422


def test_metadata_does_not_change_cache_identity_but_records_each_event():
    client = TestClient(app)
    first = client.post(
        "/validate",
        json={"text": "part A attribute x", "mode": "online_reward", "metadata": {"checkpoint": "a"}},
    ).json()
    second = client.post(
        "/validate",
        json={"text": "part A attribute x", "mode": "online_reward", "metadata": {"checkpoint": "b"}},
    ).json()

    assert first["meta"]["cache_hit"] is False
    assert second["meta"]["cache_hit"] is True
    records = validation_records.list()
    assert [record.metadata for record in records] == [{"checkpoint": "a"}, {"checkpoint": "b"}]
    assert [record.cache_hit for record in records] == [False, True]


def test_validate_full_with_reference_returns_structural_scores():
    client = TestClient(app)
    payload = {
        "text": "part vehicle.engine attribute vehicle.mass",
        "mode": "full",
        "reference": _reference(),
    }

    response = client.post("/validate", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["structural"]["evaluated"] is True
    assert body["structural"]["f1"] == 1.0
    assert body["structural"]["requirement_coverage"] == 1.0
    assert body["structural"]["matching_policy_id"] == "h3-frozen-exact-v1"
    assert body["tier_summary"]["t1_available"] is True


def test_validate_full_with_perturbations_returns_ipt_consistency():
    client = TestClient(app)
    payload = {
        "text": "part vehicle.engine attribute vehicle.mass",
        "mode": "full",
        "reference": _reference(),
        "perturbations": ["attribute vehicle.mass part vehicle.engine"],
    }

    response = client.post("/validate", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["structural"]["evaluated"] is True
    assert body["robustness"]["ipt_consistent"] is True


def test_cache_key_distinguishes_reference_for_structural_scores():
    client = TestClient(app)
    payload = {
        "text": "part vehicle.engine attribute vehicle.mass",
        "mode": "full",
        "reference": _reference(),
    }

    first = client.post("/validate", json=payload).json()
    second = client.post("/validate", json=payload).json()
    changed_reference = {
        **payload,
        "reference": _reference(engine_name="vehicle.motor"),
    }
    third = client.post("/validate", json=changed_reference).json()

    assert first["meta"]["cache_hit"] is False
    assert second["meta"]["cache_hit"] is True
    assert third["meta"]["cache_hit"] is False
    assert third["structural"]["f1"] < 1.0


def test_cache_key_distinguishes_perturbations_for_ipt_results():
    client = TestClient(app)
    payload = {
        "text": "part vehicle.engine attribute vehicle.mass",
        "mode": "full",
        "reference": _reference(),
        "perturbations": ["attribute vehicle.mass part vehicle.engine"],
    }
    different_perturbation = {
        **payload,
        "perturbations": ["part vehicle.engine"],
    }

    first = client.post("/validate", json=payload).json()
    second = client.post("/validate", json=payload).json()
    third = client.post("/validate", json=different_perturbation).json()

    assert first["meta"]["cache_hit"] is False
    assert second["meta"]["cache_hit"] is True
    assert third["meta"]["cache_hit"] is False
    assert first["robustness"]["ipt_consistent"] is True
    assert third["robustness"]["ipt_consistent"] is False


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


def test_validate_batch_records_every_item_in_order_with_metadata():
    client = TestClient(app)
    payload = {
        "texts": ["part A attribute x", "part B unresolved_ref"],
        "mode": "online_reward",
        "metadata": {"domain": "vehicle"},
    }

    response = client.post("/validate_batch", json=payload)

    assert response.status_code == 200
    records = validation_records.list()
    assert len(records) == 2
    assert [record.text_hash for record in records] == [
        item["meta"]["text_hash"] for item in response.json()["responses"]
    ]
    assert [record.metadata for record in records] == [{"domain": "vehicle"}, {"domain": "vehicle"}]


def test_validate_batch_rejects_non_string_metadata_value():
    client = TestClient(app)

    response = client.post(
        "/validate_batch",
        json={
            "texts": ["part A attribute x"],
            "mode": "online_reward",
            "metadata": {"epoch": 1},
        },
    )

    assert response.status_code == 422


def test_validate_batch_forwards_reference_to_each_response():
    client = TestClient(app)
    payload = {
        "texts": ["part vehicle.engine attribute vehicle.mass"],
        "mode": "full",
        "reference": _reference(),
    }

    body = client.post("/validate_batch", json=payload).json()

    assert body["responses"][0]["structural"]["evaluated"] is True
    assert body["responses"][0]["structural"]["f1"] == 1.0


def test_validate_batch_forwards_perturbations_to_each_response():
    client = TestClient(app)
    response = client.post(
        "/validate_batch",
        json={
            "texts": ["part vehicle.engine attribute vehicle.mass"],
            "mode": "full",
            "reference": _reference(),
            "perturbations": ["attribute vehicle.mass part vehicle.engine"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["responses"][0]["robustness"]["ipt_consistent"] is True


def test_validate_batch_rejects_empty_texts():
    client = TestClient(app)

    response = client.post("/validate_batch", json={"texts": [], "mode": "online_reward"})

    assert response.status_code == 422


def _intent_reference():
    return {
        "requirements": ["model engine", "include mass"],
        "must_include": ["vehicle.engine", "vehicle.mass"],
        "must_not_include": ["aircraft.wing"],
    }


def test_validate_full_forwards_intent_reference():
    client = TestClient(app)
    payload = {
        "text": "part vehicle.engine attribute vehicle.mass",
        "mode": "full",
        "intent_reference": _intent_reference(),
    }

    response = client.post("/validate", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["intent"]["evaluated"] is True
    assert body["intent"]["source"] == "llm_judge"
    assert body["intent"]["score"] > 3.0


def test_validate_batch_forwards_intent_reference_to_each_response():
    client = TestClient(app)
    payload = {
        "texts": ["part vehicle.engine attribute vehicle.mass"],
        "mode": "full",
        "intent_reference": _intent_reference(),
    }

    response = client.post("/validate_batch", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["responses"][0]["intent"]["evaluated"] is True
    assert body["responses"][0]["intent"]["score"] > 3.0


def test_cache_key_distinguishes_intent_reference_for_intent_results():
    client = TestClient(app)
    payload = {
        "text": "part vehicle.engine attribute vehicle.mass",
        "mode": "full",
        "intent_reference": _intent_reference(),
    }
    changed_intent = {
        **payload,
        "intent_reference": {
            "must_include": ["aircraft.engine"],
            "must_not_include": ["vehicle.mass"],
        },
    }

    first = client.post("/validate", json=payload).json()
    second = client.post("/validate", json=payload).json()
    third = client.post("/validate", json=changed_intent).json()

    assert first["meta"]["cache_hit"] is False
    assert second["meta"]["cache_hit"] is True
    assert third["meta"]["cache_hit"] is False
    assert third["intent"]["score"] < first["intent"]["score"]


def test_reward_config_endpoint_returns_h6_config():
    client = TestClient(app)

    response = client.get("/reward_config")

    assert response.status_code == 200
    body = response.json()
    assert body["validator_fingerprint"].startswith("syvern-h6-stub@0.6.0")
    assert set(body["weights"]) == {"w0", "w1", "w2", "w3", "w4", "w5", "w6", "w7"}
    assert body["caps"] == {"cap_type": 4, "cap_cons": 4, "cap_hall": 4}
    assert body["matching_policy_id"] == "h3-frozen-exact-v1"


def test_monitor_summary_endpoint_returns_empty_then_recorded_summary():
    client = TestClient(app)

    empty = client.get("/monitor_summary").json()
    assert empty["record_count"] == 0
    assert empty["semantic_pass_rate"] == 0.0
    assert empty["divergence_alerts"] == []

    client.post("/validate", json={"text": "part A attribute x", "mode": "online_reward"})
    current = client.get("/monitor_summary").json()

    assert current["record_count"] == 1
    assert current["semantic_pass_rate"] == 1.0
    assert current["t0_pass_rate"] == 1.0
    assert current["stable_at_k"] == 1.0
