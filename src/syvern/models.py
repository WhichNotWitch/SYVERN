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
    mode: Mode = "online_reward"
    k: int | None = Field(default=None, ge=1)


class BatchValidateRequest(BaseModel):
    texts: list[str] = Field(min_length=1)
    reference: dict[str, Any] | None = None
    perturbations: list[str] | None = None
    intent_reference: dict[str, Any] | None = None
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
    parser_agreement: bool
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
    matching_policy_id: str


class RobustnessSummary(BaseModel):
    stable_at_k: float | None = None
    ipt_consistent: bool | None = None


class IntentSummary(BaseModel):
    evaluated: bool = False
    score: float | None = None
    source: Literal["llm_judge", "human"] | None = None


class VetoSummary(BaseModel):
    triggered: bool = False
    reason: str | None = None


class MonitorSummary(BaseModel):
    codebleu: float | None = None
    levenshtein: int | None = None


class MetaSummary(BaseModel):
    latency_ms: int
    mode: Mode
    validator_fingerprint: str
    reward: float
    text_hash: str
    cache_hit: bool = False


class ValidateResponse(BaseModel):
    sample_id: str
    tier_summary: TierSummary
    stage: StageSummary
    structural: StructuralSummary
    robustness: RobustnessSummary
    intent: IntentSummary
    veto: VetoSummary
    monitor: MonitorSummary
    meta: MetaSummary


class BatchValidateResponse(BaseModel):
    sample_count: int = Field(ge=1)
    pass_at_k: float = Field(ge=0.0, le=1.0)
    stable_at_k: float = Field(ge=0.0, le=1.0)
    responses: list[ValidateResponse]
    meta: BatchMetaSummary
