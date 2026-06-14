import pytest

from syvern.models import (
    ConstraintStage,
    IntentSummary,
    MetaSummary,
    MonitorSummary,
    ParseStage,
    ResolveStage,
    RobustnessSummary,
    StageSummary,
    StructuralSummary,
    TierSummary,
    TypecheckStage,
    ValidateResponse,
    VetoSummary,
)
from syvern.robustness import aggregate_robustness, semantic_pass
from syvern.settings import SyvernSettings


def _response(parse_ok=True, resolve_ok=True, typecheck_ok=True):
    settings = SyvernSettings()
    stage = StageSummary(
        parse=ParseStage(reached=True, ok=parse_ok, parser_agreement=True, errors=[]),
        resolve=ResolveStage(reached=parse_ok, ok=resolve_ok, unresolved_refs=0, errors=[]),
        typecheck=TypecheckStage(reached=parse_ok and resolve_ok, ok=typecheck_ok, type_errors=0, errors=[]),
        constraint=ConstraintStage(reached=parse_ok and resolve_ok, ok=True, violations=[]),
    )
    return ValidateResponse(
        sample_id="sample",
        tier_summary=TierSummary(t0_pass=parse_ok and resolve_ok and typecheck_ok, t1_available=False, veto=False),
        stage=stage,
        structural=StructuralSummary(matching_policy_id=settings.matching_policy_id),
        robustness=RobustnessSummary(),
        intent=IntentSummary(),
        veto=VetoSummary(),
        monitor=MonitorSummary(),
        meta=MetaSummary(
            latency_ms=0,
            mode="online_reward",
            validator_fingerprint=settings.validator_fingerprint,
            reward=0.0,
            text_hash="hash",
            cache_hit=False,
        ),
    )


def test_semantic_pass_requires_parse_resolve_and_typecheck():
    assert semantic_pass(_response()) is True
    assert semantic_pass(_response(parse_ok=False)) is False
    assert semantic_pass(_response(resolve_ok=False)) is False
    assert semantic_pass(_response(typecheck_ok=False)) is False


def test_aggregate_robustness_computes_pass_at_k_and_stable_at_k():
    metrics = aggregate_robustness([
        _response(),
        _response(typecheck_ok=False),
        _response(resolve_ok=False),
    ])

    assert metrics.pass_at_k == 1.0
    assert metrics.stable_at_k == pytest.approx(1 / 3)


def test_aggregate_robustness_reports_zero_when_no_sample_passes():
    metrics = aggregate_robustness([
        _response(parse_ok=False),
        _response(typecheck_ok=False),
    ])

    assert metrics.pass_at_k == 0.0
    assert metrics.stable_at_k == 0.0


def test_aggregate_robustness_rejects_empty_responses():
    with pytest.raises(ValueError, match="responses must not be empty"):
        aggregate_robustness([])
