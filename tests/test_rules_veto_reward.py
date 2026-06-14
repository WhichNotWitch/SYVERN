from syvern.adapters.stub import MontiCoreStubAdapter, PilotStubAdapter
from syvern.models import (
    ConstraintStage,
    IntentSummary,
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
from syvern.reward import compute_reward
from syvern.rules import evaluate_rules, weighted_violations
from syvern.settings import SyvernSettings
from syvern.veto import evaluate_veto


def _response(
    intent_score: float | None = None,
    veto: bool = False,
    stage: StageSummary | None = None,
) -> ValidateResponse:
    settings = SyvernSettings()
    stage = stage or StageSummary(
        parse=ParseStage(reached=True, ok=True, parser_agreement=True, errors=[]),
        resolve=ResolveStage(reached=True, ok=True, unresolved_refs=0, errors=[]),
        typecheck=TypecheckStage(reached=True, ok=True, type_errors=0, errors=[]),
        constraint=ConstraintStage(reached=True, ok=True, violations=[]),
    )
    return ValidateResponse(
        sample_id="sample",
        tier_summary=TierSummary(t0_pass=True, t1_available=False, veto=veto),
        stage=stage,
        structural=StructuralSummary(matching_policy_id=settings.matching_policy_id),
        robustness=RobustnessSummary(),
        intent=IntentSummary(evaluated=intent_score is not None, score=intent_score, source=None),
        veto=VetoSummary(triggered=veto, reason="forced" if veto else None),
        monitor=MonitorSummary(),
        meta={
            "latency_ms": 0,
            "mode": "online_reward",
            "validator_fingerprint": settings.validator_fingerprint,
            "reward": 0.0,
            "text_hash": "hash",
            "cache_hit": False,
        },
    )


def test_stub_adapter_reports_triggered_failures():
    adapter = PilotStubAdapter()
    assert not adapter.parse("syntax_error").ok
    assert adapter.resolve("unresolved_ref").unresolved_refs == 1
    assert adapter.typecheck("type_error").type_errors == 1


def test_monticore_stub_disagrees_on_marker():
    pilot = PilotStubAdapter()
    monticore = MontiCoreStubAdapter()
    assert not monticore.parser_agrees("part A parser_disagreement", pilot)


def test_anti_gaming_rules_are_weighted():
    violations = evaluate_rules("filler filler filler", SyvernSettings())
    assert any(v.rule == "no_filler_text" for v in violations)
    assert weighted_violations(violations) >= 2


def test_repetition_rule_applies_below_min_tokens():
    violations = evaluate_rules("x x", SyvernSettings())
    rules = {v.rule for v in violations}
    assert "no_excessive_repetition" in rules
    assert "minimum_model_signal" in rules


def test_veto_triggers_for_error_anti_gaming_rule():
    settings = SyvernSettings()
    violations = evaluate_rules("filler filler filler", settings)
    veto = evaluate_veto(
        text="filler filler filler",
        settings=settings,
        semantic_path_passed=True,
        parser_agreement=True,
        violations=violations,
    )
    assert veto.triggered
    assert veto.reason == "anti_gaming_rule"


def test_reward_is_zero_when_veto_triggers():
    assert compute_reward(_response(veto=True), SyvernSettings()) == 0.0


def test_intent_score_does_not_affect_reward():
    settings = SyvernSettings()
    low = compute_reward(_response(intent_score=0.0), settings)
    high = compute_reward(_response(intent_score=5.0), settings)
    assert low == high


def test_reward_does_not_credit_downstream_when_parse_fails():
    settings = SyvernSettings()
    stage = StageSummary(
        parse=ParseStage(reached=True, ok=False, parser_agreement=False, errors=[]),
        resolve=ResolveStage(reached=True, ok=True, unresolved_refs=0, errors=[]),
        typecheck=TypecheckStage(reached=True, ok=True, type_errors=0, errors=[]),
        constraint=ConstraintStage(reached=True, ok=True, violations=[]),
    )

    assert compute_reward(_response(stage=stage), settings) == 0.0


def test_reward_does_not_credit_unreached_typecheck_or_constraint_after_resolve_failure():
    settings = SyvernSettings()
    stage = StageSummary(
        parse=ParseStage(reached=True, ok=True, parser_agreement=True, errors=[]),
        resolve=ResolveStage(reached=True, ok=False, unresolved_refs=1, errors=[]),
        typecheck=TypecheckStage(reached=False, ok=True, type_errors=0, errors=[]),
        constraint=ConstraintStage(reached=False, ok=True, violations=[]),
    )

    assert compute_reward(_response(stage=stage), settings) == settings.weights.w0


def test_reward_credits_reached_typecheck_and_only_reached_constraint():
    settings = SyvernSettings()
    stage_without_constraint = StageSummary(
        parse=ParseStage(reached=True, ok=True, parser_agreement=True, errors=[]),
        resolve=ResolveStage(reached=True, ok=True, unresolved_refs=0, errors=[]),
        typecheck=TypecheckStage(reached=True, ok=False, type_errors=2, errors=[]),
        constraint=ConstraintStage(reached=False, ok=True, violations=[]),
    )
    stage_with_constraint = StageSummary(
        parse=ParseStage(reached=True, ok=True, parser_agreement=True, errors=[]),
        resolve=ResolveStage(reached=True, ok=True, unresolved_refs=0, errors=[]),
        typecheck=TypecheckStage(reached=True, ok=False, type_errors=2, errors=[]),
        constraint=ConstraintStage(reached=True, ok=True, violations=[]),
    )
    typecheck_credit = settings.weights.w2 * (1 - 2 / settings.cap_type)

    assert compute_reward(_response(stage=stage_without_constraint), settings) == (
        settings.weights.w0 + settings.weights.w1 + typecheck_credit
    )
    assert compute_reward(_response(stage=stage_with_constraint), settings) == (
        settings.weights.w0 + settings.weights.w1 + typecheck_credit + settings.weights.w3
    )
