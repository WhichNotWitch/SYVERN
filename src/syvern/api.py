from __future__ import annotations

from copy import deepcopy
from time import perf_counter
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, status

from syvern.adapters.pilot import PilotBackendError
from syvern.audit import AuditEvent, AuditOutcome
from syvern.cache import CacheKey
from syvern.models import (
    AuditEventSummary,
    BatchMetaSummary,
    BatchValidateRequest,
    BatchValidateResponse,
    DashboardSnapshot,
    Mode,
    MonitorAggregateSummary,
    RewardConfigSummary,
    ValidateRequest,
    ValidateResponse,
)
from syvern.monitoring import aggregate_dashboard_snapshot, aggregate_monitor_summary, detect_divergence
from syvern.normalization import (
    formal_properties_identity,
    intent_reference_identity,
    perturbation_identity,
    reference_identity,
    sha256_text,
)
from syvern.pipeline_factory import build_validation_pipeline
from syvern.records import ValidationRecord, make_validation_record
from syvern.robustness import aggregate_robustness
from syvern.reward_ops import reward_config_summary
from syvern.settings import load_settings_from_env
from syvern.storage_factory import (
    build_audit_event_sink,
    build_audit_event_store,
    build_validation_cache,
    build_validation_record_store,
)


settings = load_settings_from_env()
pipeline = build_validation_pipeline(settings)
settings = pipeline.settings
validation_cache = build_validation_cache(settings)
validation_records = build_validation_record_store(settings)
audit_events = build_audit_event_store(settings)
audit_event_sink = build_audit_event_sink(settings)
previous_monitor_summaries: dict[str, MonitorAggregateSummary] = {}
app = FastAPI(title="SYVERN", version="0.1.0")


def reset_monitor_summary_window() -> None:
    previous_monitor_summaries.clear()


def require_api_token(
    request: Request,
    authorization: str | None = Header(default=None),
    x_syvern_api_key: str | None = Header(default=None),
    x_syvern_tenant: str | None = Header(default=None),
    x_syvern_user: str | None = Header(default=None),
    x_syvern_groups: str | None = Header(default=None),
) -> None:
    _require_api_token_scope(
        "admin", authorization, x_syvern_api_key, request, x_syvern_tenant, x_syvern_user, x_syvern_groups
    )


def require_read_token(
    request: Request,
    authorization: str | None = Header(default=None),
    x_syvern_api_key: str | None = Header(default=None),
    x_syvern_tenant: str | None = Header(default=None),
    x_syvern_user: str | None = Header(default=None),
    x_syvern_groups: str | None = Header(default=None),
) -> None:
    _require_api_token_scope(
        "read", authorization, x_syvern_api_key, request, x_syvern_tenant, x_syvern_user, x_syvern_groups
    )


def require_write_token(
    request: Request,
    authorization: str | None = Header(default=None),
    x_syvern_api_key: str | None = Header(default=None),
    x_syvern_tenant: str | None = Header(default=None),
    x_syvern_user: str | None = Header(default=None),
    x_syvern_groups: str | None = Header(default=None),
) -> None:
    _require_api_token_scope(
        "write", authorization, x_syvern_api_key, request, x_syvern_tenant, x_syvern_user, x_syvern_groups
    )


def _require_api_token_scope(
    scope: str,
    authorization: str | None,
    x_syvern_api_key: str | None,
    request: Request,
    tenant_id: str | None,
    identity_user: str | None,
    identity_groups_header: str | None,
) -> None:
    configured_roles = _configured_api_token_roles()
    if not configured_roles and not settings.enable_identity_rbac:
        return

    provided_token = _provided_api_token(authorization, x_syvern_api_key)
    token_role = configured_roles.get(provided_token) if provided_token is not None else None
    token_present = provided_token is not None
    if token_role is not None:
        if _role_allows_scope(token_role, scope):
            _record_auth_event(
                request=request,
                scope=scope,
                outcome="allowed",
                reason=None,
                token_present=token_present,
                token_role=token_role,
                tenant_id=tenant_id,
                auth_method="token",
            )
            return
        _record_auth_event(
            request=request,
            scope=scope,
            outcome="denied",
            reason="insufficient_scope",
            token_present=token_present,
            token_role=token_role,
            tenant_id=tenant_id,
            auth_method="token",
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="insufficient API token scope",
        )

    identity_user_id = _normalize_identity_user(identity_user)
    identity_groups = _parse_identity_groups(identity_groups_header)
    if settings.enable_identity_rbac and identity_user_id is not None and identity_groups:
        if _identity_allows_scope(identity_groups, scope):
            _record_auth_event(
                request=request,
                scope=scope,
                outcome="allowed",
                reason=None,
                token_present=token_present,
                token_role=None,
                tenant_id=tenant_id,
                auth_method="identity",
                principal_id=identity_user_id,
                principal_groups=identity_groups,
            )
            return
        _record_auth_event(
            request=request,
            scope=scope,
            outcome="denied",
            reason="insufficient_scope",
            token_present=token_present,
            token_role=None,
            tenant_id=tenant_id,
            auth_method="identity",
            principal_id=identity_user_id,
            principal_groups=identity_groups,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="insufficient API token scope",
        )

    _record_auth_event(
        request=request,
        scope=scope,
        outcome="denied",
        reason="missing_or_invalid_token",
        token_present=token_present,
        token_role=None,
        tenant_id=tenant_id,
    )
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="missing or invalid API token",
    )


def _configured_api_tokens() -> set[str]:
    return {
        token
        for token in (
            settings.api_token,
            settings.api_read_token,
            settings.api_write_token,
            settings.api_admin_token,
        )
        if token is not None
    }


def _record_auth_event(
    *,
    request: Request,
    scope: str,
    outcome: AuditOutcome,
    reason: str | None,
    token_present: bool,
    token_role: str | None,
    tenant_id: str | None,
    auth_method: Literal["token", "identity"] | None = None,
    principal_id: str | None = None,
    principal_groups: tuple[str, ...] = (),
) -> None:
    event = AuditEvent(
        method=request.method,
        path=request.url.path,
        required_permission=scope,
        outcome=outcome,
        reason=reason,
        token_present=token_present,
        token_role=token_role,
        tenant_id=_normalize_tenant_header(tenant_id),
        auth_method=auth_method,
        principal_id=principal_id,
        principal_groups=principal_groups,
    )
    audit_events.add(event)
    if audit_event_sink is None:
        return
    try:
        audit_event_sink.add(event)
    except OSError:
        return


def _tokens_for_scope(scope: str) -> set[str]:
    return {
        token
        for token, role in _configured_api_token_roles().items()
        if _role_allows_scope(role, scope)
    }


def _configured_api_token_roles() -> dict[str, str]:
    roles: dict[str, str] = {}
    for token, role in (
        (settings.api_token, "admin"),
        (settings.api_read_token, "read"),
        (settings.api_write_token, "write"),
        (settings.api_admin_token, "admin"),
    ):
        if token is not None:
            roles[token] = role
    return roles


def _role_allows_scope(role: str, scope: str) -> bool:
    permissions = settings.api_rbac_policy.get(role, ())
    return "admin" in permissions or scope in permissions


def _identity_allows_scope(groups: tuple[str, ...], scope: str) -> bool:
    permissions = {
        permission
        for group in groups
        for permission in settings.identity_rbac_policy.get(group, ())
    }
    return "admin" in permissions or scope in permissions


def _normalize_identity_user(identity_user: str | None) -> str | None:
    if identity_user is None:
        return None
    normalized = identity_user.strip()
    return normalized or None


def _parse_identity_groups(identity_groups_header: str | None) -> tuple[str, ...]:
    if identity_groups_header is None:
        return ()
    return tuple(sorted({group.strip() for group in identity_groups_header.split(",") if group.strip()}))


def _provided_api_token(
    authorization: str | None,
    x_syvern_api_key: str | None,
) -> str | None:
    if x_syvern_api_key is not None:
        return x_syvern_api_key
    if authorization is not None and authorization.startswith("Bearer "):
        return authorization.removeprefix("Bearer ")
    return None


def _metadata_with_tenant(
    metadata: dict[str, str] | None,
    tenant_id: str | None,
) -> dict[str, str] | None:
    normalized_tenant = _normalize_tenant_header(tenant_id)
    if normalized_tenant is None:
        return metadata
    merged = dict(metadata or {})
    merged["tenant_id"] = normalized_tenant
    return merged


def _normalize_tenant_header(tenant_id: str | None) -> str | None:
    if tenant_id is None:
        return None
    normalized_tenant = tenant_id.strip()
    return normalized_tenant or None


def _tenant_or_raise(tenant_id: str | None) -> str | None:
    normalized_tenant = _normalize_tenant_header(tenant_id)
    if settings.enforce_tenant_isolation and normalized_tenant is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X-SYVERN-Tenant is required when tenant isolation is enabled",
        )
    return normalized_tenant


def _records_for_tenant(
    records: list[ValidationRecord],
    tenant_id: str | None,
) -> list[ValidationRecord]:
    if not settings.enforce_tenant_isolation:
        return records
    return [record for record in records if record.metadata.get("tenant_id") == tenant_id]


def _monitor_scope_key(tenant_id: str | None) -> str:
    return f"tenant:{tenant_id}" if settings.enforce_tenant_isolation else "global"


def _validate_with_cache(
    text: str,
    *,
    mode: Mode,
    reference: dict | None,
    perturbations: list[str] | None,
    intent_reference: dict | None,
    formal_properties: list[str] | None,
    metadata: dict[str, str] | None,
) -> ValidateResponse:
    started = perf_counter()
    text_hash = sha256_text(text)
    key = CacheKey(
        text_hash=text_hash,
        validator_fingerprint=settings.validator_fingerprint,
        mode=mode,
        reference_id=reference_identity(reference),
        perturbation_id=perturbation_identity(perturbations),
        intent_reference_id=intent_reference_identity(intent_reference),
        formal_properties_id=formal_properties_identity(formal_properties),
    )
    cached = validation_cache.get(key)
    if cached is not None:
        cached_payload = deepcopy(cached)
        cached_payload["meta"]["cache_hit"] = True
        cached_payload["meta"]["latency_ms"] = int((perf_counter() - started) * 1000)
        response = ValidateResponse.model_validate(cached_payload)
        validation_records.add(make_validation_record(response, metadata=metadata))
        return response

    try:
        response = pipeline.validate(
            text,
            mode=mode,
            reference=reference,
            perturbations=perturbations,
            intent_reference=intent_reference,
            formal_properties=formal_properties,
        )
    except PilotBackendError as exc:
        # Backend unavailable is not a model failure: circuit-break with 503
        # instead of recording a misleading reward-0 result.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"pilot backend unavailable: {exc}",
        ) from exc
    payload = response.model_dump(mode="json")
    payload["meta"]["cache_hit"] = False
    validation_cache.set(key, payload)
    response = ValidateResponse.model_validate(payload)
    validation_records.add(make_validation_record(response, metadata=metadata))
    return response


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/validate", response_model=ValidateResponse)
def validate(
    request: ValidateRequest,
    _auth: None = Depends(require_write_token),
    x_syvern_tenant: str | None = Header(default=None),
) -> ValidateResponse:
    tenant_id = _tenant_or_raise(x_syvern_tenant)
    return _validate_with_cache(
        request.text,
        mode=request.mode,
        reference=request.reference,
        perturbations=request.perturbations,
        intent_reference=request.intent_reference,
        formal_properties=request.formal_properties,
        metadata=_metadata_with_tenant(request.metadata, tenant_id),
    )


@app.post("/validate_batch", response_model=BatchValidateResponse)
def validate_batch(
    request: BatchValidateRequest,
    _auth: None = Depends(require_write_token),
    x_syvern_tenant: str | None = Header(default=None),
) -> BatchValidateResponse:
    tenant_id = _tenant_or_raise(x_syvern_tenant)
    metadata = _metadata_with_tenant(request.metadata, tenant_id)
    responses = [
        _validate_with_cache(
            text,
            mode=request.mode,
            reference=request.reference,
            perturbations=request.perturbations,
            intent_reference=request.intent_reference,
            formal_properties=request.formal_properties,
            metadata=metadata,
        )
        for text in request.texts
    ]
    metrics = aggregate_robustness(responses)
    return BatchValidateResponse(
        sample_count=len(responses),
        pass_at_k=metrics.pass_at_k,
        stable_at_k=metrics.stable_at_k,
        responses=responses,
        meta=BatchMetaSummary(
            mode=request.mode,
            validator_fingerprint=settings.validator_fingerprint,
        ),
    )


@app.get("/reward_config", response_model=RewardConfigSummary)
def reward_config(_auth: None = Depends(require_read_token)) -> RewardConfigSummary:
    return reward_config_summary(settings)


@app.get("/audit_events", response_model=list[AuditEventSummary])
def audit_event_log(_auth: None = Depends(require_api_token)) -> list[AuditEventSummary]:
    return [AuditEventSummary(**event.__dict__) for event in audit_events.list()]


@app.get("/monitor_summary", response_model=MonitorAggregateSummary)
def monitor_summary(
    _auth: None = Depends(require_read_token),
    x_syvern_tenant: str | None = Header(default=None),
) -> MonitorAggregateSummary:
    tenant_id = _tenant_or_raise(x_syvern_tenant)
    records = _records_for_tenant(validation_records.list(), tenant_id)
    current = aggregate_monitor_summary(records)
    scope_key = _monitor_scope_key(tenant_id)
    previous_monitor_summary = previous_monitor_summaries.get(scope_key)
    if previous_monitor_summary is not None:
        current.divergence_alerts = detect_divergence(previous_monitor_summary, current, settings)
    previous_monitor_summaries[scope_key] = current.model_copy(update={"divergence_alerts": []})
    return current


@app.get("/dashboard_snapshot", response_model=DashboardSnapshot)
def dashboard_snapshot(
    _auth: None = Depends(require_read_token),
    x_syvern_tenant: str | None = Header(default=None),
    limit: int = Query(default=20, ge=0, le=100),
) -> DashboardSnapshot:
    tenant_id = _tenant_or_raise(x_syvern_tenant)
    records = _records_for_tenant(validation_records.list(), tenant_id)
    current = aggregate_monitor_summary(records)
    scope_key = _monitor_scope_key(tenant_id)
    previous_monitor_summary = previous_monitor_summaries.get(scope_key)
    if previous_monitor_summary is not None:
        current.divergence_alerts = detect_divergence(previous_monitor_summary, current, settings)
    previous_monitor_summaries[scope_key] = current.model_copy(update={"divergence_alerts": []})
    return aggregate_dashboard_snapshot(
        records,
        summary=current,
        validator_fingerprint=settings.validator_fingerprint,
        recent_limit=limit,
    )
