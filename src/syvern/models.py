from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


Mode = Literal["online_reward", "full", "data_filter"]
Severity = Literal["error", "warn"]


class ValidateRequest(BaseModel):
    text: str
    reference: dict[str, Any] | None = None
    perturbations: list[str] | None = None
    intent_reference: dict[str, Any] | None = None
    formal_properties: list[str] | None = None
    metadata: dict[str, str] | None = None
    mode: Mode = "online_reward"
    k: int | None = Field(default=None, ge=1)


class BatchValidateRequest(BaseModel):
    texts: list[str] = Field(min_length=1)
    reference: dict[str, Any] | None = None
    perturbations: list[str] | None = None
    intent_reference: dict[str, Any] | None = None
    formal_properties: list[str] | None = None
    metadata: dict[str, str] | None = None
    mode: Mode = "online_reward"


class BatchMetaSummary(BaseModel):
    mode: Mode
    validator_fingerprint: str


class ErrorDetail(BaseModel):
    stage: str
    code: str
    message: str
    location: str | None = None


class Violation(BaseModel):
    rule: str
    severity: Severity
    category: str = "metamodel"


class ElementSummary(BaseModel):
    type: str
    qualified_name: str

    @field_validator("type", "qualified_name")
    @classmethod
    def normalize_non_empty(cls, value: str) -> str:
        normalized = " ".join(value.strip().lower().split())
        if not normalized:
            raise ValueError("element summary fields must not be blank")
        return normalized


class ParseStage(BaseModel):
    reached: bool
    ok: bool
    parser_agreement: bool | None
    errors: list[ErrorDetail] = Field(default_factory=list)


class ResolveStage(BaseModel):
    reached: bool
    ok: bool
    unresolved_refs: int = 0
    errors: list[ErrorDetail] = Field(default_factory=list)


class TypecheckStage(BaseModel):
    reached: bool
    ok: bool
    type_errors: int = 0
    errors: list[ErrorDetail] = Field(default_factory=list)


class ConstraintStage(BaseModel):
    reached: bool
    ok: bool
    violations: list[Violation] = Field(default_factory=list)


class StageSummary(BaseModel):
    parse: ParseStage
    resolve: ResolveStage
    typecheck: TypecheckStage
    constraint: ConstraintStage


class TierSummary(BaseModel):
    t0_pass: bool
    t1_available: bool
    veto: bool


class StructuralSummary(BaseModel):
    evaluated: bool = False
    precision: float = 0.0
    recall: float = 0.0
    f1: float = 0.0
    requirement_coverage: float = 0.0
    ged_accuracy: float | None = None
    hallucinated_elements: int = 0
    exact_matched: int = 0
    normalized_matched: int = 0
    fuzzy_matched: int = 0
    soft_matched: int = 0
    matching_policy_id: str


class RobustnessSummary(BaseModel):
    stable_at_k: float | None = None
    ipt_consistent: bool | None = None


class IntentSummary(BaseModel):
    evaluated: bool = False
    score: float | None = None
    source: Literal["heuristic", "llm_judge", "human"] | None = None


class FormalSummary(BaseModel):
    evaluated: bool = False
    tool: Literal["imandra", "gamma", "nuxmv"] | None = None
    status: Literal["proved", "failed", "unknown", "timeout", "error"] | None = None
    properties_checked: int = 0
    conclusions: list[str] = Field(default_factory=list)
    counterexamples: list[str] = Field(default_factory=list)


class VetoSummary(BaseModel):
    triggered: bool = False
    reason: str | None = None


class MonitorSummary(BaseModel):
    codebleu: float | None = None
    levenshtein: int | None = None


class DivergenceAlert(BaseModel):
    code: str
    message: str
    severity: Severity


class RewardConfigSummary(BaseModel):
    validator_fingerprint: str
    weights: dict[str, float]
    caps: dict[str, int]
    r_max: float
    matching_policy_id: str
    fuzzy_threshold: int
    judge_model: str
    rubric_version: str
    ipt_threshold: float
    data_filter_min_reward: float


class AuditEventSummary(BaseModel):
    method: str
    path: str
    required_permission: str
    outcome: Literal["allowed", "denied"]
    reason: str | None
    token_present: bool
    token_role: str | None
    tenant_id: str | None
    auth_method: Literal["token", "identity"] | None = None
    principal_id: str | None = None
    principal_groups: tuple[str, ...] = ()


class MonitorAggregateSummary(BaseModel):
    record_count: int = Field(ge=0)
    semantic_pass_rate: float = Field(ge=0.0, le=1.0)
    t0_pass_rate: float = Field(ge=0.0, le=1.0)
    t1_available_rate: float = Field(ge=0.0, le=1.0)
    veto_rate: float = Field(ge=0.0, le=1.0)
    average_requirement_coverage: float = Field(ge=0.0, le=1.0)
    average_reward: float
    average_latency_ms: float = Field(ge=0.0)
    stable_at_k: float = Field(ge=0.0, le=1.0)
    formal_evaluated_count: int = Field(ge=0)
    formal_proved_rate: float = Field(ge=0.0, le=1.0)
    formal_failed_rate: float = Field(ge=0.0, le=1.0)
    formal_timeout_rate: float = Field(ge=0.0, le=1.0)
    formal_error_rate: float = Field(ge=0.0, le=1.0)
    divergence_alerts: list[DivergenceAlert] = Field(default_factory=list)


class DashboardTenantSummary(BaseModel):
    tenant_id: str
    record_count: int = Field(ge=0)
    semantic_pass_rate: float = Field(ge=0.0, le=1.0)
    average_reward: float


class DashboardRecentRecord(BaseModel):
    sample_id: str
    text_hash: str
    mode: Mode
    cache_hit: bool
    semantic_pass: bool
    t0_pass: bool
    veto_triggered: bool
    veto_reason: str | None
    reward: float
    latency_ms: int = Field(ge=0)
    tenant_id: str | None
    prompt_id: str | None
    formal_status: str | None


class DashboardSnapshot(BaseModel):
    validator_fingerprint: str
    summary: MonitorAggregateSummary
    tenant_summaries: list[DashboardTenantSummary] = Field(default_factory=list)
    recent_records: list[DashboardRecentRecord] = Field(default_factory=list)


class MetaSummary(BaseModel):
    latency_ms: int
    mode: Mode
    validator_fingerprint: str
    reward: float
    text_hash: str
    cache_hit: bool = False
    data_filter_pass: bool | None = None
    data_filter_reason: Literal["passed", "t0_failed", "vetoed", "reward_below_threshold"] | None = None


class ValidateResponse(BaseModel):
    sample_id: str
    tier_summary: TierSummary
    stage: StageSummary
    structural: StructuralSummary
    robustness: RobustnessSummary
    intent: IntentSummary
    formal: FormalSummary = Field(default_factory=FormalSummary)
    veto: VetoSummary
    monitor: MonitorSummary
    meta: MetaSummary


class BatchValidateResponse(BaseModel):
    sample_count: int = Field(ge=1)
    pass_at_k: float = Field(ge=0.0, le=1.0)
    stable_at_k: float = Field(ge=0.0, le=1.0)
    responses: list[ValidateResponse]
    meta: BatchMetaSummary
