from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from dataclasses import replace
from typing import Any, Mapping, cast
from typing import Literal


RbacPermission = Literal["read", "write", "admin"]
RbacPolicy = dict[str, tuple[RbacPermission, ...]]
IdentityRbacPolicy = dict[str, tuple[RbacPermission, ...]]


def _default_rbac_policy() -> RbacPolicy:
    return {
        "admin": ("read", "write", "admin"),
        "read": ("read",),
        "write": ("write",),
    }


@dataclass(frozen=True)
class RewardWeights:
    w0: float = 0.25
    w1: float = 0.25
    w2: float = 0.20
    w3: float = 0.20
    w4: float = 0.05
    w5: float = 0.05
    w6: float = 0.00
    w7: float = 0.10


@dataclass(frozen=True)
class SyvernSettings:
    validator_fingerprint: str = "syvern-phase2-pilot-http@0.8.0+rules@h4+intent@heuristic-h5+ops@h6+match@h9-normalized-fuzzy-v1"
    matching_policy_id: str = "h9-normalized-fuzzy-v1"
    judge_model: str = "h5-deterministic-heuristic"
    rubric_version: str = "h5-rubric-v1"
    intent_vote_count: int = 3
    kappa_min: float = 0.6
    min_tokens: int = 3
    min_elements: int = 1
    repetition_ratio: float = 0.65
    enum_ratio: float = 0.75
    enum_min_group_size: int = 4
    ipt_threshold: float = 1.0
    fuzzy_threshold: int = 1
    data_filter_min_reward: float = 0.8
    cap_type: int = 4
    cap_cons: int = 4
    cap_hall: int = 4
    r_max: float = 1.0
    monitor_semantic_gain_threshold: float = 0.20
    monitor_coverage_stall_threshold: float = 0.05
    monitor_veto_rate_increase_threshold: float = 0.20
    monitor_stable_drop_threshold: float = 0.20
    pilot_endpoint: str = "http://127.0.0.1:8888"
    pilot_version: str = "0.6.0"
    pilot_timeout_s: float = 2.0
    monticore_endpoint: str | None = None
    monticore_version: str = "0.6.0"
    monticore_timeout_s: float = 2.0
    formal_endpoint: str | None = None
    formal_tool: Literal["imandra", "gamma", "nuxmv"] | None = None
    formal_version: str = "0.0.0"
    formal_timeout_s: float = 5.0
    intent_judge_endpoint: str | None = None
    intent_judge_timeout_s: float = 5.0
    structural_matcher_endpoint: str | None = None
    structural_matcher_timeout_s: float = 5.0
    perturbation_endpoint: str | None = None
    perturbation_model: str = "h10-perturbation-generator"
    perturbation_rubric_version: str = "h10-ipt-perturb-v1"
    perturbation_timeout_s: float = 5.0
    api_token: str | None = None
    api_read_token: str | None = None
    api_write_token: str | None = None
    api_admin_token: str | None = None
    api_rbac_policy: RbacPolicy = field(default_factory=_default_rbac_policy)
    enable_identity_rbac: bool = False
    identity_rbac_policy: IdentityRbacPolicy = field(default_factory=dict)
    enforce_tenant_isolation: bool = False
    cache_path: str | None = None
    cache_max_size: int = 1024
    record_store_path: str | None = None
    record_retention_limit: int | None = None
    audit_log_path: str | None = None
    audit_retention_limit: int | None = None
    audit_sink_endpoint: str | None = None
    audit_sink_timeout_s: float = 2.0
    weights: RewardWeights = RewardWeights()

    def __post_init__(self) -> None:
        if not self.validator_fingerprint.strip():
            raise ValueError("validator_fingerprint must not be empty")
        if not self.judge_model.strip():
            raise ValueError("judge_model must not be empty")
        if not self.rubric_version.strip():
            raise ValueError("rubric_version must not be empty")
        if not self.perturbation_model.strip():
            raise ValueError("perturbation_model must not be empty")
        if not self.perturbation_rubric_version.strip():
            raise ValueError("perturbation_rubric_version must not be empty")
        for name in ("api_token", "api_read_token", "api_write_token", "api_admin_token"):
            value = getattr(self, name)
            if value is not None and not value.strip():
                raise ValueError(f"{name} must not be empty when configured")
        _validate_rbac_policy(self.api_rbac_policy, "api_rbac_policy")
        _validate_rbac_policy(self.identity_rbac_policy, "identity_rbac_policy")
        if self.intent_vote_count < 1:
            raise ValueError("intent_vote_count must be at least 1")
        if not -1.0 <= self.kappa_min <= 1.0:
            raise ValueError("kappa_min must be between -1.0 and 1.0")
        if self.fuzzy_threshold < 0:
            raise ValueError("fuzzy_threshold must not be negative")
        if self.r_max > 0 and not 0.0 <= self.data_filter_min_reward <= self.r_max:
            raise ValueError("data_filter_min_reward must be between 0.0 and r_max")
        if self.cache_max_size <= 0:
            raise ValueError("cache_max_size must be positive")
        if self.record_retention_limit is not None and self.record_retention_limit <= 0:
            raise ValueError("record_retention_limit must be positive")
        if self.audit_retention_limit is not None and self.audit_retention_limit <= 0:
            raise ValueError("audit_retention_limit must be positive")
        for name in (
            "pilot_timeout_s",
            "monticore_timeout_s",
            "formal_timeout_s",
            "intent_judge_timeout_s",
            "structural_matcher_timeout_s",
            "perturbation_timeout_s",
            "audit_sink_timeout_s",
        ):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")
        if self.formal_endpoint and self.formal_tool is None:
            raise ValueError("formal_tool is required when formal_endpoint is set")


_STRING_ENV_FIELDS: dict[str, str] = {
    "SYVERN_VALIDATOR_FINGERPRINT": "validator_fingerprint",
    "SYVERN_MATCHING_POLICY_ID": "matching_policy_id",
    "SYVERN_JUDGE_MODEL": "judge_model",
    "SYVERN_RUBRIC_VERSION": "rubric_version",
    "SYVERN_PILOT_ENDPOINT": "pilot_endpoint",
    "SYVERN_PILOT_VERSION": "pilot_version",
    "SYVERN_MONTICORE_ENDPOINT": "monticore_endpoint",
    "SYVERN_MONTICORE_VERSION": "monticore_version",
    "SYVERN_FORMAL_ENDPOINT": "formal_endpoint",
    "SYVERN_FORMAL_TOOL": "formal_tool",
    "SYVERN_FORMAL_VERSION": "formal_version",
    "SYVERN_INTENT_JUDGE_ENDPOINT": "intent_judge_endpoint",
    "SYVERN_STRUCTURAL_MATCHER_ENDPOINT": "structural_matcher_endpoint",
    "SYVERN_PERTURBATION_ENDPOINT": "perturbation_endpoint",
    "SYVERN_PERTURBATION_MODEL": "perturbation_model",
    "SYVERN_PERTURBATION_RUBRIC_VERSION": "perturbation_rubric_version",
    "SYVERN_API_TOKEN": "api_token",
    "SYVERN_API_READ_TOKEN": "api_read_token",
    "SYVERN_API_WRITE_TOKEN": "api_write_token",
    "SYVERN_API_ADMIN_TOKEN": "api_admin_token",
    "SYVERN_API_RBAC_POLICY": "api_rbac_policy",
    "SYVERN_IDENTITY_RBAC_POLICY": "identity_rbac_policy",
    "SYVERN_CACHE_PATH": "cache_path",
    "SYVERN_RECORD_STORE_PATH": "record_store_path",
    "SYVERN_AUDIT_LOG_PATH": "audit_log_path",
    "SYVERN_AUDIT_SINK_ENDPOINT": "audit_sink_endpoint",
}

_INT_ENV_FIELDS: dict[str, str] = {
    "SYVERN_INTENT_VOTE_COUNT": "intent_vote_count",
    "SYVERN_MIN_TOKENS": "min_tokens",
    "SYVERN_MIN_ELEMENTS": "min_elements",
    "SYVERN_ENUM_MIN_GROUP_SIZE": "enum_min_group_size",
    "SYVERN_FUZZY_THRESHOLD": "fuzzy_threshold",
    "SYVERN_CAP_TYPE": "cap_type",
    "SYVERN_CAP_CONS": "cap_cons",
    "SYVERN_CAP_HALL": "cap_hall",
    "SYVERN_CACHE_MAX_SIZE": "cache_max_size",
    "SYVERN_RECORD_RETENTION_LIMIT": "record_retention_limit",
    "SYVERN_AUDIT_RETENTION_LIMIT": "audit_retention_limit",
}

_FLOAT_ENV_FIELDS: dict[str, str] = {
    "SYVERN_KAPPA_MIN": "kappa_min",
    "SYVERN_REPETITION_RATIO": "repetition_ratio",
    "SYVERN_ENUM_RATIO": "enum_ratio",
    "SYVERN_IPT_THRESHOLD": "ipt_threshold",
    "SYVERN_DATA_FILTER_MIN_REWARD": "data_filter_min_reward",
    "SYVERN_R_MAX": "r_max",
    "SYVERN_MONITOR_SEMANTIC_GAIN_THRESHOLD": "monitor_semantic_gain_threshold",
    "SYVERN_MONITOR_COVERAGE_STALL_THRESHOLD": "monitor_coverage_stall_threshold",
    "SYVERN_MONITOR_VETO_RATE_INCREASE_THRESHOLD": "monitor_veto_rate_increase_threshold",
    "SYVERN_MONITOR_STABLE_DROP_THRESHOLD": "monitor_stable_drop_threshold",
    "SYVERN_PILOT_TIMEOUT_S": "pilot_timeout_s",
    "SYVERN_MONTICORE_TIMEOUT_S": "monticore_timeout_s",
    "SYVERN_FORMAL_TIMEOUT_S": "formal_timeout_s",
    "SYVERN_INTENT_JUDGE_TIMEOUT_S": "intent_judge_timeout_s",
    "SYVERN_STRUCTURAL_MATCHER_TIMEOUT_S": "structural_matcher_timeout_s",
    "SYVERN_PERTURBATION_TIMEOUT_S": "perturbation_timeout_s",
    "SYVERN_AUDIT_SINK_TIMEOUT_S": "audit_sink_timeout_s",
}

_BOOL_ENV_FIELDS: dict[str, str] = {
    "SYVERN_ENABLE_IDENTITY_RBAC": "enable_identity_rbac",
    "SYVERN_ENFORCE_TENANT_ISOLATION": "enforce_tenant_isolation",
}

_WEIGHT_ENV_FIELDS: dict[str, str] = {
    "SYVERN_WEIGHT_W0": "w0",
    "SYVERN_WEIGHT_W1": "w1",
    "SYVERN_WEIGHT_W2": "w2",
    "SYVERN_WEIGHT_W3": "w3",
    "SYVERN_WEIGHT_W4": "w4",
    "SYVERN_WEIGHT_W5": "w5",
    "SYVERN_WEIGHT_W6": "w6",
    "SYVERN_WEIGHT_W7": "w7",
}


def load_settings_from_env(environ: Mapping[str, str] | None = None) -> SyvernSettings:
    source = os.environ if environ is None else environ
    kwargs: dict[str, object] = {}

    for env_name, field_name in _STRING_ENV_FIELDS.items():
        value = _optional_string(source.get(env_name))
        if value is not None:
            kwargs[field_name] = (
                _parse_rbac_policy(value, env_name)
                if field_name in {"api_rbac_policy", "identity_rbac_policy"}
                else value
            )

    for env_name, field_name in _INT_ENV_FIELDS.items():
        value = _optional_string(source.get(env_name))
        if value is not None:
            kwargs[field_name] = _parse_int(env_name, value)

    for env_name, field_name in _FLOAT_ENV_FIELDS.items():
        value = _optional_string(source.get(env_name))
        if value is not None:
            kwargs[field_name] = _parse_float(env_name, value)

    for env_name, field_name in _BOOL_ENV_FIELDS.items():
        value = _optional_string(source.get(env_name))
        if value is not None:
            kwargs[field_name] = _parse_bool(env_name, value)

    weights = RewardWeights()
    weight_values: dict[str, float] = {}
    for env_name, field_name in _WEIGHT_ENV_FIELDS.items():
        value = _optional_string(source.get(env_name))
        if value is not None:
            weight_values[field_name] = _parse_float(env_name, value)
    if weight_values:
        weights = replace(weights, **weight_values)
        kwargs["weights"] = weights

    return SyvernSettings(**cast(Any, kwargs))


def _optional_string(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _parse_int(env_name: str, value: str) -> int:
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{env_name} must be an integer") from exc


def _parse_float(env_name: str, value: str) -> float:
    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(f"{env_name} must be a float") from exc


def _parse_bool(env_name: str, value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{env_name} must be a boolean")


def _parse_rbac_policy(value: str, source_name: str = "SYVERN_API_RBAC_POLICY") -> RbacPolicy:
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{source_name} must be a JSON object") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{source_name} must be a JSON object")

    policy: RbacPolicy = {}
    for role, permissions in payload.items():
        if not isinstance(role, str) or not isinstance(permissions, list):
            raise ValueError(f"{source_name} must map role names to permission lists")
        parsed_permissions: list[RbacPermission] = []
        for permission in permissions:
            if permission not in {"read", "write", "admin"}:
                raise ValueError(f"{source_name} contains unknown permission {permission}")
            parsed_permissions.append(cast(RbacPermission, permission))
        policy[role] = tuple(parsed_permissions)
    _validate_rbac_policy(policy, source_name)
    return dict(sorted(policy.items()))


def _validate_rbac_policy(policy: RbacPolicy, source_name: str) -> None:
    if not isinstance(policy, dict):
        raise ValueError(f"{source_name} must be a mapping")
    for role, permissions in policy.items():
        if not role.strip():
            raise ValueError(f"{source_name} role names must not be empty")
        for permission in permissions:
            if permission not in {"read", "write", "admin"}:
                raise ValueError(f"{source_name} contains unknown permission {permission}")
