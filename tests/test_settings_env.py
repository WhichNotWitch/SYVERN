import pytest

from syvern.settings import SyvernSettings, load_settings_from_env


def test_load_settings_from_env_uses_defaults_for_empty_environment():
    assert load_settings_from_env({}) == SyvernSettings()
    assert load_settings_from_env({}).pilot_endpoint == "http://127.0.0.1:8888"


def test_load_settings_from_env_ignores_removed_pilot_backend_switches():
    settings = load_settings_from_env(
        {"SYVERN_PILOT_BACKEND": "subset", "SYVERN_USE_SUBSET_PARSER": "true"}
    )
    assert settings.pilot_endpoint == "http://127.0.0.1:8888"


def test_load_settings_from_env_maps_production_configuration():
    settings = load_settings_from_env({
        "SYVERN_PILOT_ENDPOINT": "http://pilot.local/api",
        "SYVERN_PILOT_VERSION": "2026.1",
        "SYVERN_PILOT_TIMEOUT_S": "3.5",
        "SYVERN_MONTICORE_ENDPOINT": "http://monticore.local/api",
        "SYVERN_FORMAL_ENDPOINT": "http://formal.local/api",
        "SYVERN_FORMAL_TOOL": "imandra",
        "SYVERN_INTENT_JUDGE_ENDPOINT": "http://judge.local/api",
        "SYVERN_STRUCTURAL_MATCHER_ENDPOINT": "http://matcher.local/api",
        "SYVERN_PERTURBATION_ENDPOINT": "http://perturb.local/api",
        "SYVERN_CACHE_PATH": ".pytest_tmp/cache.sqlite3",
        "SYVERN_CACHE_MAX_SIZE": "17",
        "SYVERN_RECORD_STORE_PATH": ".pytest_tmp/records.sqlite3",
        "SYVERN_RECORD_RETENTION_LIMIT": "11",
        "SYVERN_AUDIT_LOG_PATH": ".pytest_tmp/audit.sqlite3",
        "SYVERN_AUDIT_RETENTION_LIMIT": "13",
        "SYVERN_AUDIT_SINK_ENDPOINT": "http://audit.local/events",
        "SYVERN_AUDIT_SINK_TIMEOUT_S": "1.5",
        "SYVERN_API_TOKEN": "secret-token",
        "SYVERN_API_READ_TOKEN": "read-token",
        "SYVERN_API_WRITE_TOKEN": "write-token",
        "SYVERN_API_ADMIN_TOKEN": "admin-token",
        "SYVERN_API_RBAC_POLICY": '{"read":["read"],"write":["write"],"admin":["read","write","admin"]}',
        "SYVERN_ENABLE_IDENTITY_RBAC": "true",
        "SYVERN_IDENTITY_RBAC_POLICY": '{"sysml-readers":["read"],"sysml-writers":["write"]}',
        "SYVERN_ENFORCE_TENANT_ISOLATION": "true",
        "SYVERN_DATA_FILTER_MIN_REWARD": "0.75",
    })

    assert settings.pilot_endpoint == "http://pilot.local/api"
    assert settings.pilot_version == "2026.1"
    assert settings.pilot_timeout_s == 3.5
    assert settings.monticore_endpoint == "http://monticore.local/api"
    assert settings.formal_endpoint == "http://formal.local/api"
    assert settings.formal_tool == "imandra"
    assert settings.intent_judge_endpoint == "http://judge.local/api"
    assert settings.structural_matcher_endpoint == "http://matcher.local/api"
    assert settings.perturbation_endpoint == "http://perturb.local/api"
    assert settings.cache_path == ".pytest_tmp/cache.sqlite3"
    assert settings.cache_max_size == 17
    assert settings.record_store_path == ".pytest_tmp/records.sqlite3"
    assert settings.record_retention_limit == 11
    assert settings.audit_log_path == ".pytest_tmp/audit.sqlite3"
    assert settings.audit_retention_limit == 13
    assert settings.audit_sink_endpoint == "http://audit.local/events"
    assert settings.audit_sink_timeout_s == 1.5
    assert settings.api_token == "secret-token"
    assert settings.api_read_token == "read-token"
    assert settings.api_write_token == "write-token"
    assert settings.api_admin_token == "admin-token"
    assert settings.api_rbac_policy == {
        "admin": ("read", "write", "admin"),
        "read": ("read",),
        "write": ("write",),
    }
    assert settings.enable_identity_rbac is True
    assert settings.identity_rbac_policy == {
        "sysml-readers": ("read",),
        "sysml-writers": ("write",),
    }
    assert settings.enforce_tenant_isolation is True
    assert settings.data_filter_min_reward == 0.75


def test_load_settings_from_env_ignores_blank_optional_strings():
    settings = load_settings_from_env({
        "SYVERN_API_TOKEN": " ",
        "SYVERN_API_READ_TOKEN": "",
        "SYVERN_API_WRITE_TOKEN": " ",
        "SYVERN_API_ADMIN_TOKEN": "",
        "SYVERN_CACHE_PATH": "",
        "SYVERN_RECORD_STORE_PATH": " ",
        "SYVERN_AUDIT_LOG_PATH": " ",
        "SYVERN_AUDIT_SINK_ENDPOINT": " ",
    })

    assert settings.api_token is None
    assert settings.api_read_token is None
    assert settings.api_write_token is None
    assert settings.api_admin_token is None
    assert settings.cache_path is None
    assert settings.record_store_path is None
    assert settings.audit_log_path is None
    assert settings.audit_sink_endpoint is None


def test_load_settings_from_env_maps_reward_weights():
    settings = load_settings_from_env({
        "SYVERN_WEIGHT_W0": "0.10",
        "SYVERN_WEIGHT_W4": "0.25",
        "SYVERN_WEIGHT_W7": "0.03",
    })

    assert settings.weights.w0 == 0.10
    assert settings.weights.w4 == 0.25
    assert settings.weights.w7 == 0.03


def test_load_settings_from_env_rejects_invalid_integer_values():
    with pytest.raises(ValueError, match="SYVERN_CACHE_MAX_SIZE must be an integer"):
        load_settings_from_env({"SYVERN_CACHE_MAX_SIZE": "not-an-int"})


def test_load_settings_from_env_rejects_invalid_float_values():
    with pytest.raises(ValueError, match="SYVERN_PILOT_TIMEOUT_S must be a float"):
        load_settings_from_env({"SYVERN_PILOT_TIMEOUT_S": "not-a-float"})


def test_load_settings_from_env_rejects_invalid_boolean_values():
    with pytest.raises(ValueError, match="SYVERN_ENFORCE_TENANT_ISOLATION must be a boolean"):
        load_settings_from_env({"SYVERN_ENFORCE_TENANT_ISOLATION": "sometimes"})


def test_load_settings_from_env_rejects_invalid_rbac_policy_json():
    with pytest.raises(ValueError, match="SYVERN_API_RBAC_POLICY must be a JSON object"):
        load_settings_from_env({"SYVERN_API_RBAC_POLICY": "[]"})


def test_load_settings_from_env_rejects_unknown_rbac_permissions():
    with pytest.raises(ValueError, match="SYVERN_API_RBAC_POLICY contains unknown permission delete"):
        load_settings_from_env({"SYVERN_API_RBAC_POLICY": '{"read":["delete"]}'})


def test_load_settings_from_env_rejects_unknown_identity_rbac_permissions():
    with pytest.raises(ValueError, match="SYVERN_IDENTITY_RBAC_POLICY contains unknown permission delete"):
        load_settings_from_env({"SYVERN_IDENTITY_RBAC_POLICY": '{"sysml-users":["delete"]}'})
