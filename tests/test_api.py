import pytest
from fastapi.testclient import TestClient

import syvern.api as api_module
from syvern.audit import SQLiteAuditEventStore
from syvern.api import app, audit_events, reset_monitor_summary_window, validation_cache, validation_records
from syvern.settings import SyvernSettings


@pytest.fixture(autouse=True)
def clear_api_state():
    validation_cache.clear()
    validation_records.clear()
    audit_events.clear()
    reset_monitor_summary_window()
    yield
    validation_cache.clear()
    validation_records.clear()
    audit_events.clear()
    reset_monitor_summary_window()


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


def test_validate_circuit_breaks_to_503_on_pilot_backend_error(monkeypatch):
    from syvern.adapters.pilot import PilotBackendError

    def boom(*args, **kwargs):
        raise PilotBackendError("connection refused")

    monkeypatch.setattr(api_module.pipeline, "validate", boom)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post("/validate", json={"text": "part vehicle.engine", "mode": "online_reward"})

    assert response.status_code == 503
    assert "pilot backend unavailable" in response.json()["detail"]
    # backend outage must not be recorded as a (reward-0) validation event
    assert validation_records.list() == []


def test_health_endpoint_remains_public_when_api_token_is_configured(monkeypatch):
    monkeypatch.setattr(api_module, "settings", SyvernSettings(api_token="secret-token"))
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.parametrize(
    "path",
    ["/validate", "/validate_batch", "/reward_config", "/audit_events", "/monitor_summary", "/dashboard_snapshot"],
)
def test_protected_endpoints_reject_missing_api_token_when_configured(monkeypatch, path):
    monkeypatch.setattr(api_module, "settings", SyvernSettings(api_token="secret-token"))
    client = TestClient(app)
    payload = (
        {"text": "part A attribute x", "mode": "online_reward"}
        if path == "/validate"
        else {"texts": ["part A attribute x"], "mode": "online_reward"}
    )

    response = client.post(path, json=payload) if path.startswith("/validate") else client.get(path)

    assert response.status_code == 401
    assert response.json()["detail"] == "missing or invalid API token"


def test_auth_decisions_are_recorded_without_token_values(monkeypatch):
    monkeypatch.setattr(
        api_module,
        "settings",
        SyvernSettings(api_read_token="read-token", api_write_token="write-token"),
    )
    client = TestClient(app)

    allowed = client.get(
        "/monitor_summary",
        headers={"X-SYVERN-API-Key": "read-token", "X-SYVERN-Tenant": "tenant-a"},
    )
    denied = client.post(
        "/validate",
        json={"text": "part A attribute x", "mode": "online_reward"},
        headers={"X-SYVERN-API-Key": "read-token", "X-SYVERN-Tenant": "tenant-a"},
    )

    events = audit_events.list()
    assert allowed.status_code == 200
    assert denied.status_code == 403
    assert [event.outcome for event in events] == ["allowed", "denied"]
    assert [event.path for event in events] == ["/monitor_summary", "/validate"]
    assert [event.required_permission for event in events] == ["read", "write"]
    assert [event.token_role for event in events] == ["read", "read"]
    assert [event.tenant_id for event in events] == ["tenant-a", "tenant-a"]
    assert all(event.token_present for event in events)
    assert "read-token" not in repr(events)


def test_audit_events_endpoint_requires_admin_scope(monkeypatch):
    monkeypatch.setattr(
        api_module,
        "settings",
        SyvernSettings(api_read_token="read-token", api_admin_token="admin-token"),
    )
    client = TestClient(app)

    denied = client.get("/audit_events", headers={"X-SYVERN-API-Key": "read-token"})
    allowed = client.get("/audit_events", headers={"X-SYVERN-API-Key": "admin-token"})

    assert denied.status_code == 403
    assert allowed.status_code == 200
    body = allowed.json()
    assert body[-1]["path"] == "/audit_events"
    assert body[-1]["required_permission"] == "admin"
    assert body[-1]["outcome"] == "allowed"


def test_auth_audit_events_can_use_configured_sqlite_store(monkeypatch, tmp_path):
    audit_path = tmp_path / "audit.sqlite3"
    monkeypatch.setattr(
        api_module,
        "settings",
        SyvernSettings(api_read_token="read-token", audit_log_path=str(audit_path)),
    )
    monkeypatch.setattr(api_module, "audit_events", SQLiteAuditEventStore(audit_path))
    client = TestClient(app)

    response = client.get("/monitor_summary", headers={"X-SYVERN-API-Key": "read-token"})

    assert response.status_code == 200
    reopened = SQLiteAuditEventStore(audit_path)
    assert [(event.path, event.outcome, event.token_role) for event in reopened.list()] == [
        ("/monitor_summary", "allowed", "read")
    ]


def test_auth_audit_events_are_exported_to_optional_sink(monkeypatch):
    exported = []

    class CapturingSink:
        def add(self, event):
            exported.append(event)

    monkeypatch.setattr(
        api_module,
        "settings",
        SyvernSettings(api_read_token="read-token", audit_sink_endpoint="http://audit.local/events"),
    )
    monkeypatch.setattr(api_module, "audit_event_sink", CapturingSink())
    client = TestClient(app)

    response = client.get("/monitor_summary", headers={"X-SYVERN-API-Key": "read-token"})

    assert response.status_code == 200
    assert [(event.path, event.outcome, event.token_role) for event in exported] == [
        ("/monitor_summary", "allowed", "read")
    ]
    assert "read-token" not in repr(exported)


def test_auth_audit_sink_failure_does_not_block_request_or_local_audit(monkeypatch):
    class FailingSink:
        def add(self, event):
            raise OSError("audit sink unavailable")

    monkeypatch.setattr(
        api_module,
        "settings",
        SyvernSettings(api_read_token="read-token", audit_sink_endpoint="http://audit.local/events"),
    )
    monkeypatch.setattr(api_module, "audit_event_sink", FailingSink())
    client = TestClient(app)

    response = client.get("/monitor_summary", headers={"X-SYVERN-API-Key": "read-token"})

    assert response.status_code == 200
    assert [(event.path, event.outcome) for event in audit_events.list()] == [("/monitor_summary", "allowed")]


def test_validate_accepts_bearer_api_token_when_configured(monkeypatch):
    monkeypatch.setattr(api_module, "settings", SyvernSettings(api_token="secret-token"))
    client = TestClient(app)

    response = client.post(
        "/validate",
        json={"text": "part A attribute x", "mode": "online_reward"},
        headers={"Authorization": "Bearer secret-token"},
    )

    assert response.status_code == 200


def test_reward_config_accepts_api_key_header_when_configured(monkeypatch):
    monkeypatch.setattr(api_module, "settings", SyvernSettings(api_token="secret-token"))
    client = TestClient(app)

    response = client.get("/reward_config", headers={"X-SYVERN-API-Key": "secret-token"})

    assert response.status_code == 200


def test_rbac_tokens_enforce_read_and_write_scopes(monkeypatch):
    monkeypatch.setattr(
        api_module,
        "settings",
        SyvernSettings(
            api_read_token="read-token",
            api_write_token="write-token",
            api_admin_token="admin-token",
        ),
    )
    client = TestClient(app)

    read_monitor = client.get("/monitor_summary", headers={"X-SYVERN-API-Key": "read-token"})
    read_validate = client.post(
        "/validate",
        json={"text": "part A attribute x", "mode": "online_reward"},
        headers={"X-SYVERN-API-Key": "read-token"},
    )
    write_validate = client.post(
        "/validate",
        json={"text": "part A attribute x", "mode": "online_reward"},
        headers={"Authorization": "Bearer write-token"},
    )
    write_monitor = client.get("/monitor_summary", headers={"Authorization": "Bearer write-token"})
    admin_monitor = client.get("/monitor_summary", headers={"X-SYVERN-API-Key": "admin-token"})
    admin_validate = client.post(
        "/validate",
        json={"text": "part B attribute y", "mode": "online_reward"},
        headers={"X-SYVERN-API-Key": "admin-token"},
    )

    assert read_monitor.status_code == 200
    assert read_validate.status_code == 403
    assert read_validate.json()["detail"] == "insufficient API token scope"
    assert write_validate.status_code == 200
    assert write_monitor.status_code == 403
    assert write_monitor.json()["detail"] == "insufficient API token scope"
    assert admin_monitor.status_code == 200
    assert admin_validate.status_code == 200


def test_identity_headers_are_not_trusted_unless_identity_rbac_is_enabled(monkeypatch):
    monkeypatch.setattr(api_module, "settings", SyvernSettings(api_token="secret-token"))
    client = TestClient(app)

    response = client.get(
        "/monitor_summary",
        headers={"X-SYVERN-User": "alice", "X-SYVERN-Groups": "sysml-readers"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "missing or invalid API token"


def test_identity_group_rbac_grants_read_scope_and_records_audit(monkeypatch):
    monkeypatch.setattr(
        api_module,
        "settings",
        SyvernSettings(
            enable_identity_rbac=True,
            identity_rbac_policy={"sysml-readers": ("read",)},
        ),
    )
    client = TestClient(app)

    response = client.get(
        "/monitor_summary",
        headers={"X-SYVERN-User": "alice", "X-SYVERN-Groups": "sysml-readers, other-group"},
    )

    assert response.status_code == 200
    events = audit_events.list()
    assert [(event.path, event.outcome, event.auth_method, event.principal_id) for event in events] == [
        ("/monitor_summary", "allowed", "identity", "alice")
    ]
    assert events[0].principal_groups == ("other-group", "sysml-readers")
    assert events[0].token_present is False


def test_identity_group_rbac_denies_insufficient_scope(monkeypatch):
    monkeypatch.setattr(
        api_module,
        "settings",
        SyvernSettings(
            enable_identity_rbac=True,
            identity_rbac_policy={"sysml-readers": ("read",)},
        ),
    )
    client = TestClient(app)

    response = client.post(
        "/validate",
        json={"text": "part A attribute x", "mode": "online_reward"},
        headers={"X-SYVERN-User": "alice", "X-SYVERN-Groups": "sysml-readers"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "insufficient API token scope"
    events = audit_events.list()
    assert [(event.outcome, event.reason, event.auth_method, event.principal_id) for event in events] == [
        ("denied", "insufficient_scope", "identity", "alice")
    ]


def test_legacy_api_token_retains_admin_scope_when_rbac_tokens_are_configured(monkeypatch):
    monkeypatch.setattr(
        api_module,
        "settings",
        SyvernSettings(
            api_token="legacy-token",
            api_read_token="read-token",
            api_write_token="write-token",
            api_admin_token="admin-token",
        ),
    )
    client = TestClient(app)

    validate_response = client.post(
        "/validate",
        json={"text": "part A attribute x", "mode": "online_reward"},
        headers={"X-SYVERN-API-Key": "legacy-token"},
    )
    monitor_response = client.get("/monitor_summary", headers={"X-SYVERN-API-Key": "legacy-token"})

    assert validate_response.status_code == 200
    assert monitor_response.status_code == 200


def test_rbac_policy_can_grant_write_permission_to_read_token(monkeypatch):
    monkeypatch.setattr(
        api_module,
        "settings",
        SyvernSettings(
            api_read_token="read-token",
            api_rbac_policy={"read": ("read", "write"), "write": ("write",), "admin": ("read", "write", "admin")},
        ),
    )
    client = TestClient(app)

    response = client.post(
        "/validate",
        json={"text": "part A attribute x", "mode": "online_reward"},
        headers={"X-SYVERN-API-Key": "read-token"},
    )

    assert response.status_code == 200


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
        "formal",
        "veto",
        "monitor",
        "meta",
    }
    assert body["formal"]["evaluated"] is False
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


def test_validate_data_filter_returns_filter_decision_in_meta():
    client = TestClient(app)

    accepted = client.post(
        "/validate",
        json={"text": "part vehicle.engine attribute vehicle.mass", "mode": "data_filter"},
    ).json()
    rejected = client.post(
        "/validate",
        json={"text": "part vehicle.engine attribute vehicle.mass type_error", "mode": "data_filter"},
    ).json()

    assert accepted["meta"]["data_filter_pass"] is True
    assert accepted["meta"]["data_filter_reason"] == "passed"
    assert rejected["meta"]["data_filter_pass"] is False
    assert rejected["meta"]["data_filter_reason"] == "t0_failed"


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


def test_validate_records_tenant_header_without_echoing_or_changing_cache_identity():
    client = TestClient(app)
    payload = {
        "text": "part A attribute x",
        "mode": "online_reward",
        "metadata": {"domain": "vehicle"},
    }

    first = client.post("/validate", json=payload, headers={"X-SYVERN-Tenant": "tenant-a"}).json()
    second = client.post("/validate", json=payload, headers={"X-SYVERN-Tenant": "tenant-b"}).json()

    assert "metadata" not in first
    assert first["meta"]["cache_hit"] is False
    assert second["meta"]["cache_hit"] is True
    records = validation_records.list()
    assert [record.metadata for record in records] == [
        {"domain": "vehicle", "tenant_id": "tenant-a"},
        {"domain": "vehicle", "tenant_id": "tenant-b"},
    ]


def test_tenant_isolation_rejects_validation_without_tenant_header_when_enabled(monkeypatch):
    monkeypatch.setattr(api_module, "settings", SyvernSettings(enforce_tenant_isolation=True))
    client = TestClient(app)

    response = client.post("/validate", json={"text": "part A attribute x", "mode": "online_reward"})

    assert response.status_code == 400
    assert response.json()["detail"] == "X-SYVERN-Tenant is required when tenant isolation is enabled"


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


def test_cache_hit_record_uses_event_latency_not_cached_pipeline_latency():
    client = TestClient(app)
    payload = {"text": "part A attribute x", "mode": "online_reward"}

    client.post("/validate", json=payload)
    cached_payload = next(iter(validation_cache._items.values()))
    cached_payload["meta"]["latency_ms"] = 999999
    second = client.post("/validate", json=payload).json()

    records = validation_records.list()
    assert second["meta"]["cache_hit"] is True
    assert second["meta"]["latency_ms"] < 999999
    assert records[1].cache_hit is True
    assert records[1].latency_ms < 999999
    assert next(iter(validation_cache._items.values()))["meta"]["latency_ms"] == 999999


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
    assert body["structural"]["matching_policy_id"] == "h9-normalized-fuzzy-v1"
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


def test_validate_batch_records_tenant_header_for_each_item():
    client = TestClient(app)

    response = client.post(
        "/validate_batch",
        json={
            "texts": ["part A attribute x", "part B unresolved_ref"],
            "mode": "online_reward",
            "metadata": {"domain": "vehicle"},
        },
        headers={"X-SYVERN-Tenant": "tenant-a"},
    )

    assert response.status_code == 200
    assert [record.metadata for record in validation_records.list()] == [
        {"domain": "vehicle", "tenant_id": "tenant-a"},
        {"domain": "vehicle", "tenant_id": "tenant-a"},
    ]


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
    assert body["intent"]["source"] == "heuristic"
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
    assert body["validator_fingerprint"].startswith("syvern-phase2-stub@0.7.0")
    assert set(body["weights"]) == {"w0", "w1", "w2", "w3", "w4", "w5", "w6", "w7"}
    assert body["caps"] == {"cap_type": 4, "cap_cons": 4, "cap_hall": 4}
    assert body["matching_policy_id"] == "h9-normalized-fuzzy-v1"
    assert body["fuzzy_threshold"] == 1
    assert body["data_filter_min_reward"] == 0.8


def test_monitor_summary_endpoint_returns_empty_then_recorded_summary():
    client = TestClient(app)

    empty = client.get("/monitor_summary").json()
    assert empty["record_count"] == 0
    assert empty["semantic_pass_rate"] == 0.0
    assert empty["formal_evaluated_count"] == 0
    assert empty["formal_proved_rate"] == 0.0
    assert empty["divergence_alerts"] == []

    client.post("/validate", json={"text": "part A attribute x", "mode": "online_reward"})
    current = client.get("/monitor_summary").json()

    assert current["record_count"] == 1
    assert current["semantic_pass_rate"] == 1.0
    assert current["t0_pass_rate"] == 1.0
    assert current["stable_at_k"] == 1.0
    assert current["formal_evaluated_count"] == 0


def test_tenant_isolation_filters_monitor_summary_by_tenant_header(monkeypatch):
    monkeypatch.setattr(api_module, "settings", SyvernSettings(enforce_tenant_isolation=True))
    client = TestClient(app)

    client.post(
        "/validate",
        json={"text": "part vehicle.engine attribute vehicle.mass", "mode": "online_reward"},
        headers={"X-SYVERN-Tenant": "tenant-a"},
    )
    client.post(
        "/validate",
        json={"text": "syntax_error sample", "mode": "online_reward"},
        headers={"X-SYVERN-Tenant": "tenant-b"},
    )

    missing = client.get("/monitor_summary")
    tenant_a = client.get("/monitor_summary", headers={"X-SYVERN-Tenant": "tenant-a"}).json()
    tenant_b = client.get("/monitor_summary", headers={"X-SYVERN-Tenant": "tenant-b"}).json()

    assert missing.status_code == 400
    assert missing.json()["detail"] == "X-SYVERN-Tenant is required when tenant isolation is enabled"
    assert tenant_a["record_count"] == 1
    assert tenant_a["semantic_pass_rate"] == 1.0
    assert tenant_b["record_count"] == 1
    assert tenant_b["semantic_pass_rate"] == 0.0


def test_dashboard_snapshot_endpoint_returns_empty_operational_view():
    client = TestClient(app)

    response = client.get("/dashboard_snapshot")

    assert response.status_code == 200
    body = response.json()
    assert body["validator_fingerprint"].startswith("syvern-phase2-stub@0.7.0")
    assert body["summary"]["record_count"] == 0
    assert body["summary"]["divergence_alerts"] == []
    assert body["tenant_summaries"] == []
    assert body["recent_records"] == []


def test_dashboard_snapshot_endpoint_reports_tenants_and_recent_records_without_raw_metadata():
    client = TestClient(app)

    first = client.post(
        "/validate",
        json={
            "text": "part vehicle.engine attribute vehicle.mass",
            "mode": "online_reward",
            "metadata": {"prompt_id": "prompt-a", "domain": "vehicle"},
        },
        headers={"X-SYVERN-Tenant": "tenant-a"},
    ).json()
    second = client.post(
        "/validate",
        json={
            "text": "syntax_error sample",
            "mode": "online_reward",
            "metadata": {"prompt_id": "prompt-b", "domain": "vehicle"},
        },
        headers={"X-SYVERN-Tenant": "tenant-b"},
    ).json()

    response = client.get("/dashboard_snapshot?limit=1")

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["record_count"] == 2
    assert body["summary"]["semantic_pass_rate"] == 0.5
    assert body["tenant_summaries"] == [
        {"tenant_id": "tenant-a", "record_count": 1, "semantic_pass_rate": 1.0, "average_reward": first["meta"]["reward"]},
        {
            "tenant_id": "tenant-b",
            "record_count": 1,
            "semantic_pass_rate": 0.0,
            "average_reward": second["meta"]["reward"],
        },
    ]
    assert body["recent_records"] == [
        {
            "sample_id": second["sample_id"],
            "text_hash": second["meta"]["text_hash"],
            "mode": "online_reward",
            "cache_hit": False,
            "semantic_pass": False,
            "t0_pass": False,
            "veto_triggered": False,
            "veto_reason": None,
            "reward": second["meta"]["reward"],
            "latency_ms": second["meta"]["latency_ms"],
            "tenant_id": "tenant-b",
            "prompt_id": "prompt-b",
            "formal_status": None,
        }
    ]
    assert "domain" not in body["recent_records"][0]


def test_tenant_isolation_filters_dashboard_snapshot_by_tenant_header(monkeypatch):
    monkeypatch.setattr(api_module, "settings", SyvernSettings(enforce_tenant_isolation=True))
    client = TestClient(app)

    first = client.post(
        "/validate",
        json={
            "text": "part vehicle.engine attribute vehicle.mass",
            "mode": "online_reward",
            "metadata": {"prompt_id": "prompt-a"},
        },
        headers={"X-SYVERN-Tenant": "tenant-a"},
    ).json()
    client.post(
        "/validate",
        json={
            "text": "syntax_error sample",
            "mode": "online_reward",
            "metadata": {"prompt_id": "prompt-b"},
        },
        headers={"X-SYVERN-Tenant": "tenant-b"},
    )

    missing = client.get("/dashboard_snapshot")
    tenant_a = client.get("/dashboard_snapshot", headers={"X-SYVERN-Tenant": "tenant-a"}).json()

    assert missing.status_code == 400
    assert tenant_a["summary"]["record_count"] == 1
    assert tenant_a["summary"]["semantic_pass_rate"] == 1.0
    assert tenant_a["tenant_summaries"] == [
        {
            "tenant_id": "tenant-a",
            "record_count": 1,
            "semantic_pass_rate": 1.0,
            "average_reward": first["meta"]["reward"],
        }
    ]
    assert [record["tenant_id"] for record in tenant_a["recent_records"]] == ["tenant-a"]


def test_monitor_summary_endpoint_reports_cross_window_divergence():
    client = TestClient(app)

    for index in range(5):
        client.post("/validate", json={"text": f"syntax_error sample {index}", "mode": "online_reward"})
    previous = client.get("/monitor_summary").json()
    assert previous["semantic_pass_rate"] == 0.0
    assert previous["divergence_alerts"] == []

    validation_records.clear()
    for index in range(5):
        client.post(
            "/validate",
            json={"text": f"part vehicle.engine{index} attribute vehicle.mass{index}", "mode": "online_reward"},
        )
    current = client.get("/monitor_summary").json()

    assert current["semantic_pass_rate"] == 1.0
    assert [alert["code"] for alert in current["divergence_alerts"]] == ["semantic_without_coverage"]
